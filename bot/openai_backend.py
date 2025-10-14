# openai_backend.py — anti-fallback + anti-truncamento (ajustes mínimos)

import os
import io
import re
import json
import unicodedata
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

# ========= PERFORMANCE & QUALIDADE =========
USE_JSONL = True               # prefere JSON/JSONL do Drive (rápido)
USE_CE = True                  # CE ligado, mas com pulo inteligente
SKIP_CE_IF_ANN_BEST = 0.60     # se ANN >= 0.60, não roda CE
TOP_N_ANN = 64                 # mais recall
TOP_K = 4                      # contexto base enviado ao LLM
MAX_WORDS_PER_BLOCK = 220
GROUP_WINDOW = 3
# Limiar quando CE é usado vs quando só ANN é usado
CE_SCORE_THRESHOLD = 0.38
ANN_SCORE_THRESHOLD = 0.18
# Anti-truncamento
MAX_TOKENS = 700               # ↑ aumenta espaço pra resposta
REQUEST_TIMEOUT = 40           # ↑ evita corte por timeout
TEMPERATURE = 0.15

# ========= ÍNDICE PRÉ-COMPUTADO (opcional) =========
PRECOMP_FAISS_NAME = "faiss.index"
PRECOMP_VECTORS_NAME = "vectors.npy"
PRECOMP_BLOCKS_NAME = "blocks.json"
USE_PRECOMPUTED = True

# ========= DRIVE / AUTH =========
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# ========= FALLBACK =========
FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2025-10-14-robusto-02"

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

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _tokenize(s: str):
    s = _strip_accents((s or "").lower())
    return re.findall(r"[a-zA-Z0-9_]{3,}", s)

def _has_lexical_evidence(query: str, texts: list[str]) -> bool:
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return False
    for t in texts:
        t_tokens = set(_tokenize(t or ""))
        if q_tokens & t_tokens:
            return True
    return False

def _is_fallback_output(text: str) -> bool:
    """Detecta fallback mesmo com espaços/variações mínimas."""
    if not text:
        return False
    norm = "\n".join([line.strip() for line in text.strip().splitlines() if line.strip()])
    norm = _strip_accents(norm.lower())
    fallback_norm = _strip_accents(FALLBACK_MSG.lower())
    first_line = _strip_accents(FALLBACK_MSG.splitlines()[0].lower())
    return (fallback_norm in norm) or norm.startswith(first_line)

# >>> NOVO: detecta respostas do tipo "não há informações..." para forçar o FALLBACK
_NOINFO_RE = re.compile(
    r"(não\s+há\s+informa|não\s+encontrei|não\s+foi\s+possível\s+encontrar|sem\s+informações|não\s+consta|não\s+existe)",
    re.IGNORECASE
)

def _looks_like_noinfo(text: str) -> bool:
    return bool(text and _NOINFO_RE.search(text))

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

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    if not USE_CE:
        return None
    import torch
    from sentence_transformers import CrossEncoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)

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
    files = _list_by_mime_query(
        drive_service, folder_id,
        "mimeType='application/json' or mimeType='text/plain'"
    )
    return [f for f in files if f.get("name", "").lower().endswith((".jsonl", ".json"))]

def _list_named_files(drive_service, folder_id, wanted_names):
    fields = "files(id, name, md5Checksum, modifiedTime, mimeType)"
    results = drive_service.files().list(q=f"'{folder_id}' in parents", fields=fields).execute()
    files = results.get("files", []) or []
    return {f["name"]: f for f in files if f.get("name") in wanted_names}

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
    return [{k: f.get(k) for k in ("id", "name", "md5Checksum", "modifiedTime")} for f in (files or [])]

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
    if USE_JSONL and files_json:
        for f in files_json:
            try:
                recs = _records_from_json_text(_download_text(drive, f["id"]))
                blocks.extend(_json_records_to_blocks(recs, fallback_name=f["name"], file_id=f["id"]))
            except Exception:
                continue
        if blocks:
            return blocks

    # Fallback DOCX
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

# ========================= ÍNDICE PRÉ-COMPUTADO =========================
def _list_named_files_map():
    drive = get_drive_client()
    want = {PRECOMP_FAISS_NAME, PRECOMP_VECTORS_NAME, PRECOMP_BLOCKS_NAME}
    name_map = _list_named_files(drive, FOLDER_ID, want)
    return name_map if all(n in name_map for n in want) else None

