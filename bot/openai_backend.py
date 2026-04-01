# openai_backend.py — RAG conversacional v7 (todas as correções aplicadas)
# Correções: embedding multilíngue, título no chunk, cross-encoder PT,
#            query expansion leve, dedup de resultados, prompt enxuto

import os
import io
import re
import json
import time
import unicodedata
from typing import Optional

import numpy as np
import requests
import streamlit as st
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ========= CONFIG BÁSICA =========
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o"

# ========= PERFORMANCE & QUALIDADE =========
USE_JSONL = True
USE_CE = True  # ← LIGADO: cross-encoder para reranking

TOP_N_ANN = 15       # candidatos iniciais (aumentado para dar margem à dedup)
TOP_K = 5            # blocos finais enviados ao LLM
DEDUP_MAX_OVERLAP = 0.70  # limiar de deduplicação

MAX_WORDS_PER_BLOCK = 180
GROUP_WINDOW = 2

MAX_TOKENS = 750
REQUEST_TIMEOUT = 60
TEMPERATURE = 0.30

HISTORY_TURNS = 3

# ========= EMBEDDING MODEL =========
# intfloat/multilingual-e5-base: melhor modelo multilíngue custo/benefício
# Requer prefixo "query: " para queries e "passage: " para documentos
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
EMBED_QUERY_PREFIX = "query: "
EMBED_PASSAGE_PREFIX = "passage: "

# ========= CROSS-ENCODER =========
# Modelo de reranking treinado em português (mMARCO)
CE_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# ========= ÍNDICE PRÉ-COMPUTADO (opcional) =========
PRECOMP_FAISS_NAME = "faiss.index"
PRECOMP_VECTORS_NAME = "vectors.npy"
PRECOMP_BLOCKS_NAME = "blocks.json"
USE_PRECOMPUTED = False

# ========= DRIVE / AUTH =========
FOLDER_ID = "1fdcVl6RcoyaCpa6PmOX1kUAhXn5YIPTa"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# ========= FALLBACK =========
FALLBACK_MSG = (
    "⚠️ Este agente é exclusivo para consulta de Procedimento Operacional Padrão - POP Quadra. ⚠️\n"
    "Departamento de Estratégia & Inovação."
)

# ========= SYSTEM PROMPT (enxuto e assertivo) =========
SYSTEM_PROMPT_RAG = """Você é o QD Bot, assistente interno da Quadra Engenharia. Fale sempre em português do Brasil.

REGRAS INVIOLÁVEIS:
1. Responda APENAS com base nos trechos de documentos fornecidos. Nunca invente informações, etapas, prazos, formulários ou responsáveis que não estejam nos trechos.
2. Se os trechos não cobrem a pergunta, diga: "Os documentos disponíveis não detalham esse ponto específico. Recomendo consultar o setor responsável."
3. Sempre identifique o documento fonte (ex: "Conforme o PO.08 - Controle de Pessoal R.02..." ou "De acordo com o documento Contratos e Medições R.02...").
4. Use SOMENTE os trechos do documento mais relevante para o assunto perguntado. Não misture informações de documentos diferentes.
5. Se a pergunta foge de procedimentos internos, responda: "Meu foco é ajudar com procedimentos operacionais padrão (POPs), políticas e rotinas internas da Quadra Engenharia."

ESTILO:
- Respostas detalhadas e estruturadas como manual interno.
- Descreva etapas, responsáveis, formulários e prazos quando presentes nos trechos.
- Finalize com "Em resumo," reforçando o que o colaborador deve fazer."""

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2026-04-01-v7-multilingual-e5"

# ========= HTTP SESSION =========
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY.strip()}",
    "Content-Type": "application/json"
})

# ========================= STATE =========================
_FALLBACK_STATE = {}

def _state_get(key, default=None):
    try:
        return st.session_state.get(key, default)
    except Exception:
        return _FALLBACK_STATE.get(key, default)

