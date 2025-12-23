# openai_backend.py — RAG conversacional detalhado + link do POP correto
# (Atualizado: desambiguação inteligente para processos de Pessoas/RH:
#  Obra (Departamento Pessoal / PO.08) vs Administrativo (Pessoas & Performance / PO.06))

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
USE_CE = False  # CrossEncoder desativado para manter leve/rápido

TOP_N_ANN = 12   # candidatos na ANN
TOP_K = 5        # blocos que vão para o contexto

MAX_WORDS_PER_BLOCK = 180
GROUP_WINDOW = 2

MAX_TOKENS = 750
REQUEST_TIMEOUT = 60
TEMPERATURE = 0.30

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

# ========= SYSTEM PROMPT (CONVERSACIONAL + MANUAL INTERNO) =========
SYSTEM_PROMPT_RAG = """
Você é o QD Bot, assistente virtual interno da Quadra Engenharia.

Seu papel:
- Ajudar colaboradores a entender POPs, políticas e procedimentos internos.
- Falar SEMPRE em português do Brasil.
- Manter tom profissional e técnico, mas acessível.

Estilo de resposta (muito importante):
- Evite respostas curtas. Quando o contexto trouxer um procedimento detalhado, descreva-o de forma igualmente detalhada.
- Estruture a resposta de forma parecida com um manual interno bem escrito.

Regras de conteúdo:
- Use APENAS as informações dos trechos de documentos fornecidos no contexto.
- Quando o contexto trouxer regras gerais (por exemplo, compras de materiais de expediente ou gestão de férias),
  aplique essas regras ao caso específico perguntado (por exemplo, toner, benefício, formulário), mesmo que a palavra exata não apareça.

Interpretação de perguntas de Pessoas/RH (muito importante):
- Se a pergunta indicar temas como admissão/contratação, período de experiência, avaliação de desempenho,
  desligamento/rescisão, férias, ponto/folha, ASO, documentos admissionais, benefícios ou rotinas de pessoal,
  interprete SEMPRE como dúvida sobre procedimentos internos da Quadra Engenharia.
- Nesses casos, NÃO trate como assunto externo. Use os POPs e documentos internos do contexto
  para descrever o fluxo (responsáveis, formulários, prazos, etapas, aprovações etc.).

Fora de escopo:
- Se a pergunta fugir totalmente de procedimentos internos, você NÃO deve tentar responder sobre assunto externo.
  Nesses casos, responda curto e educado, começando com a frase exata:

  "Meu foco é ajudar com procedimentos operacionais padrão (POPs), políticas e rotinas internas da Quadra Engenharia."
"""

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2025-11-25-RAG-GERAL-OFFDOMAIN-01"

# ========= HTTP SESSION =========
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY.strip()}",
    "Content-Type": "application/json"
})

# ========================= STATE (ROBUSTO: STREAMLIT OU CLI) =========================
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
    inter = len(q_tokens & t_tokens)
    return inter / len(q_tokens)

def _overlap_score(a: str, b: str) -> float:
    ta = set(_tokenize(a))
    tb = set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(1.0, len(ta))

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
HR_TIPO_OBRA = "obra"               # Departamento Pessoal (PO.08)
HR_TIPO_ADMIN = "administrativo"    # Pessoas & Performance (PO.06)

def _is_people_process_question(q: str) -> bool:
    """
    Detecta se a pergunta é de Pessoas/RH (contratação, experiência, avaliação, férias, ponto, desligamento, etc.)
    para disparar a escolha Obra x Administrativo antes de responder.
    """
    t = _strip_accents((q or "").lower())

    termos = [
        # pessoas gerais
        "colaborador", "colaboradores", "funcionario", "funcionarios", "funcionário", "funcionários",
        "empregado", "empregados", "clt",

        # contratação / admissão
        "contrat", "admiss", "admit", "recrut", "sele", "vaga", "curriculo", "currículo", "entrevista",
        "aso", "documentos admissionais", "documentacao admissional", "documentação admissional",

        # experiência / avaliação / desempenho
        "experiencia", "experiência", "periodo de experiencia", "período de experiência", "contrato de experiencia",
        "avaliacao", "avaliação", "desempenho", "feedback", "pdi", "metas", "performance",

        # desligamento / rescisão
        "deslig", "demiss", "rescis", "aviso previo", "aviso prévio", "termino de contrato", "término de contrato",

        # rotina de pessoal
        "férias", "ferias", "ponto", "banco de horas", "folha", "holerite", "salario", "salário",
        "atestado", "afastamento", "beneficio", "benefícios", "vr", "vt", "vale transporte", "vale refeicao", "vale refeição",
        "epi", "epis", "uniforme",

        # áreas/nomes
        "departamento pessoal", " dp", "pessoas e performance", "pessoas & performance", " pp", "rh",
        "po.06", "po 06", "po.08", "po 08",
    ]

    # match com cuidado em dp/pp (evitar pegar "dp" dentro de palavra)
    if re.search(r"\bdp\b", t) or re.search(r"\bpp\b", t):
        return True

    return any(x in t for x in termos)

