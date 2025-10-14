# openai_backend.py — modo ultra (rápido) com JSON/JSONL + índice pré-computado (opcional)

import os
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

# ========= CONFIG BÁSICA =========
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o-mini"

# ========= PERFORMANCE SWITCHES =========
USE_JSONL = True            # usa JSON/JSONL do Drive se existir (mais rápido que DOCX)
USE_CE = False              # desliga CrossEncoder (maior ganho de latência)
TOP_N_ANN = 16              # menos candidatos no estágio 1
TOP_K = 4                   # blocos finais enviados ao LLM
MAX_WORDS_PER_BLOCK = 320   # blocos maiores = menos itens
GROUP_WINDOW = 5            # agrega mais blocos por item
CE_SCORE_THRESHOLD = 0.42   # limiar de confiança
MAX_TOKENS = 280            # resposta mais curta = mais rápida
TEMPERATURE = 0.15
REQUEST_TIMEOUT = 25

# ========= ÍNDICE PRÉ-COMPUTADO (OPCIONAL, VIA DRIVE) =========
# Se esses 3 arquivos aparecerem no mesmo folder do Drive, o app carrega e usa direto (turbo):
PRECOMP_FAISS_NAME = "faiss.index"
PRECOMP_VECTORS_NAME = "vectors.npy"
PRECOMP_BLOCKS_NAME = "blocks.json"
USE_PRECOMPUTED = True      # procura por esses arquivos primeiro

# ========= DRIVE / AUTH =========
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# ========= FALLBACK =========
FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2025-10-14-ultra-02"

# ========= HTTP SESSION =========
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY.strip()}",
    "Content-Type": "application/json"
})


# ========================= UTILS =========================
def sanitize_doc_name(name: str) -> str:
    name = re.sub(r"^(C[oó]pia de|Copy of)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\.(docx?|pdf|txt|jsonl?|JSONL?)$", "", name, flags=re.IGNORECASE)
    return name.strip()


# ========================= CLIENTES CACHEADOS =========================
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


# ========================= DRIVE LIST/DOWNLOAD =========================
def _list_by_mime_query(drive_service, folder_id, mime_query):
    query = f"'{folder_id}' in parents and ({mime_query})"
    fields = "files(id, name, md5Checksum, modifiedTime, mimeType)"
    results = drive_service.files().list(q=query, fields=fields).execute()
    return results.get("files", []) or []

def _list_docx_metadata(drive_service, folder_id):
    return _list_by_mime_query(
        drive_service, folder_id,
        "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    )

def _list_json_metadata(drive_service, folder_id):
    # JSON às vezes vem como text/plain; filtramos pela extensão tbm
    files = _list_by_mime_query(
        drive_service, folder_id,
        "mimeType='application/json' or mimeType='text/plain'"
    )
    return [f for f in files if f.get("name", "").lower().endswith((".jsonl", ".json"))]

def _list_named_files(drive_service, folder_id, wanted_names):
    # Busca arquivos por nome exato dentro da pasta
    fields = "files(id, name, md5Checksum, modifiedTime, mimeType)"
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents",
        fields=fields
    ).execute()
    files = results.get("files", []) or []
    name_map = {f["name"]: f for f in files if f.get("name") in wanted_names}
    return name_map

