# openai_backend.py — RAG conversacional v8.2
# Ajustes principais:
#   1. Leitura robusta de JSON, JSONL e objeto JSON único
#   2. Suporte a DoclingDocument (.json/.jsonl novos)
#   3. Auditoria preservada, agora refletindo corretamente blocos vindos dos JSONs novos
#   4. Pipeline de RAG mantido (ANN + boosts + cross-encoder + prompt final)
#   5. Logs de diagnóstico por arquivo no parse JSON

import os
import io
import re
import json
import time
import unicodedata
from typing import Optional, Any

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
USE_CE = True  # mMARCO multilíngue

TOP_N_ANN = 15
TOP_K = 5
DEDUP_MAX_OVERLAP = 0.75
MIN_SCORE_THRESHOLD = 0.25
RELATIVE_SCORE_CUTOFF = 0.60

MAX_WORDS_PER_BLOCK = 180
GROUP_WINDOW = 2

MAX_TOKENS = 750
REQUEST_TIMEOUT = 60
TEMPERATURE = 0.30

HISTORY_TURNS = 3

# ========= EMBEDDING MODEL =========
EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# ========= CROSS-ENCODER MODEL =========
CE_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
CE_WEIGHT = 0.45
EMB_WEIGHT = 0.55

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

# ========= SYSTEM PROMPT =========
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
CACHE_BUSTER = "2026-04-01-v8.2-docling-json"

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

def _safe_get_first_page_no(item: dict) -> Optional[int]:
    try:
        prov = item.get("prov") or []
        if prov and isinstance(prov, list):
            page_no = prov[0].get("page_no")
            if page_no is not None:
                return int(page_no)
    except Exception:
        pass
    return None

