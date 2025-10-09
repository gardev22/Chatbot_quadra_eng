import os
import io
import re
import time
import json
import hashlib
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

# Modelos: 4o-mini é ótimo p/ latência
MODEL_ID = "gpt-4o-mini"
TOP_K = 5                   # blocos finais enviados ao LLM
TOP_N_ANN = 60              # (antes: 80) — reduz custo da 1ª busca
MAX_TOKENS = 400            # (antes: 500) — resposta menor = mais rápida
TEMPERATURE = 0.2
REQUEST_TIMEOUT = 40

# Fast path: pula CrossEncoder na 1ª pergunta
FAST_FIRST_QUESTION = True

# Pasta do Google Drive
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# Persistência local (sobrevive ao re-run e acelera cold start)
PERSIST_DIR = "/tmp/quadra_idx"
os.makedirs(PERSIST_DIR, exist_ok=True)

# ========= MENSAGEM PADRÃO E THRESHOLD =========
FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)
CE_SCORE_THRESHOLD = 0.42  # ajuste fino: 0.38~0.48 funciona bem com o MiniLM

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2025-10-09-01"

# ========= HTTP SESSION (reaproveita conexão) =========
@st.cache_resource(show_spinner=False)
def get_http():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {API_KEY.strip()}"})
    return s

# ========= UTILS =========
def sanitize_doc_name(name: str) -> str:
    name = re.sub(r"^(C[oó]pia de|Copy of)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\.(docx?|pdf|txt)$", "", name, flags=re.IGNORECASE)
    return name.strip()

def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

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
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    # Carregado só quando realmente necessário
    import torch
    from sentence_transformers import CrossEncoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)

# ========= LISTAGEM E DOWNLOAD (DRIVE) =========
def _list_docx_metadata(drive_service, folder_id):
    query = (
        f"'{folder_id}' in parents and "
        "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    )
    fields = "files(id, name, md5Checksum, modifiedTime)"
    # página única com bastante itens (reduz round-trips)
    results = drive_service.files().list(q=query, fields=fields, pageSize=1000).execute()
    return results.get("files", [])

def _download_docx_bytes(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    return request.execute()

# ========= PARSE DOCX EM BLOCOS =========
def _split_text_blocks(text, max_words=220):   # ligeiro aumento p/ menos blocos
    words = text.split()
    blocks = []
    for i in range(0, len(words), max_words):
        blocks.append(" ".join(words[i:i + max_words]))
    return blocks

def _docx_to_blocks(file_bytes, file_name, file_id, max_words=220):
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

def _signature_hash(sig: str) -> str:
    return _hash(sig)

@st.cache_data(show_spinner=False)
def _download_and_parse_blocks(signature: str, folder_id: str, _v=CACHE_BUSTER):
    drive = get_drive_client()
    files = _list_docx_metadata(drive, folder_id)
    all_blocks = []
    for f in files:
        bytes_ = _download_docx_bytes(drive, f["id"])
        all_blocks.extend(_docx_to_blocks(bytes_, f["name"], f["id"], max_words=220))
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

# ========= ÍNDICE VETORIAL (com persistência em disco) =========
def try_import_faiss():
    try:
        import faiss  # type: ignore
        return faiss
    except Exception:
        return None

def _persist_paths(sig_hash: str):
    base = os.path.join(PERSIST_DIR, f"idx_{sig_hash}")
    return base + ".json", base + ".npz"

@st.cache_resource(show_spinner=False)
def build_vector_index(_v=CACHE_BUSTER):
    """
    Retorna um dicionário com:
      - blocks (agrupados)
      - emb    (np.ndarray)
      - index  (FAISS ou None)
      - use_faiss (bool)
    Com persistência em disco por assinatura (evita re-embed a cada cold start).
    """
    blocks_raw, sig = load_all_blocks_cached(FOLDER_ID)
    grouped = agrupar_blocos(blocks_raw, janela=3)
    if not grouped:
        return {"blocks": [], "emb": None, "index": None, "use_faiss": False}

    sig_hash = _signature_hash(sig)
    meta_path, npz_path = _persist_paths(sig_hash)

    # 1) tenta carregar do disco
    if os.path.exists(meta_path) and os.path.exists(npz_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                # (mantemos apenas contagem para segurança; os textos vêm de memória)
                meta = json.load(f)
            if meta.get("count", -1) == len(grouped):
                npz = np.load(npz_path)
                emb = npz["emb"]
                faiss = try_import_faiss()
                index = None
                use_faiss = False
                if faiss is not None:
                    dim = emb.shape[1]
                    index = faiss.IndexFlatIP(dim)
                    index.add(emb.astype(np.float32))
                    use_faiss = True
                return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}
        except Exception:
            pass  # se falhar, refaz abaixo

    # 2) calcula embeddings e persiste
    sbert = get_sbert_model()
    texts = [b["texto"] for b in grouped]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, _v2=CACHE_BUSTER):
        return sbert.encode(texts_, convert_to_numpy=True, normalize_embeddings=True)

    emb = _embed_texts_cached(texts)

    # persiste em disco
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"count": len(grouped)}, f)
        np.savez_compressed(npz_path, emb=emb)
    except Exception:
        pass

    # cria índice
    faiss = try_import_faiss()
    index = None
    use_faiss = False
    if faiss is not None:
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(emb.astype(np.float32))
        use_faiss = True

    return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}