def _state_set(key, value):
    try:
        st.session_state[key] = value
    except Exception:
        _FALLBACK_STATE[key] = value

def _state_pop(key, default=None):
    try:
        return st.session_state.pop(key, default)
    except Exception:
        return _FALLBACK_STATE.pop(key, default)

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

def _lexical_overlap(query: str, text: str) -> float:
    q_tokens = set(_tokenize(query))
    t_tokens = set(_tokenize(text))
    if not q_tokens or not t_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)

def _overlap_score(a: str, b: str) -> float:
    ta = set(_tokenize(a))
    tb = set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1.0, len(ta))

def _escolher_bloco_para_link(pergunta: str, resposta: str, blocos: list[dict]):
    if not blocos:
        return None
    melhor = None
    melhor_score = 0.0
    for b in blocos:
        txt = b.get("texto") or ""
        if not txt.strip():
            continue
        s_resp = _overlap_score(resposta or "", txt)
        s_perg = _overlap_score(pergunta or "", txt)
        score = s_resp + 0.5 * s_perg
        if score > melhor_score:
            melhor_score = score
            melhor = b
    if melhor is None or melhor_score < 0.02:
        return None
    return melhor

def _is_off_domain_reply(text: str) -> bool:
    if not text:
        return False
    t = _strip_accents(text.lower())
    gatilho = _strip_accents(
        "Meu foco é ajudar com procedimentos operacionais padrão (POPs), políticas e rotinas internas da Quadra Engenharia."
    ).lower()
    return gatilho[:60] in t

# ========================= ROTAS PESSOAS/RH: OBRA x ADMIN =========================
HR_TIPO_OBRA = "obra"
HR_TIPO_ADMIN = "administrativo"

def _is_people_process_question(q: str) -> bool:
    t = _strip_accents((q or "").lower())
    termos = [
        "colaborador", "colaboradores", "funcionario", "funcionarios",
        "empregado", "empregados", "clt",
        "contrat", "admiss", "admit", "recrut", "sele", "vaga", "curriculo", "entrevista",
        "aso", "documentos admissionais", "documentacao admissional",
        "experiencia", "periodo de experiencia", "contrato de experiencia",
        "avaliacao", "desempenho", "feedback", "pdi", "metas", "performance",
        "deslig", "demiss", "rescis", "aviso previo", "termino de contrato",
        "ferias", "ponto", "banco de horas", "folha", "holerite", "salario",
        "atestado", "afastamento", "beneficio", "beneficios", "vr", "vt",
        "vale transporte", "vale refeicao",
        "epi", "epis", "uniforme",
        "departamento pessoal", "pessoas e performance", "pessoas & performance",
        "po.06", "po 06", "po.08", "po 08",
    ]
    if re.search(r"\bdp\b", t) or re.search(r"\bpp\b", t) or re.search(r"\brh\b", t):
        return True
    return any(x in t for x in termos)

def _parse_tipo_contratacao(texto: str) -> Optional[str]:
    t_raw = (texto or "").strip()
    t = _strip_accents(t_raw.lower())

    if re.fullmatch(r"\s*1\s*", t_raw):
        return HR_TIPO_OBRA
    if re.fullmatch(r"\s*2\s*", t_raw):
        return HR_TIPO_ADMIN

    if "pessoas e performance" in t or "pessoas & performance" in t or "po.06" in t or "po 06" in t or re.search(r"\bpp\b", t):
        return HR_TIPO_ADMIN
    if "departamento pessoal" in t or "po.08" in t or "po 08" in t or re.search(r"\bdp\b", t):
        return HR_TIPO_OBRA

    sinais_obra = ["obra", "canteiro", "campo", "frente de obra", "producao", "produção", "apoio de obra", "alojamento"]
    sinais_admin = ["administrativo", "escritorio", "escritório", "sede", "corporativo", "matriz"]

    has_obra = any(s in t for s in sinais_obra)
    has_admin = any(s in t for s in sinais_admin)

    if has_obra and not has_admin:
        return HR_TIPO_OBRA
    if has_admin and not has_obra:
        return HR_TIPO_ADMIN
    return None