def _download_bytes(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    return request.execute()

def _download_text(drive_service, file_id) -> str:
    return _download_bytes(drive_service, file_id).decode("utf-8", errors="ignore")


# ========================= PARSE DOCX/JSON =========================
def _split_text_blocks(text, max_words=MAX_WORDS_PER_BLOCK):
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

def _docx_to_blocks(file_bytes, file_name, file_id, max_words=MAX_WORDS_PER_BLOCK):
    from docx import Document as _Docx
    doc = _Docx(io.BytesIO(file_bytes))
    text = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    return [
        {"pagina": file_name, "texto": chunk, "file_id": file_id}
        for chunk in _split_text_blocks(text, max_words=max_words) if chunk.strip()
    ]

def _records_from_json_text(text: str):
    recs = []
    t = text.lstrip()
    if t.startswith("["):
        try:
            data = json.loads(t)
            if isinstance(data, list):
                recs = data
        except Exception:
            pass
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                continue
    return recs

def _json_records_to_blocks(recs, fallback_name: str, file_id: str):
    out = []
    for r in recs:
        pagina = r.get("pagina") or r.get("page") or r.get("doc") or fallback_name
        texto  = r.get("texto")  or r.get("text") or r.get("content") or ""
        fid    = r.get("file_id") or r.get("source_id") or file_id
        if str(texto).strip():
            out.append({"pagina": str(pagina), "texto": str(texto), "file_id": fid})
    return out


# ========================= CACHE DE FONTE (DOCX/JSON) =========================
@st.cache_data(show_spinner=False)
def _list_sources_cached(folder_id: str, _v=CACHE_BUSTER):
    drive = get_drive_client()
    files_json = _list_json_metadata(drive, folder_id) if USE_JSONL else []
    files_docx = _list_docx_metadata(drive, folder_id)
    return {"json": files_json, "docx": files_docx}

def _signature_from_files(files):
    return [
        {k: f.get(k) for k in ("id", "name", "md5Checksum", "modifiedTime")} for f in (files or [])
    ]

def _build_signature_json_docx(files_json, files_docx):
    payload = {
        "json": sorted(_signature_from_files(files_json), key=lambda x: x["id"]) if files_json else [],
        "docx": sorted(_signature_from_files(files_docx), key=lambda x: x["id"]) if files_docx else [],
    }
    return json.dumps(payload, ensure_ascii=False)

@st.cache_data(show_spinner=False)
def _download_and_parse_blocks(signature: str, folder_id: str, _v=CACHE_BUSTER):
    drive = get_drive_client()
    sources = _list_sources_cached(folder_id)
    files_json = sources.get("json", [])
    files_docx = sources.get("docx", [])

    blocks = []
    # 1) Prefere JSON/JSONL
    if USE_JSONL and files_json:
        for f in files_json:
            try:
                recs = _records_from_json_text(_download_text(drive, f["id"]))
                blocks.extend(_json_records_to_blocks(recs, fallback_name=f["name"], file_id=f["id"]))
            except Exception:
                continue
        if blocks:
            return blocks

    # 2) Fallback DOCX
    for f in files_docx:
        try:
            blocks.extend(_docx_to_blocks(_download_bytes(drive, f["id"]), f["name"], f["id"]))
        except Exception:
            continue
    return blocks

def load_all_blocks_cached(folder_id: str):
    src = _list_sources_cached(folder_id)
    signature = _build_signature_json_docx(src.get("json", []), src.get("docx", []))
    blocks = _download_and_parse_blocks(signature, folder_id)
    return blocks, signature


# ========================= AGRUPAMENTO =========================
def agrupar_blocos(blocos, janela=GROUP_WINDOW):
    grouped = []
    for i in range(0, len(blocos), 1):
        group = blocos[i:i+janela]
        if not group:
            continue
        grouped.append({
            "pagina": group[0].get("pagina", "?"),
            "texto": " ".join(b["texto"] for b in group),
            "file_id": group[0].get("file_id")
        })
    return grouped


# ========================= ÍNDICE PRÉ-COMPUTADO (CARREGAR) =========================
def _find_precomputed_files():
    drive = get_drive_client()
    want = {PRECOMP_FAISS_NAME, PRECOMP_VECTORS_NAME, PRECOMP_BLOCKS_NAME}
    name_map = _list_named_files(drive, FOLDER_ID, want)
    if not all(n in name_map for n in want):
        return None
    return {
        "faiss": name_map[PRECOMP_FAISS_NAME]["id"],
        "vectors": name_map[PRECOMP_VECTORS_NAME]["id"],
        "blocks": name_map[PRECOMP_BLOCKS_NAME]["id"],
    }

@st.cache_resource(show_spinner=False)
def _load_precomputed_index(_v=CACHE_BUSTER):
    """
    Carrega FAISS + vectors.npy + blocks.json do Drive se todos existirem.
    Retorna dict compatível com o resto do pipeline.
    """
    if not USE_PRECOMPUTED:
        return None

    ids = _find_precomputed_files()
    if not ids:
        return None

    drive = get_drive_client()
    # Baixa arquivos
    try:
        vectors = np.load(io.BytesIO(_download_bytes(drive, ids["vectors"])))
        blocks_json = json.loads(_download_text(drive, ids["blocks"]))
        # Normaliza blocks_json para [{pagina, texto, file_id}, ...]
        blocks = _json_records_to_blocks(blocks_json, fallback_name="precomp", file_id="precomp")
        # Carrega FAISS
        try:
            import faiss
        except Exception:
            return None
        faiss_index_bytes = _download_bytes(drive, ids["faiss"])
        # Salva em memória temporária e lê com faiss
        tmp_path = "/tmp/faiss.index"
        with open(tmp_path, "wb") as f:
            f.write(faiss_index_bytes)
        index = faiss.read_index(tmp_path)
        return {"blocks": blocks, "emb": vectors, "index": index, "use_faiss": True}
    except Exception:
        return None


# ========================= ÍNDICE (GERAR OU USAR PRONTO) =========================
def try_import_faiss():
    try:
        import faiss
        return faiss
    except Exception:
        return None

@st.cache_resource(show_spinner=False)
def build_vector_index(_v=CACHE_BUSTER):
    # 0) Tenta carregar pré-computado (turbo)
    pre = _load_precomputed_index()
    if pre is not None:
        return pre

    # 1) Caso não exista pré-computado, gera em runtime (cacheado)
    blocks_raw, _sig = load_all_blocks_cached(FOLDER_ID)
    grouped = agrupar_blocos(blocks_raw, janela=GROUP_WINDOW)
    if not grouped:
        return {"blocks": [], "emb": None, "index": None, "use_faiss": False}

    sbert = get_sbert_model()
    texts = [b["texto"] for b in grouped]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, _v2=CACHE_BUSTER):
        return sbert.encode(texts_, convert_to_numpy=True, normalize_embeddings=True)

    emb = _embed_texts_cached(texts)

    faiss = try_import_faiss()
    use_faiss = False
    index = None
    if faiss is not None:
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(emb.astype(np.float32))
        use_faiss = True

    return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}