def _parse_tipo_contratacao(texto: str) -> Optional[str]:
    """
    Retorna 'obra' | 'administrativo' | None
    Entende: 'Obra', 'Administrativo', '1', '2', 'DP', 'PP', PO.08, PO.06, sede, canteiro.
    """
    t_raw = (texto or "").strip()
    t = _strip_accents(t_raw.lower())

    # respostas numéricas
    if re.fullmatch(r"\s*1\s*", t_raw):
        return HR_TIPO_OBRA
    if re.fullmatch(r"\s*2\s*", t_raw):
        return HR_TIPO_ADMIN

    # sinais fortes (diretos)
    if "pessoas e performance" in t or "pessoas & performance" in t or "po.06" in t or "po 06" in t or re.search(r"\bpp\b", t):
        return HR_TIPO_ADMIN
    if "departamento pessoal" in t or "po.08" in t or "po 08" in t or re.search(r"\bdp\b", t):
        return HR_TIPO_OBRA

    # sinais por contexto
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
    """
    Boost leve para puxar o POP certo (sem travar o RAG).
    """
    if not tipo or not block:
        return 0.0

    pagina = _strip_accents((block.get("pagina") or "")).lower()
    texto = _strip_accents((block.get("texto") or "")).lower()
    hay = f"{pagina}\n{texto}"

    if tipo == HR_TIPO_OBRA:
        chaves = ["po.08", "po 08", "controle de pessoal", "departamento pessoal", " dp ", "obra", "r.02", "r 02"]
        return 0.20 if any(k in hay for k in chaves) else 0.0

    if tipo == HR_TIPO_ADMIN:
        chaves = ["po.06", "po 06", "pessoas e performance", "pessoas & performance", "recrutamento", "selecao", "seleção"]
        return 0.20 if any(k in hay for k in chaves) else 0.0

    return 0.0

def _expand_query_for_hr(query: str, tipo_contratacao: Optional[str] = None) -> str:
    """
    Expande queries para melhorar match semântico (Pessoas/RH + Compras).
    """
    q_norm = _strip_accents(query.lower())
    extras = []

    # Pessoas/RH geral
    if _is_people_process_question(query):
        extras.append(
            "rotinas de pessoas rh procedimentos internos pop quadra "
            "controle de pessoal pessoas e performance departamento pessoal "
            "formularios prazos responsaveis aprovacao fluxo"
        )

    # Experiência / avaliação
    if "experien" in q_norm or "experiên" in q_norm:
        extras.append(
            "periodo de experiencia contrato de experiencia 45 dias 90 dias "
            "avaliacao de desempenho feedback ficha de avaliacao F.90 F.99"
        )

    # Contratação/admissão (reforço)
    if any(x in q_norm for x in ["contrat", "admiss", "admit", "recrut", "sele", "vaga", "curricul", "entrevist"]):
        extras.append(
            "contratação de funcionários admissão de colaboradores "
            "processo de admissão recrutamento seleção de candidatos "
            "documentos admissionais aso cadastro de colaborador"
        )

    # Desligamento/rescisão
    if any(x in q_norm for x in ["deslig", "demiss", "rescis", "aviso previo", "aviso prévio", "termino de contrato", "término de contrato"]):
        extras.append(
            "procedimento de desligamento rescisao documentos rescisorios "
            "controle de aviso previo ficha avaliacao prazos dp"
        )

    # Roteamento por tipo (quando informado)
    if tipo_contratacao == HR_TIPO_OBRA:
        extras.append("Obra canteiro Departamento Pessoal DP PO.08 Controle de Pessoal R.02")
    elif tipo_contratacao == HR_TIPO_ADMIN:
        extras.append("Administrativo sede escritório Pessoas e Performance PO.06 Pessoas e Performance")

    # Compras / toner como material de expediente
    if "toner" in q_norm:
        extras.append(
            "material de expediente suprimentos de escritório cartucho de impressão "
            "cartucho de impressora toner de impressora compras de materiais de expediente "
            "procedimento de solicitação de material de expediente F.18 F.45 Departamento de Compras"
        )

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
            "2. Explique que você é um assistente treinado principalmente com documentos internos "
            "   (procedimentos, POPs, rotinas, fluxos da Quadra) e que não localizou nada específico "
            "   sobre essa pergunta nos documentos.\n"
            "3. Ajude o usuário a continuar: sugira que ele reformule a dúvida focando em processos, "
            "   políticas, POPs, rotinas ou documentos da Quadra, com uma pergunta final amigável.\n"
            "4. Use um tom profissional, mas próximo e amigável, em português do Brasil.\n\n"
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
    return [f for f in files if f.get("name", "").lower().endswith((".jsonl", ".json"))]

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