def _tipo_boost(block: dict, tipo: str) -> float:
    if not tipo or not block:
        return 0.0
    pagina = _strip_accents((block.get("pagina") or "")).lower()
    texto = _strip_accents((block.get("texto") or "")).lower()
    hay = f"{pagina}\n{texto}"

    if tipo == HR_TIPO_OBRA:
        chaves = ["po.08", "po 08", "controle de pessoal", "departamento pessoal", " dp ", "r.02", "r 02"]
        return 0.20 if any(k in hay for k in chaves) else 0.0
    if tipo == HR_TIPO_ADMIN:
        chaves = ["po.06", "po 06", "pessoas e performance", "pessoas & performance", "recrutamento", "selecao", "seleção"]
        return 0.20 if any(k in hay for k in chaves) else 0.0
    return 0.0

# ========================= QUERY EXPANSION (LEVE) =========================
def _expand_query_for_hr(query: str, tipo_contratacao: Optional[str] = None) -> str:
    """Expansão LEVE para embedding — poucos termos de alto sinal.
    Expansão pesada vai no prompt, não no vetor."""
    q_norm = _strip_accents(query.lower())
    extras = []

    # Contratos/medições
    sinais_contrato = ["aditivo", "medicao", "medição", "boletim", "fornecedor",
                       "terceirizado", "clausula", "cláusula", "contratual"]
    eh_contrato = any(x in q_norm for x in sinais_contrato)

    if eh_contrato:
        extras.append("contratos medições aditivo contratual")
    elif _is_people_process_question(query):
        extras.append("procedimento pessoal rotina interna")
        if tipo_contratacao == HR_TIPO_OBRA:
            extras.append("obra departamento pessoal PO.08")
        elif tipo_contratacao == HR_TIPO_ADMIN:
            extras.append("administrativo pessoas performance PO.06")

    if "experiên" in q_norm or "experien" in q_norm:
        if not eh_contrato:
            extras.append("periodo experiencia avaliacao desempenho")

    if "deslig" in q_norm or "demiss" in q_norm or "rescis" in q_norm:
        extras.append("desligamento rescisão aviso prévio")

    if "toner" in q_norm:
        extras.append("material expediente cartucho impressora compras")

    if "gestao de terceirizados" in q_norm or "gestão de terceirizados" in q_norm:
        extras.append("gestão terceirizados avaliação portaria controle")

    if extras:
        return query + " " + " ".join(extras)
    return query

# ========================= FALLBACK INTERATIVO =========================
def gerar_resposta_fallback_interativa(pergunta: str,
                                       api_key: str = API_KEY,
                                       model_id: str = MODEL_ID) -> str:
    try:
        prompt_usuario = (
            "O usuário fez a pergunta abaixo, mas não encontramos nenhum conteúdo correspondente "
            "nos documentos internos ou POPs da Quadra Engenharia.\n\n"
            "Sua tarefa:\n"
            "1. Cumprimente o usuário de forma cordial.\n"
            "2. Explique que você é um assistente treinado com documentos internos "
            "   e que não localizou nada específico sobre essa pergunta.\n"
            "3. Sugira que ele reformule focando em processos, POPs ou rotinas da Quadra.\n"
            "4. Tom profissional mas amigável, português do Brasil.\n\n"
            f"Pergunta do usuário:\n\"{pergunta}\""
        )
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente virtual da Quadra Engenharia. "
                        "Responda sempre em português do Brasil, de forma clara, educada e objetiva."
                    ),
                },
                {"role": "user", "content": prompt_usuario},
            ],
            "max_tokens": 320,
            "temperature": 0.35,
            "n": 1,
            "stream": False,
        }
        resp = session.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        texto = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not texto or not texto.strip():
            return FALLBACK_MSG
        return texto.strip()
    except Exception:
        return FALLBACK_MSG

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
    return SentenceTransformer(EMBED_MODEL_NAME)

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    if not USE_CE:
        return None
    from sentence_transformers import CrossEncoder
    return CrossEncoder(CE_MODEL_NAME, max_length=512)

