import os
import io
import re
import time
import json
import numpy as np
import pandas as pd
import requests
import streamlit as st
from html import escape
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ========= CONFIG =========
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o-mini"          # você pode testar "gpt-4o-mini" para ainda mais velocidade
TOP_K = 5                         # blocos finais enviados ao LLM
TOP_N_ANN = 80                    # candidatos do estágio 1 (ANN) antes do reranker
MAX_TOKENS = 500                  # resposta menor tende a ser mais rápida
TEMPERATURE = 0.2
REQUEST_TIMEOUT = 40              # segundos

# Pasta do Google Drive
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# ========= MENSAGEM PADRÃO E THRESHOLD =========
FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)
CE_SCORE_THRESHOLD = 0.42  # ajuste fino: 0.38~0.48 funciona bem com o MiniLM

# ========= CACHE BUSTER (force refresh geral) =========
CACHE_BUSTER = "2025-10-08-01"

# ========= UTILS =========
def sanitize_doc_name(name: str) -> str:
    """Remove 'Cópia de', 'Copy of' e extensões (.doc/.docx/.pdf/.txt), além de espaços extras."""
    name = re.sub(r"^(C[oó]pia de|Copy of)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\.(docx?|pdf|txt)$", "", name, flags=re.IGNORECASE)
    return name.strip()

# ========= CLIENTES E MODELOS (CACHEADOS) =========
@st.cache_resource(show_spinner=False)
def get_drive_client(_v=CACHE_BUSTER):
    creds = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

@st.cache_resource(show_spinner=False)
def get_sbert_model(_v=CACHE_BUSTER):
    from sentence_transformers import SentenceTransformer
    # modelo pequeno e rápido; ótimo custo/benefício
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return model

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    import torch
    from sentence_transformers import CrossEncoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)
    return ce

# ========= LISTAGEM E DOWNLOAD (DRIVE) =========
def _list_docx_metadata(drive_service, folder_id):
    query = (
        f"'{folder_id}' in parents and "
        "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    )
    fields = "files(id, name, md5Checksum, modifiedTime)"
    results = drive_service.files().list(q=query, fields=fields).execute()
    return results.get("files", [])

def _download_docx_bytes(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    return request.execute()

# ========= PARSE DOCX EM BLOCOS =========
def _split_text_blocks(text, max_words=200):
    words = text.split()
    blocks = []
    for i in range(0, len(words), max_words):
        blocks.append(" ".join(words[i:i + max_words]))
    return blocks

def _docx_to_blocks(file_bytes, file_name, file_id, max_words=200):
    doc = Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    small_blocks = _split_text_blocks(text, max_words=max_words)
    out = []
    for chunk in small_blocks:
        if chunk.strip():
            out.append({"pagina": file_name, "texto": chunk, "file_id": file_id})
    return out

# ========= CACHE DE METADADOS E CONTEÚDO (ASSINATURA) =========
@st.cache_data(show_spinner=False)
def _list_docx_metadata_cached(folder_id: str, _v=CACHE_BUSTER):
    drive = get_drive_client()
    files = _list_docx_metadata(drive, folder_id)
    return files

def _build_signature(files_meta):
    payload = sorted(
        [{k: f.get(k) for k in ("id", "name", "md5Checksum", "modifiedTime")} for f in files_meta],
        key=lambda x: x["id"]
    )
    return json.dumps(payload, ensure_ascii=False)

@st.cache_data(show_spinner=False)
def _download_and_parse_blocks(signature: str, folder_id: str, _v=CACHE_BUSTER):
    """
    Função pesada, cacheada **em cima da assinatura**.
    Quando qualquer nome/arquivo muda, a signature muda e o cache invalida.
    """
    drive = get_drive_client()
    files = _list_docx_metadata(drive, folder_id)
    all_blocks = []
    for f in files:
        bytes_ = _download_docx_bytes(drive, f["id"])
        all_blocks.extend(_docx_to_blocks(bytes_, f["name"], f["id"], max_words=200))
    return all_blocks

def load_all_blocks_cached(folder_id: str):
    files = _list_docx_metadata_cached(folder_id)
    signature = _build_signature(files)
    all_blocks = _download_and_parse_blocks(signature, folder_id)
    return all_blocks, signature

# ========= AGRUPAMENTO EM JANELA DESLIZANTE =========
def agrupar_blocos(blocos, janela=3):
    grouped = []
    for i in range(len(blocos)):
        group = blocos[i:i+janela]
        if not group:
            continue
        texto_agregado = " ".join([b["texto"] for b in group])
        grouped.append({
            "pagina": group[0].get("pagina", "?"),
            "texto": texto_agregado,
            "file_id": group[0].get("file_id")
        })
    return grouped

# ========= ÍNDICE VETORIAL (FAISS se disponível) =========
def try_import_faiss():
    try:
        import faiss  # type: ignore
        return faiss
    except Exception:
        return None

@st.cache_resource(show_spinner=False)
def build_vector_index(_v=CACHE_BUSTER):
    """
    1) Carrega blocos do Drive (cacheados)
    2) Agrupa em janelas (contexto)
    3) Calcula embeddings (cacheados)
    4) Cria índice FAISS (ou numpy fallback)
    Retorna um dicionário com tudo que precisamos na consulta.
    """
    blocks_raw, _sig = load_all_blocks_cached(FOLDER_ID)
    grouped = agrupar_blocos(blocks_raw, janela=3)
    if not grouped:
        return {"blocks": [], "emb": None, "index": None, "use_faiss": False}

    sbert = get_sbert_model()
    texts = [b["texto"] for b in grouped]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, _v2=CACHE_BUSTER):
        # embeddings de todos os blocos (cacheados)
        return sbert.encode(texts_, convert_to_numpy=True, normalize_embeddings=True)

    emb = _embed_texts_cached(texts)

    faiss = try_import_faiss()
    use_faiss = False
    index = None
    if faiss is not None:
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)  # inner product com vetores normalizados = cos sim
        index.add(emb.astype(np.float32))
        use_faiss = True

    return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}