def _normalize_spaces(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _looks_like_docling_document(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("schema_name") == "DoclingDocument":
        return True
    if "texts" in obj and "body" in obj:
        return True
    return False

# ========================= ROTAS PESSOAS/RH: OBRA x ADMIN =========================
HR_TIPO_OBRA = "obra"
HR_TIPO_ADMIN = "administrativo"

def _is_people_process_question(q: str) -> bool:
    t = _strip_accents((q or "").lower())
    termos = [
        "colaborador", "colaboradores", "funcionario", "funcionarios",
        "empregado", "empregados", "clt",
        "admiss", "admit", "recrut", "sele", "vaga", "curriculo", "entrevista",
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

def _is_contract_question(q: str) -> bool:
    t = _strip_accents((q or "").lower())
    sinais = [
        "aditivo", "medicao", "medição", "medicoes", "medições",
        "boletim", "fornecedor", "terceirizado", "terceirizados",
        "gestao de terceirizados", "gestão de terceirizados",
        "clausula", "cláusula", "contratual", "contratuais",
        "contrato de fornecedor", "contratos e medicoes", "contratos e medições",
        "sienge", "tratto",
    ]
    return any(x in t for x in sinais)

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

# ========================= BOOST POR DOMÍNIO DO DOCUMENTO =========================
def _domain_boost(query: str, block: dict) -> float:
    pagina = _strip_accents((block.get("pagina") or "")).lower()

    if _is_contract_question(query):
        sinais_compras = ["compra", "po.07", "po 07"]
        if any(s in pagina for s in sinais_compras):
            return -0.25

        sinais_contrato = ["contrato", "medicao", "medicoes", "aditivo",
                           "terceirizado", "gestao de terceirizados", "boletim"]
        if any(s in pagina for s in sinais_contrato):
            return 0.35

        sinais_fora = ["pessoal", "po.08", "po 08", "po.06", "po 06"]
        if any(s in pagina for s in sinais_fora):
            return -0.20

    if _is_people_process_question(query) and not _is_contract_question(query):
        if "pessoal" in pagina or "pessoas" in pagina or "po.08" in pagina or "po.06" in pagina:
            return 0.25
        if any(s in pagina for s in ["contrato", "medicao", "compra", "po.07"]):
            return -0.15

    return 0.0

# ========================= QUERY EXPANSION (LEVE) =========================
def _expand_query_for_hr(query: str, tipo_contratacao: Optional[str] = None) -> str:
    q_norm = _strip_accents(query.lower())
    extras = []

    if _is_contract_question(query):
        extras.append("gestão contratual medições aditivo boletim obra terceirizados")
    elif _is_people_process_question(query):
        extras.append("procedimento pessoal rotina interna")
        if tipo_contratacao == HR_TIPO_OBRA:
            extras.append("obra departamento pessoal PO.08")
        elif tipo_contratacao == HR_TIPO_ADMIN:
            extras.append("administrativo pessoas performance PO.06")

    if "toner" in q_norm:
        extras.append("material expediente cartucho impressora compras")

    if "gestao de terceirizados" in q_norm or "gestão de terceirizados" in q_norm:
        extras.append("gestão terceirizados avaliação portaria supervisão")

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
    model = SentenceTransformer(EMBED_MODEL_NAME)
    model.encode(["teste"], normalize_embeddings=True)
    print(f"[QD-BOT v8.2] Embedding carregado: {EMBED_MODEL_NAME}")
    return model

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    if not USE_CE:
        return None
    from sentence_transformers import CrossEncoder
    try:
        ce = CrossEncoder(CE_MODEL_NAME, max_length=512)
        score = ce.predict([("aditivo de contrato", "procedimento para aditivo contratual")])
        score0 = float(np.atleast_1d(score)[0])
        print(f"[QD-BOT v8.2] Cross-encoder carregado: {CE_MODEL_NAME} (teste={score0:.3f})")
        return ce
    except Exception as e:
        print(f"[QD-BOT v8.2] Cross-encoder falhou: {e} — continuando sem CE")
        return None

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

# ========================= PARSE DOCX =========================
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

# ========================= PARSE JSON / JSONL / DOCLING =========================
def _load_jsonish(text: str) -> Any:
    """
    Tenta ler:
    - JSON array
    - JSON objeto único
    - JSONL (um objeto por linha)
    """
    raw = (text or "").strip()
    if not raw:
        return []

    try:
        return json.loads(raw)
    except Exception:
        pass

    recs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    return recs

def _flatten_simple_json_records(obj: Any):
    """
    Normaliza para lista de registros simples quando possível.
    """
    if obj is None:
        return []

    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        if any(k in obj for k in ("pagina", "page", "doc", "texto", "text", "content")):
            return [obj]

        for key in ("records", "items", "data", "chunks", "blocks"):
            val = obj.get(key)
            if isinstance(val, list):
                return val

    return []

def _extract_blocks_from_docling_document(doc_obj: dict, fallback_name: str, file_id: str):
    """
    Extrai blocos úteis de um DoclingDocument.
    Estratégia:
    - lê doc_obj["texts"]
    - ignora mobiliário/cabeçalhos/rodapés e textos vazios
    - agrupa por página
    - mantém headers, list_items e textos do corpo
    """
    texts = doc_obj.get("texts") or []
    if not isinstance(texts, list) or not texts:
        return []

    doc_name = (
        doc_obj.get("name")
        or (doc_obj.get("origin") or {}).get("filename")
        or fallback_name
    )
    doc_name = sanitize_doc_name(doc_name)

    allowed_labels = {
        "section_header",
        "text",
        "list_item",
        "title",
        "caption",
        "subtitle",
    }
    ignored_labels = {
        "page_header",
        "page_footer",
    }
    ignored_content_layers = {
        "furniture",
    }

    noise_texts = {
        "imprimir/salvar comopdf",
        "quadra",
        "engenharia",
        "en genharia",
        "e n g e nharia",
        "en g e nharia",
        "-",
    }

    pages: dict[int, list[str]] = {}

    for t in texts:
        if not isinstance(t, dict):
            continue

        label = (t.get("label") or "").strip()
        content_layer = (t.get("content_layer") or "").strip()
        txt = (t.get("text") or t.get("orig") or "").strip()
        page_no = _safe_get_first_page_no(t)

        if not txt:
            continue
        if label in ignored_labels:
            continue
        if content_layer in ignored_content_layers:
            continue
        if label and label not in allowed_labels:
            # Mantém por tolerância; há textos úteis com labels irregulares em alguns exports
            pass

        txt_norm = _strip_accents(txt.lower())
        if txt_norm in noise_texts:
            continue

        if page_no is None:
            page_no = 1

        pages.setdefault(page_no, []).append(txt)

    out = []
    for page_no in sorted(pages):
        joined = "\n".join(pages[page_no])
        joined = _normalize_spaces(joined)
        if not joined:
            continue

        pagina_nome = f"{doc_name} [p.{page_no}]"
        for chunk in _split_text_blocks(joined, max_words=MAX_WORDS_PER_BLOCK):
            chunk = _normalize_spaces(chunk)
            if chunk:
                out.append({
                    "pagina": pagina_nome,
                    "texto": chunk,
                    "file_id": file_id
                })

    return out

def _extract_blocks_from_docling_list(doc_list: list, fallback_name: str, file_id: str):
    out = []
    for idx, obj in enumerate(doc_list, start=1):
        if _looks_like_docling_document(obj):
            blocks = _extract_blocks_from_docling_document(
                obj,
                fallback_name=f"{sanitize_doc_name(fallback_name)} #{idx}",
                file_id=file_id
            )
            out.extend(blocks)
    return out

def _json_records_to_blocks(obj: Any, fallback_name: str, file_id: str):
    """
    Converte o conteúdo JSON carregado em blocos.
    Suporta:
    - lista de registros simples
    - objeto simples
    - DoclingDocument
    - lista de DoclingDocuments
    """
    if obj is None:
        return []

    if _looks_like_docling_document(obj):
        return _extract_blocks_from_docling_document(obj, fallback_name=fallback_name, file_id=file_id)

    if isinstance(obj, list) and obj and any(_looks_like_docling_document(x) for x in obj if isinstance(x, dict)):
        return _extract_blocks_from_docling_list(obj, fallback_name=fallback_name, file_id=file_id)

    recs = _flatten_simple_json_records(obj)

    out = []
    for r in recs:
        if not isinstance(r, dict):
            continue

        pagina = r.get("pagina") or r.get("page") or r.get("doc") or fallback_name
        texto = r.get("texto") or r.get("text") or r.get("content") or ""
        fid = r.get("file_id") or r.get("source_id") or file_id

        if str(texto).strip():
            for chunk in _split_text_blocks(str(texto), max_words=MAX_WORDS_PER_BLOCK):
                if chunk.strip():
                    out.append({
                        "pagina": str(pagina),
                        "texto": str(chunk),
                        "file_id": fid
                    })

    return out

# ========================= TEXTO PARA EMBEDDING =========================
def _texto_para_embedding(block: dict) -> str:
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
    raw_text = _download_text(drive, file_id)
    loaded = _load_jsonish(raw_text)
    blocks = _json_records_to_blocks(loaded, fallback_name=name, file_id=file_id)
    print(f"[QD-BOT v8.2] JSON parseado: {name} -> {len(blocks)} blocos")
    return blocks

@st.cache_data(show_spinner=False, ttl=600)
def _download_and_parse_blocks(signature: str, folder_id: str, _v=CACHE_BUSTER):
    sources = _list_sources_cached(folder_id)
    files_json = sources.get("json", []) if USE_JSONL else []
    files_docx = sources.get("docx", []) or []

    blocks = []

    for f in files_json:
        try:
            md5 = f.get("md5Checksum", f.get("modifiedTime", ""))
            parsed = _parse_json_cached(f["id"], md5, f["name"])
            if parsed:
                blocks.extend(parsed)
        except Exception as e:
            print(f"[QD-BOT v8.2] Falha ao parsear JSON {f.get('name')}: {e}")
            continue

    for f in files_docx:
        try:
            md5 = f.get("md5Checksum", f.get("modifiedTime", ""))
            parsed = _parse_docx_cached(f["id"], md5, f["name"])
            if parsed:
                blocks.extend(parsed)
        except Exception as e:
            print(f"[QD-BOT v8.2] Falha ao parsear DOCX {f.get('name')}: {e}")
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

# ========================= DEDUPLICAÇÃO =========================
def _deduplicate_results(results: list, max_overlap: float = DEDUP_MAX_OVERLAP) -> list:
    if not results:
        return results
    selected = [results[0]]
    for r in results[1:]:
        txt = r["block"].get("texto", "")
        is_dup = False
        for s in selected:
            s_txt = s["block"].get("texto", "")
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
    except Exception as e:
        print(f"[QD-BOT v8.2] Falha ao carregar índice pré-computado: {e}")
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
    texts = [_texto_para_embedding(b) for b in grouped]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, sig: str, _v2=CACHE_BUSTER):
        return sbert.encode(
            texts_,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=64
        )

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

# ========================= BUSCA ANN =========================
def ann_search(query_text: str, top_n: int, tipo_contratacao: Optional[str] = None):
    vecdb = get_vector_index()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    sbert = get_sbert_model()

    query_expanded = _expand_query_for_hr(query_text, tipo_contratacao=tipo_contratacao)
    q = sbert.encode([query_expanded], convert_to_numpy=True, normalize_embeddings=True)[0]

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
        b_domain = _domain_boost(query_text, block)

        adj_score = float(s) + 0.20 * lex + 0.30 * pagina_lex + b_tipo + b_domain
        results.append({"idx": i, "score": adj_score, "block": block})

    results.sort(key=lambda x: x["score"], reverse=True)
    results = _deduplicate_results(results)

    results = [r for r in results if r["score"] >= MIN_SCORE_THRESHOLD]

    if len(results) >= 2:
        best = results[0]["score"]
        if best > 0:
            results = [r for r in results if r["score"] >= best * RELATIVE_SCORE_CUTOFF]

    return results[:top_n]

# ========================= RERANKING COM CROSS-ENCODER =========================
def _rerank_with_ce(query: str, candidates: list, top_k: int) -> list:
    ce = get_cross_encoder()
    if ce is None or not candidates:
        return candidates[:top_k]

    t0 = time.perf_counter()

    pairs = [(query, r["block"].get("texto", "")[:512]) for r in candidates]

    try:
        ce_scores = ce.predict(pairs, show_progress_bar=False)
    except Exception as e:
        print(f"[QD-BOT v8.2] CE predict falhou: {e}")
        return candidates[:top_k]

    ce_min = float(min(ce_scores))
    ce_max = float(max(ce_scores))
    ce_range = ce_max - ce_min if ce_max > ce_min else 1.0

    for r, cs in zip(candidates, ce_scores):
        ce_norm = (float(cs) - ce_min) / ce_range
        r["ce_score"] = float(cs)
        r["score_combined"] = EMB_WEIGHT * r["score"] + CE_WEIGHT * ce_norm

    candidates.sort(key=lambda x: x["score_combined"], reverse=True)

    t1 = time.perf_counter()
    print(f"[QD-BOT v8.2] CE rerank: {t1 - t0:.2f}s | {len(pairs)} pares")

    return candidates[:top_k]

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
        linhas.append("=== Auditoria da base de conhecimento ===")
        linhas.append(f"FOLDER_ID: {FOLDER_ID}")
        linhas.append(f"CACHE_BUSTER: {CACHE_BUSTER}")
        linhas.append(f"EMBED_MODEL: {EMBED_MODEL_NAME}")
        linhas.append(f"CE_MODEL: {CE_MODEL_NAME}")
        linhas.append(f"USE_CE: {USE_CE}")
        linhas.append(f"TOP_N_ANN: {TOP_N_ANN} | TOP_K: {TOP_K} | DEDUP: {DEDUP_MAX_OVERLAP}")
        linhas.append(f"MIN_SCORE: {MIN_SCORE_THRESHOLD} | REL_CUTOFF: {RELATIVE_SCORE_CUTOFF}")
        linhas.append("")

        linhas.append(f"JSON/JSONL encontrados: {len(files_json)}")
        for f in sorted(files_json, key=lambda x: x.get("name", "").lower()):
            linhas.append(f"[JSON] {f.get('name')} | id={f.get('id')}")

        linhas.append("")
        linhas.append(f"DOCX encontrados: {len(files_docx)}")
        for f in sorted(files_docx, key=lambda x: x.get("name", "").lower()):
            linhas.append(f"[DOCX] {f.get('name')} | id={f.get('id')}")

        linhas.append("")
        linhas.append(f"Total blocos brutos: {len(blocks_raw)}")
        linhas.append(f"Total blocos agrupados: {len(grouped)}")

        contagem = {}
        for b in blocks_raw:
            nome = b.get("pagina", "?")
            contagem[nome] = contagem.get(nome, 0) + 1

        linhas.append("")
        linhas.append(f"Documentos nos blocos: {len(contagem)}")
        for nome in sorted(contagem):
            linhas.append(f"-> {nome} ({contagem[nome]} blocos)")

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

        # Fase 1: Busca vetorial + boosts
        candidates = ann_search(pergunta, top_n=TOP_N_ANN, tipo_contratacao=tipo_contratacao)

        if not candidates:
            print(f"[QD-BOT v8.2] Nenhum candidato passou os filtros para: '{pergunta[:60]}'")
            resp = gerar_resposta_fallback_interativa(pergunta, api_key, model_id)
            _append_to_history("user", pergunta)
            _append_to_history("assistant", resp)
            return resp

        t_search = time.perf_counter()

        # Fase 2: Reranking com cross-encoder
        reranked = _rerank_with_ce(pergunta, candidates, top_k)
        blocos_relevantes = [r["block"] for r in reranked]

        if not blocos_relevantes:
            resp = gerar_resposta_fallback_interativa(pergunta, api_key, model_id)
            _append_to_history("user", pergunta)
            _append_to_history("assistant", resp)
            return resp

        t_rerank = time.perf_counter()

        # Fase 3: Montar prompt e chamar LLM
        prompt = montar_prompt_rag(pergunta, blocos_relevantes, tipo_contratacao=tipo_contratacao)

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
        top_docs = [sanitize_doc_name(r["block"].get("pagina", "?")) for r in reranked]
        top_scores_emb = [f"{r['score']:.3f}" for r in reranked]
        top_scores_ce = [f"{r.get('ce_score', 0):.3f}" for r in reranked]
        top_scores_final = [f"{r.get('score_combined', r['score']):.3f}" for r in reranked]
        print(
            f"[QD-BOT v8.2] Query: '{pergunta[:60]}'\n"
            f"  Search: {t_search - t0:.2f}s | CE: {t_rerank - t_search:.2f}s | "
            f"LLM: {t_end - t_rerank:.2f}s | Total: {t_end - t0:.2f}s\n"
            f"  Docs:       {top_docs}\n"
            f"  Emb+boost:  {top_scores_emb}\n"
            f"  CE raw:     {top_scores_ce}\n"
            f"  Final:      {top_scores_final}"
        )

        return resposta

    except Exception as e:
        return f"Erro interno: {e}"

# ========================= CLI =========================
if __name__ == "__main__":
    print(f"\nQD-Bot v8.2 | Embed: {EMBED_MODEL_NAME} | CE: {CE_MODEL_NAME} ({USE_CE})")
    print("Digite sua pergunta (ou 'sair'):\n")
    cli_history = []
    while True:
        q = input("Pergunta: ").strip()
        if q.lower() in ("sair", "exit", "quit"):
            break
        print("\nResposta:\n" + "=" * 40)
        r = responder_pergunta(q, history=cli_history)
        print(r)
        print("=" * 40 + "\n")
        cli_history.append({"role": "user", "content": q})
        cli_history.append({"role": "assistant", "content": r})
        if len(cli_history) > HISTORY_TURNS * 2:
            cli_history = cli_history[-(HISTORY_TURNS * 2):]