import io
import re
import json
import numpy as np
import requests
import streamlit as st
from html import escape
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ========= CONFIG =========
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o-mini"
TOP_K = 4
TOP_N_ANN = 60
MAX_TOKENS = 350
TEMPERATURE = 0.15
REQUEST_TIMEOUT = 30

CACHE_BUSTER = "2025-10-14-02"

FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"  # pasta no Drive
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)
CE_SCORE_THRESHOLD = 0.42

# ========= HTTP SESSION =========
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY.strip()}",
    "Content-Type": "application/json"
})

# ========= UTILS =========
def sanitize_doc_name(name: str) -> str:
    name = re.sub(r"^(C[oó]pia de|Copy of)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\.(docx?|pdf|txt)$", "", name, flags=re.IGNORECASE)
    return name.strip()

def split_text_blocks(text, max_words=200):
    words = text.split()
    blocks = []
    for i in range(0, len(words), max_words):
        blocks.append(" ".join(words[i:i+max_words]))
    return blocks

def docx_to_blocks(file_bytes, file_name, file_id, max_words=200):
    doc = Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    small_blocks = split_text_blocks(text, max_words)
    return [{"pagina": file_name, "texto": chunk, "file_id": file_id} for chunk in small_blocks if chunk.strip()]

# ========= GOOGLE DRIVE =========
@st.cache_resource(show_spinner=False)
def get_drive_client(_v=CACHE_BUSTER):
    creds = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def list_docx_files(drive_service):
    query = f"'{FOLDER_ID}' in parents and mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    results = drive_service.files().list(q=query, fields="files(id,name)").execute()
    return results.get("files", [])

def download_docx(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    return request.execute()

# ========= CACHE DE BLOCOS E EMBEDDINGS =========
@st.cache_data(show_spinner=False)
def load_blocks_and_embeddings(_v=CACHE_BUSTER):
    from sentence_transformers import SentenceTransformer
    drive = get_drive_client()
    files = list_docx_files(drive)
    all_blocks = []
    for f in files:
        bytes_ = download_docx(drive, f["id"])
        all_blocks.extend(docx_to_blocks(bytes_, f["name"], f["id"], max_words=200))
    
    if not all_blocks:
        return {"blocks": [], "emb": None, "index": None, "use_faiss": False}

    # Agrupamento simples (janela de 3 blocos)
    grouped = []
    for i in range(len(all_blocks)):
        group = all_blocks[i:i+3]
        if group:
            grouped.append({
                "pagina": group[0]["pagina"],
                "texto": " ".join([b["texto"] for b in group]),
                "file_id": group[0]["file_id"]
            })
    
    sbert = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    texts = [b["texto"] for b in grouped]
    emb = sbert.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

    # FAISS opcional
    try:
        import faiss
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(emb.astype(np.float32))
        use_faiss = True
    except Exception:
        index = None
        use_faiss = False

    return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}

# ========= ANN SEARCH =========
def ann_search(query_text, top_n=TOP_N_ANN):
    vecdb = load_blocks_and_embeddings()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    from sentence_transformers import SentenceTransformer
    sbert = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    q = sbert.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    if vecdb["use_faiss"]:
        import faiss
        D, I = vecdb["index"].search(q.reshape(1,-1).astype(np.float32), top_n)
        idxs = I[0].tolist()
        scores = D[0].tolist()
    else:
        emb = vecdb["emb"]
        scores = emb @ q
        idxs = np.argsort(-scores)[:top_n]
        scores = scores[idxs].tolist()

    candidates = [{"idx": i, "score": s, "block": blocks[i]} for i, s in zip(idxs, scores) if i >= 0]
    return candidates

# ========= CROSS-ENCODER =========
@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    import torch
    from sentence_transformers import CrossEncoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)

def crossencoder_rerank(query, candidates, top_k=TOP_K):
    if not candidates:
        return []
    ce = get_cross_encoder()
    pairs = [(query, c["block"]["texto"]) for c in candidates]
    scores = ce.predict(pairs, batch_size=64)
    packed = [{"block": c["block"], "score": float(s)} for c, s in zip(candidates, scores)]
    packed.sort(key=lambda x: x["score"], reverse=True)
    return packed[:top_k]

# ========= ETAPA SEGUINTE =========
def responder_etapa_seguinte(pergunta, blocos_raw):
    if not any(x in pergunta.lower() for x in ["após", "depois de", "seguinte a"]):
        return None
    trecho = pergunta.lower()
    for token in ["após", "depois de", "seguinte a"]:
        if token in trecho:
            trecho = trecho.split(token,1)[-1].strip()
    if not trecho:
        return None
    for i, b in enumerate(blocos_raw):
        if trecho in b["texto"].lower():
            if i+1 < len(blocos_raw):
                prox = blocos_raw[i+1]["texto"].splitlines()[0]
                return f'A etapa após "{trecho}" é "{prox}".'
            else:
                return f'A etapa "{trecho}" é a última registrada.'
    return "Essa etapa não foi encontrada no conteúdo."

# ========= PROMPT =========
def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina','?')}]:\n{b['texto']}\n\n"
    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Sua tarefa é analisar cuidadosamente os documentos fornecidos e responder à pergunta com base neles.\n\n"
        "### Regras de resposta:\n"
        f"3. Se não houver evidência, diga:\n{FALLBACK_MSG}\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n➡️ Resposta:"
    )

# ========= RESPOSTA =========
def responder_pergunta(pergunta):
    try:
        pergunta = (pergunta or "").strip()
        if not pergunta:
            return "⚠️ Pergunta vazia."
        vecdb = load_blocks_and_embeddings()
        blocos_raw = vecdb["blocks"]

        seq = responder_etapa_seguinte(pergunta, blocos_raw)
        if seq:
            return seq

        candidates = ann_search(pergunta)
        if not candidates:
            return FALLBACK_MSG

        reranked = crossencoder_rerank(pergunta, candidates)
        best_score = reranked[0]["score"] if reranked else 0.0
        if best_score < CE_SCORE_THRESHOLD:
            return FALLBACK_MSG

        blocos_relevantes = [r["block"] for r in reranked]
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        payload = {
            "model": MODEL_ID,
            "messages": [
                {"role":"system","content":"Você é um assistente que responde apenas com base no conteúdo fornecido."},
                {"role":"user","content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE
        }

        resp = session.post("https://api.openai.com/v1/chat/completions", json=payload, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            return f"❌ Erro na API: {resp.status_code} - {resp.text}"

        data = resp.json()
        escolha = data.get("choices", [])
        if not escolha or "message" not in escolha[0]:
            return "⚠️ Resposta da API vazia ou incompleta."

        resposta = escolha[0]["message"]["content"]

        # link do primeiro documento relevante
        if resposta.strip() != FALLBACK_MSG and blocos_relevantes:
            primeiro = blocos_relevantes[0]
            doc_id = primeiro.get("file_id")
            doc_nome = sanitize_doc_name(primeiro.get("pagina","?"))
            if doc_id:
                link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

        return resposta
    except Exception as e:
        return f"❌ Erro interno: {e}"