def ann_search(query_text: str, top_n: int):
    """Busca ANN top_n com FAISS (se houver) ou NumPy fallback."""
    vecdb = build_vector_index()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    sbert = get_sbert_model()
    q = sbert.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    if vecdb["use_faiss"]:
        import faiss  # type: ignore
        D, I = vecdb["index"].search(q.reshape(1, -1).astype(np.float32), top_n)
        idxs = I[0].tolist()
        scores = D[0].tolist()
    else:
        emb = vecdb["emb"]  # (N, d)
        scores = (emb @ q)          # cos sim com embeddings normalizados
        idxs = np.argsort(-scores)[:top_n].tolist()
        scores = scores[idxs].tolist()

    candidates = [{"idx": i, "score": s, "block": blocks[i]} for i, s in zip(idxs, scores) if i >= 0]
    return candidates

# ========= RERANKING (RETORNA SCORES) =========
def crossencoder_rerank(query: str, candidates, top_k: int):
    """
    Retorna uma lista de dicts: {"block": ..., "score": float}
    """
    if not candidates:
        return []

    ce = get_cross_encoder()
    pairs = [(query, c["block"]["texto"]) for c in candidates]
    scores = ce.predict(pairs, batch_size=64)
    packed = [{"block": c["block"], "score": float(s)} for c, s in zip(candidates, scores)]
    packed.sort(key=lambda x: x["score"], reverse=True)
    return packed[:top_k]

# ========= DETECÇÃO DE ETAPA SEGUINTE (mesma lógica, rápida) =========
def responder_etapa_seguinte(pergunta, blocos_raw):
    if not any(x in pergunta.lower() for x in ["após", "depois de", "seguinte a"]):
        return None

    trecho = pergunta.lower()
    for token in ["após", "depois de", "seguinte a"]:
        if token in trecho:
            trecho = trecho.split(token, 1)[-1].strip()
    if not trecho:
        return None

    for i, b in enumerate(blocos_raw):
        if trecho.lower() in b["texto"].lower():
            if i + 1 < len(blocos_raw):
                prox = blocos_raw[i+1]['texto'].splitlines()[0]
                return f'A etapa após "{trecho}" é "{prox}".'
            else:
                return f'A etapa "{trecho}" é a última registrada.'
    return "Essa etapa não foi encontrada no conteúdo."

# ========= PROMPT =========
def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"
    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Sua tarefa é analisar cuidadosamente os documentos fornecidos e responder à pergunta com base neles.\n\n"
        "### Regras de resposta:\n"
        "1. Use SOMENTE as informações dos documentos. Não invente nada.\n"
        "2. Se a resposta não estiver escrita de forma explícita, mas puder ser deduzida a partir dos documentos, apresente a dedução de forma clara.\n"
        f"3. Se realmente não houver nenhuma evidência, diga exatamente:\n{FALLBACK_MSG}\n"
        "4. Estruture a resposta em tópicos ou frases completas, e cite trechos relevantes entre aspas sempre que possível.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )

# ========= FUNÇÃO PRINCIPAL =========
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY, model_id: str = MODEL_ID):
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        # 0) checa pergunta de sequência (rápido e direto no conteúdo bruto)
        blocks_raw, _sig = load_all_blocks_cached(FOLDER_ID)
        seq = responder_etapa_seguinte(pergunta, blocks_raw)
        if seq:
            return seq

        # 1) busca ANN rápida
        candidates = ann_search(pergunta, top_n=TOP_N_ANN)

        # se nada veio do ANN, já retorna a mensagem padrão
        if not candidates:
            return FALLBACK_MSG

        # 2) reranking com scores
        reranked = crossencoder_rerank(pergunta, candidates, top_k=top_k)

        # se o melhor score estiver baixo, consideramos "sem evidência"
        best_score = reranked[0]["score"] if reranked else 0.0
        if best_score < CE_SCORE_THRESHOLD:
            return FALLBACK_MSG

        # 3) prompt e chamada ao modelo SOMENTE quando há evidência suficiente
        blocos_relevantes = [r["block"] for r in reranked]
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Você é um assistente que responde com base somente no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            return f"❌ Erro na API: {resp.status_code} - {resp.text}"

        data = resp.json()
        escolhas = data.get("choices", [])
        if not escolhas or "message" not in escolhas[0]:
            return "⚠️ A resposta da API veio vazia ou incompleta."

        resposta = escolhas[0]["message"]["content"]

        # 4) Anexar link SOMENTE quando não for fallback e houver confiança
        if resposta.strip() != FALLBACK_MSG and best_score >= CE_SCORE_THRESHOLD and blocos_relevantes:
            primeiro = blocos_relevantes[0]
            doc_id = primeiro.get("file_id")
            raw_nome = primeiro.get("pagina", "?")
            doc_nome = sanitize_doc_name(raw_nome)
            if doc_id:
                link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

        return resposta

    except Exception as e:
        return f"❌ Erro interno: {e}"

# ========= CLI de teste =========
if __name__ == "__main__":
    print("\nDigite sua pergunta (ou 'sair'):\n")
    while True:
        q = input("Pergunta: ").strip()
        if q.lower() in ("sair", "exit", "quit"):
            break
        print(responder_pergunta(q))
