import os
import io
import numpy as np
import requests
import streamlit as st
import faiss
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account
from openai import OpenAI

# === CONFIGURAÇÕES ===
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o"
EMBED_MODEL = "text-embedding-3-small"
TOP_K = 5  # menos blocos para reduzir tokens

# Id da Pasta do Google Drive (substitua pelo seu)
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"

client = OpenAI(api_key=API_KEY)

# === 0. Autenticação Google Drive ===
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_info(
    dict(st.secrets["gcp_service_account"]), scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)


# === 1. Funções para carregar DOCX do Drive em blocos menores ===
def dividir_texto_em_blocos(texto, max_palavras=200):
    palavras = texto.split()
    blocos = []
    for i in range(0, len(palavras), max_palavras):
        bloco = " ".join(palavras[i:i+max_palavras])
        blocos.append(bloco)
    return blocos

def carregar_docx_drive(file_id, file_name):
    """Lê o conteúdo de um DOCX do Drive sem salvar em disco, quebrando em blocos de 200 palavras"""
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


# === 2. Agrupa blocos em janelas deslizantes (para contexto) ===
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

    dim = len(embeddings[0])
    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(np.array(embeddings))
    index.add(np.array(embeddings))
    return index, np.array(embeddings), blocos_com_embeds


# === 4. Prepara os blocos e índice ===
blocos_raw = carregar_docx_pasta_drive(FOLDER_ID)
blocos_contexto = agrupar_blocos(blocos_raw, janela=3)
index, embeddings, blocos_com_embeds = preparar_index(blocos_contexto)


# === 5. Consulta com FAISS ===
def consultar_com_embeddings(pergunta, top_k=TOP_K):
    vec = embed_text(pergunta)
    faiss.normalize_L2(vec.reshape(1, -1))
    scores, idxs = index.search(vec.reshape(1, -1), top_k)
    return [blocos_com_embeds[i] for i in idxs[0] if i < len(blocos_com_embeds)]


# === 6. Pergunta de ordem/sequência ===
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
    return "Essa etapa não foi encontrada no conteúdo."


# === 7. Monta o prompt refinado ===
def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"

    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Sua tarefa é analisar cuidadosamente os documentos fornecidos e responder à pergunta com base neles.\n\n"
        "### Regras de resposta:\n"
        "1. Use SOMENTE as informações dos documentos. Não invente nada.\n"
        "2. Se a resposta não estiver escrita de forma explícita, mas puder ser deduzida a partir dos documentos, você deve apresentar a dedução de forma clara.\n"
        "   - Exemplo: se o documento lista várias responsabilidades e não menciona ASO, você pode responder: 'O documento não cita ASO como responsabilidade do departamento pessoal.'\n"
        "3. Se realmente não houver nenhuma evidência, diga exatamente:\n"
        "   'Essa informação não está disponível nos documentos fornecidos.'\n"
        "4. Estruture a resposta em tópicos ou frases completas, e cite trechos relevantes entre aspas sempre que possível.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )


# === 8. Requisição ao modelo (com streaming) ===
def responder_pergunta(pergunta, blocos=blocos_contexto, api_key=API_KEY, model_id=MODEL_ID, top_k=TOP_K):
    try:
        pergunta = pergunta.strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        # checa perguntas de sequência
        resposta_seq = responder_etapa_seguinte(pergunta, blocos_raw)
        if resposta_seq:
            return resposta_seq

        # consulta via embeddings
        blocos_relevantes = consultar_com_embeddings(pergunta, top_k)
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        resposta = ""
        for chunk in client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "Você é um assistente que responde com base somente no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3,
            stream=True
        ):
            delta = chunk.choices[0].delta.get("content", "")
            resposta += delta
            yield delta  # streaming para exibição no frontend

        # link do documento mais relevante
        if blocos_relevantes:
            primeiro = blocos_relevantes[0]
            doc_id = primeiro.get("file_id")
            doc_nome = primeiro.get("pagina", "?")
            if doc_id:
                link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

        yield resposta

    except Exception as e:
        yield f"❌ Erro interno: {e}"


# === 9. Teste manual ===
if __name__ == "__main__":
    print("\nDigite sua pergunta com base no conteúdo dos DOCX do Google Drive. Digite 'sair' para encerrar.\n")
    while True:
        pergunta = input("Pergunta: ").strip()
        if pergunta.lower() in ["sair", "exit", "quit"]:
            print("\nEncerrando...")
            break
        elif not pergunta or len(pergunta) < 3:
            print("⚠️ Pergunta muito curta.")
            continue

        resposta_final = ""
        for parte in responder_pergunta(pergunta):
            print(parte, end="", flush=True)
            resposta_final += parte
        print("\n")
