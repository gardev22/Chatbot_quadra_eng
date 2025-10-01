# openai_backend.py

import io
import numpy as np
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account
from openai import OpenAI
import faiss

# ================== CONFIGURAÇÕES ==================
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o"
EMBED_MODEL = "text-embedding-3-small"
TOP_K = 5
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"

client = OpenAI(api_key=API_KEY)

# ================== GOOGLE DRIVE ==================
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_file(
    "service_account.json", scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)

# ================== FUNÇÕES DOCX ==================
def dividir_texto_em_blocos(texto, max_palavras=200):
    palavras = texto.split()
    blocos = []
    for i in range(0, len(palavras), max_palavras):
        blocos.append(" ".join(palavras[i:i+max_palavras]))
    return blocos

def carregar_docx_drive(file_id, file_name):
    request = drive_service.files().get_media(fileId=file_id)
    downloader = request.execute()
    doc = Document(io.BytesIO(downloader))
    texto = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    blocos_divididos = dividir_texto_em_blocos(texto)
    blocos = [{"pagina": file_name, "texto": t, "file_id": file_id} for t in blocos_divididos]
    return blocos

def carregar_docx_pasta_drive(folder_id):
    query = f"'{folder_id}' in parents and mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    blocos = []
    for f in files:
        blocos.extend(carregar_docx_drive(f["id"], f["name"]))
    return blocos

# ================== AGRUPAMENTO ==================
def agrupar_blocos(blocos, janela=3):
    blocos_agrupados = []
    for i in range(len(blocos)):
        grupo = blocos[i:i+janela]
        texto_agregado = " ".join([b["texto"] for b in grupo])
        blocos_agrupados.append({
            "pagina": grupo[0]["pagina"],
            "texto": texto_agregado,
            "file_id": grupo[0]["file_id"]
        })
    return blocos_agrupados

# ================== EMBEDDINGS ==================
def embed_text(texto):
    resp = client.embeddings.create(model=EMBED_MODEL, input=texto)
    return np.array(resp.data[0].embedding, dtype="float32")

def preparar_index(blocos):
    embeddings = []
    for b in blocos:
        embeddings.append(embed_text(b["texto"]))
    dim = len(embeddings[0])
    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(np.array(embeddings))
    index.add(np.array(embeddings))
    return index, np.array(embeddings), blocos

# ================== CONSULTAS ==================
def consultar_com_embeddings(pergunta, index, blocos_com_embeds, top_k=TOP_K):
    vec = embed_text(pergunta)
    faiss.normalize_L2(vec.reshape(1, -1))
    scores, idxs = index.search(vec.reshape(1, -1), top_k)
    return [blocos_com_embeds[i] for i in idxs[0] if i < len(blocos_com_embeds)]

# ================== PERGUNTA/RESPOSTA ==================
def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"
    prompt = (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Responda somente com base nos documentos fornecidos.\n"
        "### Regras:\n"
        "1. Não invente nada.\n"
        "2. Se deduzir algo, explique.\n"
        "3. Se não houver informação, diga explicitamente.\n\n"
        f"{contexto}\nPergunta: {pergunta}\n\n➡️ Resposta:"
    )
    return prompt

def responder_pergunta(pergunta, client=client, blocos_contexto=None,
                        index=None, blocos_com_embeds=None,
                        model_id=MODEL_ID, top_k=TOP_K, streaming=False):
    
    if blocos_contexto is None or index is None or blocos_com_embeds is None:
        # Inicializa blocos e índice
        blocos_raw = carregar_docx_pasta_drive(FOLDER_ID)
        blocos_contexto = agrupar_blocos(blocos_raw)
        index, _, blocos_com_embeds = preparar_index(blocos_contexto)

    blocos_relevantes = consultar_com_embeddings(pergunta, index, blocos_com_embeds, top_k)
    prompt = montar_prompt_rag(pergunta, blocos_relevantes)

    # ====== Requisição ao modelo ======
    resposta = ""
    if streaming:
        for chunk in client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "Você é um assistente que responde apenas com base nos documentos."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3,
            stream=True
        ):
            delta = chunk.choices[0].delta.get("content", "")
            resposta += delta
            yield delta
    else:
        completion = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "Você é um assistente que responde apenas com base nos documentos."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3
        )
        resposta = completion.choices[0].message["content"]

    # link do documento mais relevante
    if blocos_relevantes:
        primeiro = blocos_relevantes[0]
        doc_id = primeiro.get("file_id")
        doc_nome = primeiro.get("pagina", "?")
        if doc_id:
            link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
            resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

    if streaming:
        yield resposta
    else:
        return resposta