# ========================= DRIVE LIST/DOWNLOAD =========================
def _drive_list_all(drive_service, query: str, fields: str):
    all_files = []
    page_token = None
    while True:
        resp = drive_service.files().list(
            q=query,
            fields=f"nextPageToken,{fields}",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            corpora="allDrives"
        ).execute()
        items = resp.get("files", []) or []
        all_files.extend(items)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return all_files

def _list_by_mime_query(drive_service, folder_id, mime_query):
    query = f"'{folder_id}' in parents and ({mime_query}) and trashed = false"
    fields = "files(id, name, md5Checksum, modifiedTime, mimeType)"
    return _drive_list_all(drive_service, query, fields)

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
    IGNORED = {"blocks_cache.json"}
    return [
        f for f in files
        if f.get("name", "").lower().endswith((".jsonl", ".json"))
        and f.get("name", "") not in IGNORED
    ]

def _list_named_files(drive_service, folder_id, wanted_names):
    fields = "files(id, name, md5Checksum, modifiedTime, mimeType)"
    query = f"'{folder_id}' in parents and trashed = false"
    files = _drive_list_all(drive_service, query, fields)
    return {f["name"]: f for f in files if f.get("name") in wanted_names}

def _download_bytes(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
    return request.execute()

def _download_text(drive_service, file_id) -> str:
    return _download_bytes(drive_service, file_id).decode("utf-8", errors="ignore")

# ========================= PARSE DOCX/JSON =========================
def _split_text_blocks(text, max_words=MAX_WORDS_PER_BLOCK):
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

def _docx_to_blocks(file_bytes, file_name, file_id, max_words=MAX_WORDS_PER_BLOCK):
    doc = Document(io.BytesIO(file_bytes))
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
        texto = r.get("texto") or r.get("text") or r.get("content") or ""
        fid = r.get("file_id") or r.get("source_id") or file_id
        if str(texto).strip():
            out.append({"pagina": str(pagina), "texto": str(texto), "file_id": fid})
    return out

# ========================= TEXTO PARA EMBEDDING =========================
def _texto_para_embedding(block: dict) -> str:
    """Prefixa o nome do documento no texto para dar contexto ao embedding.
    Isso permite que o modelo saiba DE QUAL documento o trecho veio."""
    pagina = sanitize_doc_name(block.get("pagina", ""))
    texto = block.get("texto", "")
    if pagina:
        return f"{pagina}. {texto}"
    return texto

# ========================= CACHE DE FONTES =========================
@st.cache_data(show_spinner=False, ttl=600)
def _list_sources_cached(folder_id: str, _v=CACHE_BUSTER):
    drive = get_drive_client()
    files_json = _list_json_metadata(drive, folder_id) if USE_JSONL else []
    files_docx = _list_docx_metadata(drive, folder_id)
    return {"json": files_json, "docx": files_docx}

def _signature_from_files(files):
    return [{k: f.get(k) for k in ("id", "name", "md5Checksum", "modifiedTime")} for f in (files or [])]

def _build_signature_sources(files_json, files_docx):
    payload = {
        "json": sorted(_signature_from_files(files_json), key=lambda x: x["id"]) if files_json else [],
        "docx": sorted(_signature_from_files(files_docx), key=lambda x: x["id"]) if files_docx else [],
    }
    return json.dumps(payload, ensure_ascii=False)

@st.cache_data(show_spinner=False)
def _parse_docx_cached(file_id: str, md5: str, name: str):
    drive = get_drive_client()
    return _docx_to_blocks(_download_bytes(drive, file_id), name, file_id)

@st.cache_data(show_spinner=False)
def _parse_json_cached(file_id: str, md5: str, name: str):
    drive = get_drive_client()
    recs = _records_from_json_text(_download_text(drive, file_id))
    return _json_records_to_blocks(recs, fallback_name=name, file_id=file_id)

@st.cache_data(show_spinner=False, ttl=600)
def _download_and_parse_blocks(signature: str, folder_id: str, _v=CACHE_BUSTER):
    sources = _list_sources_cached(folder_id)
    files_json = sources.get("json", []) if USE_JSONL else []
    files_docx = sources.get("docx", []) or []

    blocks = []
    for f in files_json:
        try:
            md5 = f.get("md5Checksum", f.get("modifiedTime", ""))
            blocks.extend(_parse_json_cached(f["id"], md5, f["name"]))
        except Exception:
            continue
    for f in files_docx:
        try:
            md5 = f.get("md5Checksum", f.get("modifiedTime", ""))
            blocks.extend(_parse_docx_cached(f["id"], md5, f["name"]))
        except Exception:
            continue
    return blocks

def load_all_blocks_cached(folder_id: str):
    src = _list_sources_cached(folder_id)
    signature = _build_signature_sources(
        src.get("json", []),
        src.get("docx", []),
    )
    blocks = _download_and_parse_blocks(signature, folder_id)
    return blocks, signature

# ========================= AGRUPAMENTO =========================
def agrupar_blocos(blocos, janela=GROUP_WINDOW):
    grouped = []
    n = len(blocos)
    if n == 0:
        return grouped

    for i in range(n):
        base = blocos[i]
        current_file_id = base.get("file_id")
        group = [base]

        for offset in range(1, janela):
            j = i + offset
            if j >= n:
                break
            b_next = blocos[j]
            if b_next.get("file_id") != current_file_id:
                break
            group.append(b_next)

        grouped.append({
            "pagina": group[0].get("pagina", "?"),
            "texto": " ".join(b["texto"] for b in group),
            "file_id": current_file_id,
        })

    return grouped

# ========================= DEDUPLICAÇÃO DE RESULTADOS =========================
def _deduplicate_results(results: list, max_overlap: float = DEDUP_MAX_OVERLAP) -> list:
    """Remove resultados cujo texto é muito similar a um já selecionado.
    Garante diversidade de documentos nos top-K."""
    if not results:
        return results
    selected = [results[0]]
    for r in results[1:]:
        txt = r["block"].get("texto", "")
        is_dup = False
        for s in selected:
            s_txt = s["block"].get("texto", "")
            # Checa overlap nos dois sentidos
            o1 = _overlap_score(txt, s_txt)
            o2 = _overlap_score(s_txt, txt)
            if max(o1, o2) > max_overlap:
                is_dup = True
                break
        if not is_dup:
            selected.append(r)
    return selected

# ========================= ÍNDICE / EMBEDDINGS =========================
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
        import faiss
        faiss_index_bytes = _download_bytes(drive, ids_map[PRECOMP_FAISS_NAME]["id"])
        tmp_path = "/tmp/faiss.index"
        with open(tmp_path, "wb") as f:
            f.write(faiss_index_bytes)
        index = faiss.read_index(tmp_path)
        return {"blocks": blocks, "emb": vectors, "index": index, "use_faiss": True}
    except Exception:
        return None

def try_import_faiss():
    try:
        import faiss
        return faiss
    except Exception:
        return None

@st.cache_resource(show_spinner=False)
def build_vector_index(signature: str, _v=CACHE_BUSTER):
    pre = _load_precomputed_index()
    if pre is not None:
        return pre

    blocks_raw, _sig = load_all_blocks_cached(FOLDER_ID)
    grouped = agrupar_blocos(blocks_raw, janela=GROUP_WINDOW)
    if not grouped:
        return {"blocks": [], "emb": None, "index": None, "use_faiss": False}

    sbert = get_sbert_model()

    # ── CORREÇÃO: título do doc prefixado + prefixo "passage: " para e5 ──
    texts = [
        f"{EMBED_PASSAGE_PREFIX}{_texto_para_embedding(b)}"
        for b in grouped
    ]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, sig: str, _v2=CACHE_BUSTER):
        return sbert.encode(texts_, convert_to_numpy=True, normalize_embeddings=True,
                            show_progress_bar=False, batch_size=64)

    emb = _embed_texts_cached(texts, signature)

    faiss = try_import_faiss()
    use_faiss = False
    index = None
    if faiss is not None:
        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(emb.astype(np.float32))
        use_faiss = True

    return {"blocks": grouped, "emb": emb, "index": index, "use_faiss": use_faiss}

