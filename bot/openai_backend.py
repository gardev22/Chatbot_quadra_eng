import os
import io
import numpy as np
import faiss
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account
from openai import OpenAI
import streamlit as st

# === CONFIGURAÇÕES ===
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o"  # modelo principal
EMBED_MODEL = "text-embedding-3-small"
TOP_K = 5  # blocos retornados no contexto

# Id da Pasta do Google Drive (troque pelo seu)
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"

client = OpenAI(api_key=API_KEY)

# === 0. Autenticação Google Drive ===
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_info(
    dict(st.secrets["gcp_service_account"]), scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)


# === 1. Funções para carregar DOCX do Drive ===
def dividir_texto_em_blocos(texto, max_palavras=200):
    palavras = texto.split()
    blocos = []
    for i in range(0, len(palavras), max_palavras):
        bloco = " ".join(palavras[i:i+max_palavras])
        blocos.append(bloco)
    return blocos

def carregar_docx_drive(file_id, file_name):
    """Lê o conteúdo de um DOCX do Drive e divide em blocos"""
    request = drive_service.files().get_media(fileId=file_id)
    downloader = request.execute()
    doc = Document(io.BytesIO(downloader))

    texto = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    blocos_divididos = dividir_texto_em_blocos(texto, max_palavras=200)

    blocos = []
    for trecho in blocos_divididos:
        blocos.append({
            "pagina": file_name,
            "texto": trecho,
            "file_id": file_id
        })
    return blocos

@st.cache_data
def carregar_docx_pasta_drive(folder_id):
    """Carrega todos os DOCX de uma pasta do Drive em memória"""
    query = f"'{folder_id}' in parents and mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    blocos = []
    for file in files:
        blocos.extend(carregar_docx_drive(file["id"], file["name"]))
    return blocos


# === 2. Agrupa blocos em janelas deslizantes ===
def agrupar_blocos(blocos, janela=3):
    blocos_agrupados = []
    for i in range(len(blocos)):
        grupo = blocos[i:i+janela]
        texto_agregado = " ".join([b["texto"] for b in grupo])
        pagina = grupo[0].get("pagina", "?")
        file_id = grupo[0].get("file_id", None)
        blocos_agrupados.append({
            "pagina": pagina,
            "texto": texto_agregado,
            "file_id": file_id
        })
    return blocos_agrupados


# === 3. Embeddings e FAISS ===
def embed_text(texto):
    resp = client.embeddings.create(model=EMBED_MODEL, input=texto)
    return np.array(resp.data[0].embedding, dtype="float32")

@st.cache_resource
def preparar_index(blocos):
    """Cria índice FAISS em memória"""
    blocos_com_embeds = []
    embeddings = []
    for b in blocos:
        vec = embed_text(b["texto"])
        embeddings.append(vec)
        blocos_com_embeds.append(b)

    embeddings_np = np.array(embeddings, dtype="float32")
    faiss.normalize_L2(embeddings_np)
    index = faiss.IndexFlatIP(embeddings_np.shape[1])
    index.add(embeddings_np)

    return index, embeddings_np, blocos_com_embeds


# === 4. Pré-carrega os blocos e índice ===
blocos_raw = carregar_docx_pasta_drive(FOLDER_ID)
blocos_contexto = agrupar_blocos(blocos_raw, janela=3)
index, embeddings, blocos_com_embeds = preparar_index(blocos_contexto)


# === 5. Consulta FAISS ===
def consultar_com_embeddings(pergunta, top_k=TOP_K):
    vec = embed_text(pergunta)
    faiss.normalize_L2(vec.reshape(1, -1))
    scores, idxs = index.search(vec.reshape(1, -1), top_k)
    return [blocos_com_embeds[i] for i in idxs[0] if i < len(blocos_com_embeds)]


# === 6. Perguntas de sequência ===
def responder_etapa_seguinte(pergunta, blocos):
    if not any(x in pergunta.lower() for x in ["após", "depois de", "seguinte a"]):
        return None

    trecho = pergunta.lower().split("após")[-1].strip()
    trecho = trecho.split("depois de")[-1].strip() if "depois de" in pergunta.lower() else trecho
    trecho = trecho.split("seguinte a")[-1].strip() if "seguinte a" in pergunta.lower() else trecho

    for i, bloco in enumerate(blocos):
        if trecho.lower() in bloco["texto"].lower():
            if i + 1 < len(blocos):
                return f"A etapa após \"{trecho}\" é \"{blocos[i+1]['texto'].splitlines()[0]}\"."
            else:
                return f"A etapa \"{trecho}\" é a última registrada."
    return "Essa etapa não foi encontrada nos documentos."


# === 7. Prompt RAG ===
def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"

    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Responda somente com base nos documentos fornecidos.\n\n"
        "### Regras:\n"
        "1. Use SOMENTE as informações dos documentos. Não invente nada.\n"
        "2. Se não houver resposta clara, diga: 'Essa informação não está disponível nos documentos fornecidos.'\n"
        "3. Estruture a resposta em tópicos ou frases completas e cite trechos relevantes quando possível.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )


# === 8. Função principal (com streaming) ===
def responder_pergunta(pergunta, blocos=blocos_contexto, model_id=MODEL_ID, top_k=TOP_K):
    try:
        pergunta = pergunta.strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            yield "⚠️ Pergunta vazia."
            return

        # Perguntas de sequência
        resposta_seq = responder_etapa_seguinte(pergunta, blocos_raw)
        if resposta_seq:
            yield resposta_seq
            return

        # Embeddings
        blocos_relevantes = consultar_com_embeddings(pergunta, top_k)
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        resposta_final = ""
        stream = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "Você é um assistente que responde com base somente nos documentos fornecidos."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3,
            stream=True
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.get("content", "")
            if delta:
                resposta_final += delta
                yield delta

        # Anexa link do documento mais relevante
        if blocos_relevantes:
            primeiro = blocos_relevantes[0]
            doc_id = primeiro.get("file_id")
            doc_nome = primeiro.get("pagina", "?")
            if doc_id:
                link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                extra = f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"
                resposta_final += extra
                yield extra

    except Exception as e:
        yield f"❌ Erro interno: {e}"