@st.cache_data(show_spinner=False)
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
    texts = [b["texto"] for b in grouped]

    @st.cache_data(show_spinner=False)
    def _embed_texts_cached(texts_, sig: str, _v2=CACHE_BUSTER):
        return sbert.encode(texts_, convert_to_numpy=True, normalize_embeddings=True)

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

    query_for_embed = _expand_query_for_hr(query_text, tipo_contratacao=tipo_contratacao)
    q = sbert.encode([query_for_embed], convert_to_numpy=True, normalize_embeddings=True)[0]

    if vecdb["use_faiss"]:
        import numpy as _np
        D, I = vecdb["index"].search(q.reshape(1, -1).astype(_np.float32), top_n)
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

        b_tipo = _tipo_boost(block, tipo_contratacao) if tipo_contratacao else 0.0
        adj_score = float(s) + 0.25 * lex + b_tipo

        results.append({
            "idx": i,
            "score": adj_score,
            "block": block,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]

# ========================= PROMPT RAG =========================
def montar_prompt_rag(pergunta, blocos, tipo_contratacao: Optional[str] = None):
    if not blocos:
        return (
            "Nenhum trecho de POP relevante foi encontrado para a pergunta abaixo.\n"
            "Explique educadamente que não há informação disponível nos documentos internos "
            "e convide o usuário a reformular a dúvida com foco em processos, políticas ou rotinas da Quadra.\n\n"
            f"Pergunta do colaborador: {pergunta}"
        )

    contexto_parts = []
    for i, b in enumerate(blocos, start=1):
        texto = b.get("texto") or ""
        if len(texto) > 3000:
            texto = texto[:3000]
        pagina = b.get("pagina", "?")
        contexto_parts.append(f"[Trecho {i} – {pagina}]\n{texto}")

    contexto_str = "\n\n".join(contexto_parts)

    tipo_txt = ""
    if tipo_contratacao == HR_TIPO_OBRA:
        tipo_txt = "Contexto informado: OBRA (Departamento Pessoal – PO.08 - Controle de Pessoal R.02)."
    elif tipo_contratacao == HR_TIPO_ADMIN:
        tipo_txt = "Contexto informado: ADMINISTRATIVO (Pessoas & Performance – PO.06 - Pessoas e Performance)."

    prompt_usuario = (
        "Abaixo estão trechos de documentos internos e POPs da Quadra Engenharia.\n"
        "Você deve usar ESSES trechos para responder à pergunta sobre processos, políticas ou rotinas internas.\n\n"
        f"{tipo_txt}\n\n"
        "Instruções para montar a resposta:\n"
        "1. Identifique claramente qual processo está sendo descrito (por exemplo, compras, gestão de férias,\n"
        "   controle de pessoal, admissão, período de experiência, avaliação de desempenho, desligamento etc.) e deixe isso explícito no primeiro parágrafo.\n"
        "2. Se o contexto trouxer diferenças entre Sede/Escritório e Obras, organize a resposta em seções numeradas.\n"
        "3. Dentro de cada seção, escreva por extenso, em frases completas.\n"
        "   Você pode usar o símbolo “•” ou parágrafos separados para destacar prazos, responsáveis, formulários e etapas.\n"
        "4. Finalize com “Em resumo,” reforçando o que o colaborador deve fazer na prática.\n\n"
        f"Trechos de contexto dos POPs:\n{contexto_str}\n\n"
        f"Pergunta do colaborador: {pergunta}"
    )

    return prompt_usuario

# ========================= PRINCIPAL =========================
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY, model_id: str = MODEL_ID):
    t0 = time.perf_counter()
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        tipo_contratacao: Optional[str] = None
        forced_tipo: Optional[str] = None

        # ===== 0) Se estamos aguardando a escolha (Obra/Admin), tratar e seguir para a pergunta original =====
        if _state_get("awaiting_rh_tipo", False):
            tipo = _parse_tipo_contratacao(pergunta)
            if not tipo:
                return (
                    "Antes de eu seguir, responda apenas com **Obra** ou **Administrativo** (Pessoas & Performance) — "
                    "ou **1** / **2**."
                )

            _state_set("awaiting_rh_tipo", False)
            pergunta_original = _state_pop("pending_rh_question", "")

            if not pergunta_original:
                return "✅ Entendi. Agora me envie sua dúvida sobre o processo de Pessoas/RH."

            forced_tipo = tipo
            pergunta = pergunta_original  # retoma a pergunta original

        # ===== 1) Se for tema de Pessoas/RH e tipo NÃO estiver explícito, perguntar SEMPRE antes do RAG =====
        if _is_people_process_question(pergunta):
            # Regra: só considera tipo se estiver explícito (na msg atual) OU se veio do passo de escolha (forced_tipo)
            tipo_contratacao = forced_tipo or _parse_tipo_contratacao(pergunta)

            if not tipo_contratacao:
                _state_set("awaiting_rh_tipo", True)
                _state_set("pending_rh_question", pergunta)
                return (
                    "Antes de eu te orientar, isso se refere a:\n\n"
                    "1) **Obra** (Departamento Pessoal)\n"
                    "2) **Administrativo** (Pessoas & Performance)\n\n"
                    "Responda com **Obra** ou **Administrativo** (ou apenas **1** / **2**)."
                )

        # 2) Busca ANN
        candidates = ann_search(pergunta, top_n=TOP_N_ANN, tipo_contratacao=tipo_contratacao)
        if not candidates:
            return gerar_resposta_fallback_interativa(pergunta, api_key, model_id)

        # 3) Usa os TOP_K blocos
        reranked = candidates[:top_k]
        blocos_relevantes = [r["block"] for r in reranked]

        t_rag = time.perf_counter()

        # 4) Monta prompt
        prompt = montar_prompt_rag(pergunta, blocos_relevantes, tipo_contratacao=tipo_contratacao)

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_RAG},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "n": 1,
            "stream": False,
        }

        # 5) Chamada à API
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
            return f"❌ Erro de conexão com a API: {e}"
        except (ValueError, KeyError, IndexError):
            return "⚠️ Não consegui interpretar a resposta da API."

        if not resposta_final or not resposta_final.strip():
            return "⚠️ A resposta da API veio vazia ou incompleta."

        resposta = resposta_final.strip()

        # 6) Link para o documento mais provável (não anexar se for fora de escopo)
        if blocos_relevantes and not _is_off_domain_reply(resposta):
            bloco_link = _escolher_bloco_para_link(pergunta, resposta, blocos_relevantes)
            if bloco_link:
                doc_id = bloco_link.get("file_id")
                raw_nome = bloco_link.get("pagina", "?")
                doc_nome = sanitize_doc_name(raw_nome)
                if doc_id:
                    link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                    resposta += f"\n\n📄 Documento relacionado: {doc_nome}\n🔗 {link}"

        t_end = time.perf_counter()
        print(f"[DEBUG QD-BOT] RAG: {t_rag - t0:.2f}s | Total responder_pergunta: {t_end - t0:.2f}s")

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
        print("\nResposta:\n" + "=" * 20)
        print(responder_pergunta(q))
        print("=" * 20 + "\n")