def get_vector_index():
    _blocks, signature = load_all_blocks_cached(FOLDER_ID)
    return build_vector_index(signature)

# ========================= BUSCA ANN + RERANKING =========================
def ann_search(query_text: str, top_n: int, tipo_contratacao: Optional[str] = None):
    vecdb = get_vector_index()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    sbert = get_sbert_model()

    # ── Query com expansion leve + prefixo "query: " para e5 ──
    query_expanded = _expand_query_for_hr(query_text, tipo_contratacao=tipo_contratacao)
    query_for_embed = f"{EMBED_QUERY_PREFIX}{query_expanded}"
    q = sbert.encode([query_for_embed], convert_to_numpy=True, normalize_embeddings=True)[0]

    if vecdb["use_faiss"]:
        D, I = vecdb["index"].search(q.reshape(1, -1).astype(np.float32), top_n)
        idxs = I[0].tolist()
        scores = D[0].tolist()
    else:
        emb = vecdb["emb"]
        scores_all = (emb @ q)
        idxs = np.argsort(-scores_all)[:top_n].tolist()
        scores = [float(scores_all[i]) for i in idxs]

    results = []
    for i, s in zip(idxs, scores):
        if i < 0:
            continue
        block = blocks[i]
        lex = _lexical_overlap(query_text, block.get("texto", ""))
        pagina_lex = _lexical_overlap(query_text, block.get("pagina", ""))
        b_tipo = _tipo_boost(block, tipo_contratacao) if tipo_contratacao else 0.0
        adj_score = float(s) + 0.20 * lex + 0.25 * pagina_lex + b_tipo
        results.append({"idx": i, "score": adj_score, "block": block})

    results.sort(key=lambda x: x["score"], reverse=True)

    # ── CROSS-ENCODER RERANKING (stage 2) ──
    ce = get_cross_encoder()
    if ce is not None and results:
        pairs = [(query_text, r["block"].get("texto", "")) for r in results]
        ce_scores = ce.predict(pairs, show_progress_bar=False)
        # Normalizar ce_scores para [0, 1] para combinar com embedding score
        ce_min = float(min(ce_scores))
        ce_max = float(max(ce_scores))
        ce_range = ce_max - ce_min if ce_max > ce_min else 1.0
        for r, ce_s in zip(results, ce_scores):
            ce_norm = (float(ce_s) - ce_min) / ce_range
            # 45% embedding/lexical + 55% cross-encoder
            r["score"] = 0.45 * r["score"] + 0.55 * ce_norm
        results.sort(key=lambda x: x["score"], reverse=True)

    # ── DEDUPLICAÇÃO ──
    results = _deduplicate_results(results)

    return results[:top_n]