# ========================= BUSCA ANN =========================
def ann_search(query_text: str, top_n: int):
    vecdb = build_vector_index()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    from numpy.linalg import norm
    sbert = get_sbert_model()
    q = sbert.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    if vecdb["use_faiss"]:
        import faiss
        D, I = vecdb["index"].search(q.reshape(1, -1).astype(np.float32), top_n)
        idxs = I[0].tolist()
        scores = D[0].tolist()
    else:
        emb = vecdb["emb"]
        scores_all = (emb @ q)
        idxs = np.argsort(-scores_all)[:top_n].tolist()
        scores = scores_all[idxs].tolist()

    return [{"idx": i, "score": float(s), "block": blocks[i]} for i, s in zip(idxs, scores) if i >= 0]


# ========================= PROMPT & ATALHOS =========================
def responder_etapa_seguinte(pergunta, blocos_raw):
    q = pergunta.lower()
    if not any(x in q for x in ["após", "depois de", "seguinte a"]):
        return None
    trecho = q
    for token in ["após", "depois de", "seguinte a"]:
        if token in trecho:
            trecho = trecho.split(token, 1)[-1].strip()
    if not trecho:
        return None
    for i, b in enumerate(blocos_raw):
        if trecho in b["texto"].lower():
            if i + 1 < len(blocos_raw):
                prox = blocos_raw[i+1]['texto'].splitlines()[0]
                return f'A etapa após "{trecho}" é "{prox}".'
            return f'A etapa "{trecho}" é a última registrada.'
    return "Essa etapa não foi encontrada no conteúdo."

def montar_prompt_rag(pergunta, blocos):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"
    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Responda SOMENTE com base nos documentos.\n\n"
        "Regras:\n"
        "1) Não invente nada.\n"
        "2) Se puder deduzir, explicite a dedução.\n"
        f"3) Se não houver evidência, diga exatamente:\n{FALLBACK_MSG}\n"
        "4) Estruture em tópicos ou frases completas; cite trechos em MAIÚSCULAS quando útil.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )


# ========================= PRINCIPAL =========================
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY, model_id: str = MODEL_ID):
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        # Atalho barato: sequência de etapa
        blocks_raw, _sig = load_all_blocks_cached(FOLDER_ID)
        seq = responder_etapa_seguinte(pergunta, blocks_raw)
        if seq:
            return seq

        # Busca ANN (rápida)
        candidates = ann_search(pergunta, top_n=TOP_N_ANN)
        if not candidates:
            return FALLBACK_MSG

        # Ordena pelo score ANN e corta já no top_k (sem CE)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        reranked = [{"block": c["block"], "score": c["score"]} for c in candidates[:top_k]]

        best_score = reranked[0]["score"] if reranked else 0.0
        if best_score < CE_SCORE_THRESHOLD:
            return FALLBACK_MSG

        blocos_relevantes = [r["block"] for r in reranked]
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Você responde apenas com base no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "n": 1
        }

        resp = session.post("https://api.openai.com/v1/chat/completions", json=payload, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            return f"❌ Erro na API: {resp.status_code} - {resp.text}"

        data = resp.json()
        choices = data.get("choices", [])
        if not choices or "message" not in choices[0]:
            return "⚠️ A resposta da API veio vazia ou incompleta."

        resposta = choices[0]["message"]["content"]

        # Anexa link do doc mais relevante (não custa caro)
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


# ========================= CLI =========================
if __name__ == "__main__":
    print("\nDigite sua pergunta (ou 'sair'):\n")
    while True:
        q = input("Pergunta: ").strip()
        if q.lower() in ("sair", "exit", "quit"):
            break
        print(responder_pergunta(q))