@st.cache_resource(show_spinner=False)
def _load_precomputed_index(_v=CACHE_BUSTER):
    if not USE_PRECOMPUTED:
        return None
    ids_map = _list_named_files_map()
    if not ids_map:
        return None
    drive = get_drive_client()
    try:
        vectors = np.load(io.BytesIO(_download_bytes(drive, ids_map[PRECOMP_VECTORS_NAME]["id"])))
        blocks_json = json.loads(_download_text(drive, ids_map[PRECOMP_BLOCKS_NAME]["id"]))
        blocks = _json_records_to_blocks(blocks_json, fallback_name="precomp", file_id="precomp")
        try:
            import faiss
        except Exception:
            return None
        faiss_index_bytes = _download_bytes(drive, ids_map[PRECOMP_FAISS_NAME]["id"])
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
    pre = _load_precomputed_index()
    if pre is not None:
        return pre

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
        scores = [float(scores_all[i]) for i in idxs]

    return [{"idx": i, "score": float(s), "block": blocks[i]} for i, s in zip(idxs, scores) if i >= 0]

# ========================= RERANKING (CE OPCIONAL) =========================
def crossencoder_rerank(query: str, candidates, top_k: int):
    if not candidates:
        return []
    ce = get_cross_encoder()
    if ce is None:
        packed = [{"block": c["block"], "score": float(c["score"])} for c in candidates]
        packed.sort(key=lambda x: x["score"], reverse=True)
        return packed[:top_k]
    pairs = [(query, c["block"]["texto"]) for c in candidates]
    scores = ce.predict(pairs, batch_size=96)
    packed = [{"block": c["block"], "score": float(s)} for c, s in zip(candidates, scores)]
    packed.sort(key=lambda x: x["score"], reverse=True)
    return packed[:top_k]

# ========================= ATALHO DE ETAPA & PROMPT =========================
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

def montar_prompt_rag(pergunta, blocos, reforco_no_fallback=False):
    contexto = ""
    for b in blocos:
        contexto += f"[Documento {b.get('pagina', '?')}]:\n{b['texto']}\n\n"
    # (mantém seu prompt exatamente)
    return (
        "Você é um assistente especializado em Procedimentos Operacionais.\n"
        "Sua tarefa é analisar cuidadosamente os documentos fornecidos e responder à pergunta com base neles.\n\n"
        "### Regras de resposta:\n"
        "1. Use SOMENTE as informações dos documentos. Não invente nada.\n"
        "2. Se a resposta não estiver escrita de forma explícita, mas puder ser deduzida a partir dos documentos, apresente a dedução de forma clara. Se atente a sinônimos para não dizer que não há resposta de forma equivocada\n"
        f"3. Se realmente não houver nenhuma evidência, diga exatamente:\n{FALLBACK_MSG}\n"
        "4. Estruture a resposta em tópicos ou frases completas, e cite trechos relevantes totalmente em maiúsculo  sempre que possível.\n\n"
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

        # Busca ANN
        candidates = ann_search(pergunta, top_n=TOP_N_ANN)
        if not candidates:
            return FALLBACK_MSG

        # Ordena pelo score ANN
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best_ann = candidates[0]["score"]

        # Decide CE com pulo inteligente
        run_ce = USE_CE and (best_ann < SKIP_CE_IF_ANN_BEST)

        if run_ce:
            subset = candidates[:24]
            reranked = crossencoder_rerank(pergunta, subset, top_k=top_k)
            best_score = reranked[0]["score"] if reranked else 0.0
            pass_threshold = (best_score >= CE_SCORE_THRESHOLD)
            top_texts = [r["block"]["texto"] for r in reranked]
        else:
            reranked = [{"block": c["block"], "score": c["score"]} for c in candidates[:top_k]]
            best_score = reranked[0]["score"] if reranked else 0.0
            pass_threshold = (best_score >= ANN_SCORE_THRESHOLD)
            top_texts = [c["block"]["texto"] for c in candidates[:top_k]]

        # >>> AJUSTE MINÍMO: evidência só se houver sobreposição lexical (sem a regra de ≤3 tokens)
        evidence_ok = _has_lexical_evidence(pergunta, top_texts)

        # Permite responder com score baixo apenas se houver evidência lexical real
        if not pass_threshold and evidence_ok:
            pass_threshold = True

        # Sem evidência/score: FALLBACK imediato
        if not pass_threshold:
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

        resposta = choices[0]["message"]["content"].strip()

        # =============== Guardas finais ===============
        # Se o modelo disser "não há informações..." => força FALLBACK oficial
        if _looks_like_noinfo(resposta):
            return FALLBACK_MSG

        # Detecta seu fallback explícito (compara textos)
        is_fb = _is_fallback_output(resposta)
        if is_fb:
            return FALLBACK_MSG

        # Anexa link só se NÃO for fallback
        if blocos_relevantes:
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