# ========================= PROMPT RAG =========================
def montar_prompt_rag(pergunta, blocos, tipo_contratacao: Optional[str] = None):
    if not blocos:
        return (
            "Nenhum trecho de POP relevante foi encontrado para a pergunta abaixo.\n"
            "Explique educadamente que não há informação disponível nos documentos internos "
            "e convide o usuário a reformular com foco em processos, políticas ou rotinas da Quadra.\n\n"
            f"Pergunta do colaborador: {pergunta}"
        )

    contexto_parts = []
    for i, b in enumerate(blocos, start=1):
        texto = (b.get("texto") or "")[:3000]
        pagina = b.get("pagina", "?")
        contexto_parts.append(f"[Trecho {i} – {pagina}]\n{texto}")

    contexto_str = "\n\n".join(contexto_parts)

    tipo_txt = ""
    if tipo_contratacao == HR_TIPO_OBRA:
        tipo_txt = "\nContexto informado pelo usuário: processo de OBRA (Departamento Pessoal – PO.08)."
    elif tipo_contratacao == HR_TIPO_ADMIN:
        tipo_txt = "\nContexto informado pelo usuário: processo ADMINISTRATIVO (Pessoas & Performance – PO.06)."

    return (
        f"TRECHOS DOS DOCUMENTOS INTERNOS DA QUADRA ENGENHARIA:\n\n"
        f"{contexto_str}\n"
        f"{tipo_txt}\n\n"
        f"PERGUNTA DO COLABORADOR: {pergunta}\n\n"
        "INSTRUÇÕES:\n"
        "- Responda com base APENAS nos trechos acima.\n"
        "- Priorize os trechos do documento cujo nome mais combina com o assunto da pergunta.\n"
        "- Identifique claramente o documento fonte no início da resposta.\n"
        "- Se houver etapas, responsáveis, formulários ou prazos nos trechos, descreva cada um.\n"
        "- Finalize com 'Em resumo,' reforçando o que o colaborador deve fazer na prática."
    )