def ann_search(query_text: str, top_n: int):
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
        emb = vecdb["emb"]
        scores = (emb @ q)
        idxs = np.argsort(-scores)[:top_n].tolist()
        scores = scores[idxs].tolist()

    candidates = [{"idx": i, "score": s, "block": blocks[i]} for i, s in zip(idxs, scores) if i >= 0]
    return candidates

# ========= RERANKING =========
def crossencoder_rerank(query: str, candidates, top_k: int):
    if not candidates:
        return []
    ce = get_cross_encoder()
    pairs = [(query, c["block"]["texto"]) for c in candidates]
    # batch grande acelera CPU
    scores = ce.predict(pairs, batch_size=128)
    packed = [{"block": c["block"], "score": float(s)} for c, s in zip(candidates, scores)]
    packed.sort(key=lambda x: x["score"], reverse=True)
    return packed[:top_k]

def cosine_rerank(query: str, candidates, top_k: int):
    # fallback baratíssimo para a 1ª pergunta
    if not candidates:
        return []
    sbert = get_sbert_model()
    qv = sbert.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0]
    scored = []
    for c in candidates:
        txt = c["block"]["texto"]
        # reusa vetor do ANN? simples e rápido: re-score por length penalty leve
        s = float(c["score"])
        # pequena normalização por tamanho ajuda (evitar blocos gigantes dominarem)
        penalty = 1.0 - min(len(txt) / 2000.0, 0.15)
        scored.append({"block": c["block"], "score": s * penalty})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

# ========= DETECÇÃO DE ETAPA SEGUINTE =========
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
        "Responda SOMENTE com base nos documentos fornecidos.\n\n"
        "Regras:\n"
        "1) Não invente nada.\n"
        "2) Se deduzir, explique a dedução claramente (atenção a sinônimos).\n"
        f"3) Se não houver evidência, diga exatamente:\n{FALLBACK_MSG}\n"
        "4) Estruture a resposta em tópicos ou frases completas e cite trechos relevantes EM MAIÚSCULO quando útil.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )

# ========= PRINCIPAL =========
@st.cache_data(show_spinner=False)
def _get_blocks_raw_cached(_v=CACHE_BUSTER):
    return load_all_blocks_cached(FOLDER_ID)

def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY, model_id: str = MODEL_ID):
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        # 0) checa pergunta de sequência (rápido, zero modelos)
        blocks_raw, _sig = _get_blocks_raw_cached()
        seq = responder_etapa_seguinte(pergunta, blocks_raw)
        if seq:
            return seq

        # 1) busca ANN rápida
        candidates = ann_search(pergunta, top_n=TOP_N_ANN)
        if not candidates:
            return FALLBACK_MSG

        # 2) escolher reranker
        asked_once = st.session_state.get("_asked_once", False)
        if FAST_FIRST_QUESTION and not asked_once:
            reranked = cosine_rerank(pergunta, candidates, top_k=top_k)   # ultra rápido
        else:
            reranked = crossencoder_rerank(pergunta, candidates, top_k=top_k)

        best_score = reranked[0]["score"] if reranked else 0.0
        # quando for fast path, usamos um limiar um pouco mais permissivo
        min_thresh = CE_SCORE_THRESHOLD if (asked_once or not FAST_FIRST_QUESTION) else (CE_SCORE_THRESHOLD - 0.05)
        if best_score < min_thresh:
            st.session_state["_asked_once"] = True  # marca mesmo assim
            return FALLBACK_MSG

        blocos_relevantes = [r["block"] for r in reranked]
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        # 3) chamada ao LLM
        http = get_http()
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Você é um assistente que responde com base somente no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE
        }
        resp = http.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            return f"❌ Erro na API: {resp.status_code} - {resp.text}"

        data = resp.json()
        escolhas = data.get("choices", [])
        if not escolhas or "message" not in escolhas[0]:
            return "⚠️ A resposta da API veio vazia ou incompleta."

        resposta = escolhas[0]["message"]["content"]

        # 4) Anexar link quando houve evidência
        if resposta.strip() != FALLBACK_MSG and blocos_relevantes:
            primeiro = blocos_relevantes[0]
            doc_id = primeiro.get("file_id")
            raw_nome = primeiro.get("pagina", "?")
            doc_nome = sanitize_doc_name(raw_nome)
            if doc_id:
                link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

        # marca que já passamos pela 1ª pergunta
        st.session_state["_asked_once"] = True
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