# ========================= HISTÓRICO DE CONVERSA =========================
def _get_conversation_history() -> list[dict]:
    history = _state_get("chat_history", [])
    if not history:
        return []
    return history[-(HISTORY_TURNS * 2):]

def _append_to_history(role: str, content: str):
    history = _state_get("chat_history", [])
    history.append({"role": role, "content": content})
    if len(history) > 20:
        history = history[-20:]
    _state_set("chat_history", history)

# ========================= AUDITORIA =========================
def auditar_base_conhecimento():
    try:
        src = _list_sources_cached(FOLDER_ID)
        files_json = src.get("json", []) if USE_JSONL else []
        files_docx = src.get("docx", []) or []

        signature = _build_signature_sources(files_json, files_docx)
        blocks_raw = _download_and_parse_blocks(signature, FOLDER_ID)
        grouped = agrupar_blocos(blocks_raw, janela=GROUP_WINDOW)

        linhas = []
        linhas.append("Auditoria da base de conhecimento")
        linhas.append(f"FOLDER_ID: {FOLDER_ID}")
        linhas.append(f"CACHE_BUSTER: {CACHE_BUSTER}")
        linhas.append(f"EMBED_MODEL: {EMBED_MODEL_NAME}")
        linhas.append(f"CE_MODEL: {CE_MODEL_NAME}")
        linhas.append(f"USE_CE: {USE_CE}")
        linhas.append("")

        linhas.append(f"JSON/JSONL encontrados (apos filtro): {len(files_json)}")
        for f in sorted(files_json, key=lambda x: x.get("name", "").lower()):
            linhas.append(
                f"  [JSON] {f.get('name')} | id={f.get('id')} | modified={f.get('modifiedTime')}"
            )

        linhas.append("")
        linhas.append(f"DOCX encontrados: {len(files_docx)}")
        for f in sorted(files_docx, key=lambda x: x.get("name", "").lower()):
            linhas.append(
                f"  [DOCX] {f.get('name')} | id={f.get('id')} | modified={f.get('modifiedTime')}"
            )

        linhas.append("")
        linhas.append(f"Total de blocos brutos carregados: {len(blocks_raw)}")
        linhas.append(f"Total de blocos agrupados: {len(grouped)}")

        contagem_por_documento = {}
        for b in blocks_raw:
            nome = b.get("pagina", "?")
            contagem_por_documento[nome] = contagem_por_documento.get(nome, 0) + 1

        linhas.append("")
        linhas.append(f"Documentos presentes nos blocos: {len(contagem_por_documento)}")
        for nome in sorted(contagem_por_documento):
            linhas.append(f"  -> {nome} ({contagem_por_documento[nome]} blocos)")

        linhas.append("")
        linhas.append("Previa da signature:")
        linhas.append(signature[:1200] + ("..." if len(signature) > 1200 else ""))

        return "\n".join(linhas)

    except Exception as e:
        return f"Erro ao auditar base: {e}"

# ========================= PRINCIPAL =========================
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY,
                        model_id: str = MODEL_ID, history: list[dict] = None):
    t0 = time.perf_counter()
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "Pergunta vazia."

        comando = pergunta.lower().strip()
        if comando in ["/auditar", "/debug_base", "/base", "auditar base", "debug base"]:
            return auditar_base_conhecimento()

        tipo_contratacao: Optional[str] = _parse_tipo_contratacao(pergunta)

        _state_set("awaiting_rh_tipo", False)
        _state_pop("pending_rh_question", None)

        candidates = ann_search(pergunta, top_n=TOP_N_ANN, tipo_contratacao=tipo_contratacao)
        if not candidates:
            resp = gerar_resposta_fallback_interativa(pergunta, api_key, model_id)
            _append_to_history("user", pergunta)
            _append_to_history("assistant", resp)
            return resp

        reranked = candidates[:top_k]
        blocos_relevantes = [r["block"] for r in reranked]

        t_rag = time.perf_counter()

        prompt = montar_prompt_rag(pergunta, blocos_relevantes, tipo_contratacao=tipo_contratacao)

        # --- Monta mensagens COM histórico de conversa ---
        messages = [{"role": "system", "content": SYSTEM_PROMPT_RAG}]

        conv_history = history if history is not None else _get_conversation_history()
        if conv_history:
            for msg in conv_history:
                content = msg.get("content", "")
                if len(content) > 500:
                    content = content[:500] + "..."
                messages.append({"role": msg["role"], "content": content})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_id,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "n": 1,
            "stream": False,
        }

        try:
            resp = session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            resposta_final = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except requests.exceptions.RequestException as e:
            return f"Erro de conexao com a API: {e}"
        except (ValueError, KeyError, IndexError):
            return "Nao consegui interpretar a resposta da API."

        if not resposta_final or not resposta_final.strip():
            return "A resposta da API veio vazia ou incompleta."

        resposta = resposta_final.strip()

        if blocos_relevantes and not _is_off_domain_reply(resposta):
            bloco_link = _escolher_bloco_para_link(pergunta, resposta, blocos_relevantes)
            if bloco_link:
                doc_id = bloco_link.get("file_id")
                raw_nome = bloco_link.get("pagina", "?")
                doc_nome = sanitize_doc_name(raw_nome)
                if doc_id:
                    link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                    resposta += f"\n\nDocumento relacionado: {doc_nome}\n{link}"

        _append_to_history("user", pergunta)
        _append_to_history("assistant", resposta)

        t_end = time.perf_counter()
        print(
            f"[QD-BOT v7] embed={EMBED_MODEL_NAME} | ce={USE_CE} | "
            f"RAG: {t_rag - t0:.2f}s | LLM: {t_end - t_rag:.2f}s | "
            f"Total: {t_end - t0:.2f}s | candidates={len(candidates)} top_k={top_k}"
        )

        return resposta

    except Exception as e:
        return f"Erro interno: {e}"

# ========================= CLI =========================
if __name__ == "__main__":
    print(f"\nQD-Bot v7 | Embed: {EMBED_MODEL_NAME} | CE: {CE_MODEL_NAME}")
    print("Digite sua pergunta (ou 'sair'):\n")
    cli_history = []
    while True:
        q = input("Pergunta: ").strip()
        if q.lower() in ("sair", "exit", "quit"):
            break
        print("\nResposta:\n" + "=" * 20)
        r = responder_pergunta(q, history=cli_history)
        print(r)
        print("=" * 20 + "\n")
        cli_history.append({"role": "user", "content": q})
        cli_history.append({"role": "assistant", "content": r})
        if len(cli_history) > HISTORY_TURNS * 2:
            cli_history = cli_history[-(HISTORY_TURNS * 2):]