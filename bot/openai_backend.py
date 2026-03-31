# openai_backend.py — RAG conversacional v2: embeddings multilíngue, chunking semântico,
# metadata filtering, threshold de relevância, anti-alucinação reforçado
# (Mantém: link do POP, auditoria, desambiguação Obra x Administrativo)

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
USE_CE = False  # Cross-encoder desativado para manter rápido

TOP_N_ANN = 20        # candidatos na ANN (mais candidatos → rerank por score+lex mais eficaz)
TOP_K = 5             # blocos que vão para o contexto
RELEVANCE_THRESHOLD = 0.15  # Permissivo — o GPT cuida da qualidade. Suba gradualmente se alucinar.

MAX_WORDS_PER_BLOCK = 200
OVERLAP_WORDS = 40        # overlap entre blocos consecutivos de mesma seção
GROUP_WINDOW = 2

MAX_TOKENS = 1200
REQUEST_TIMEOUT = 60
TEMPERATURE = 0.25

HISTORY_TURNS = 3  # quantas trocas de conversa manter no payload

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

# ========= SYSTEM PROMPT (REFORÇADO ANTI-ALUCINAÇÃO) =========
SYSTEM_PROMPT_RAG = """
Você é o QD Bot, assistente virtual interno da Quadra Engenharia.

Seu papel:
- Ajudar colaboradores a entender POPs, políticas e procedimentos internos.
- Falar SEMPRE em português do Brasil.
- Manter tom profissional e técnico, mas acessível.

Estilo de resposta (muito importante):
- Evite respostas curtas. Quando o contexto trouxer um procedimento detalhado, descreva-o de forma igualmente detalhada.
- Estruture a resposta de forma parecida com um manual interno bem escrito.

Regras de conteúdo (CRÍTICO — leia com atenção):
- Use APENAS as informações dos trechos de documentos fornecidos no contexto.
- NÃO invente etapas, prazos, formulários, responsáveis ou qualquer informação que NÃO esteja explicitamente nos trechos.
- Se os trechos NÃO contêm informação suficiente para responder com segurança, diga claramente:
  "Os documentos disponíveis não cobrem esse tema em detalhe suficiente. Recomendo consultar o setor responsável."
  NÃO tente completar com conhecimento geral.
- Quando citar um formulário, prazo ou responsável, ele DEVE estar presente nos trechos fornecidos.
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
CACHE_BUSTER = "2026-03-31-v4"

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
    """Escolhe o bloco mais relevante para linkar.
    Prioriza match com a PERGUNTA (não a resposta), porque se a resposta
    alucionou, o link pelo menos aponta pro documento certo."""
    if not blocos:
        return None
    melhor = None
    melhor_score = 0.0
    for b in blocos:
        txt = b.get("texto") or ""
        pagina = b.get("pagina") or ""
        if not txt.strip():
            continue
        s_resp = _overlap_score(resposta or "", txt)
        s_perg = _overlap_score(pergunta or "", txt)
        # Boost forte se o TÍTULO/PAGINA do bloco bate com a pergunta
        s_titulo = _overlap_score(pergunta or "", pagina)
        score = 0.3 * s_resp + 0.5 * s_perg + 0.4 * s_titulo
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

# ========================= METADATA EXTRACTION =========================
# Extrai código POP e departamento de cada bloco para filtragem rápida

_POP_CODE_RE = re.compile(
    r"(PO[\.\s]?\d{2}|F[\.\s]?\d{2,3}|R[\.\s]?\d{2})",
    re.IGNORECASE,
)

_DEPT_KEYWORDS = {
    "compras": "compras",
    "suprimentos": "compras",
    "financeiro": "financeiro",
    "contabil": "financeiro",
    "pessoal": "pessoal",
    "departamento pessoal": "pessoal",
    "pessoas e performance": "pessoas_performance",
    "pessoas & performance": "pessoas_performance",
    "recrutamento": "pessoas_performance",
    "selecao": "pessoas_performance",
    "seleção": "pessoas_performance",
    "engenharia": "engenharia",
    "qualidade": "qualidade",
    "seguranca": "seguranca",
    "segurança": "seguranca",
    "contratos": "contratos",
    "medicoes": "contratos",
    "medições": "contratos",
    "estrategia": "estrategia",
    "inovacao": "estrategia",
}

def _extract_pop_codes(text: str) -> list[str]:
    """Extrai códigos POP (PO.06, F.18, R.02 etc.) do texto."""
    if not text:
        return []
    matches = _POP_CODE_RE.findall(text)
    # Normaliza: PO 06 → PO.06
    normalized = []
    for m in matches:
        clean = re.sub(r"\s+", ".", m.upper())
        if clean not in normalized:
            normalized.append(clean)
    return normalized

def _extract_department(text: str) -> Optional[str]:
    """Identifica departamento a partir de palavras-chave no texto."""
    t = _strip_accents((text or "").lower())
    for keyword, dept in _DEPT_KEYWORDS.items():
        if _strip_accents(keyword) in t:
            return dept
    return None

def _enrich_block_metadata(block: dict) -> dict:
    """Adiciona pop_codes e department ao bloco (sem alterar texto)."""
    combined = f"{block.get('pagina', '')} {block.get('texto', '')}"
    block["pop_codes"] = _extract_pop_codes(combined)
    block["department"] = _extract_department(combined)
    return block

# ========================= ROTAS PESSOAS/RH: OBRA x ADMIN =========================
HR_TIPO_OBRA = "obra"
HR_TIPO_ADMIN = "administrativo"

def _is_people_process_question(q: str) -> bool:
    t = _strip_accents((q or "").lower())
    termos = [
        "colaborador", "colaboradores", "funcionario", "funcionarios", "funcionário", "funcionários",
        "empregado", "empregados", "clt",
        "contrat", "admiss", "admit", "recrut", "sele", "vaga", "curriculo", "currículo", "entrevista",
        "aso", "documentos admissionais", "documentacao admissional", "documentação admissional",
        "experiencia", "experiência", "periodo de experiencia", "período de experiência", "contrato de experiencia",
        "avaliacao", "avaliação", "desempenho", "feedback", "pdi", "metas", "performance",
        "deslig", "demiss", "rescis", "aviso previo", "aviso prévio", "termino de contrato", "término de contrato",
        "férias", "ferias", "ponto", "banco de horas", "folha", "holerite", "salario", "salário",
        "atestado", "afastamento", "beneficio", "benefícios", "vr", "vt", "vale transporte", "vale refeicao", "vale refeição",
        "epi", "epis", "uniforme",
        "departamento pessoal", " dp", "pessoas e performance", "pessoas & performance", " pp", "rh",
        "po.06", "po 06", "po.08", "po 08",
    ]
    if re.search(r"\bdp\b", t) or re.search(r"\bpp\b", t):
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
        chaves = ["po.08", "po 08", "controle de pessoal", "departamento pessoal", " dp ", "obra", "r.02", "r 02"]
        return 0.20 if any(k in hay for k in chaves) else 0.0
    if tipo == HR_TIPO_ADMIN:
        chaves = ["po.06", "po 06", "pessoas e performance", "pessoas & performance", "recrutamento", "selecao", "seleção"]
        return 0.20 if any(k in hay for k in chaves) else 0.0
    return 0.0

def _expand_query_for_hr(query: str, tipo_contratacao: Optional[str] = None) -> str:
    q_norm = _strip_accents(query.lower())
    extras = []

    if _is_people_process_question(query):
        extras.append(
            "rotinas de pessoas rh procedimentos internos pop quadra "
            "controle de pessoal pessoas e performance departamento pessoal "
            "formularios prazos responsaveis aprovacao fluxo"
        )
    if "experien" in q_norm or "experiên" in q_norm:
        extras.append(
            "periodo de experiencia contrato de experiencia 45 dias 90 dias "
            "avaliacao de desempenho feedback ficha de avaliacao F.90 F.99"
        )
    if any(x in q_norm for x in ["contrat", "admiss", "admit", "recrut", "sele", "vaga", "curricul", "entrevist"]):
        extras.append(
            "contratação de funcionários admissão de colaboradores "
            "processo de admissão recrutamento seleção de candidatos "
            "documentos admissionais aso cadastro de colaborador"
        )
    if any(x in q_norm for x in ["deslig", "demiss", "rescis", "aviso previo", "aviso prévio", "termino de contrato", "término de contrato"]):
        extras.append(
            "procedimento de desligamento rescisao documentos rescisorios "
            "controle de aviso previo ficha avaliacao prazos dp"
        )
    if tipo_contratacao == HR_TIPO_OBRA:
        extras.append("Obra canteiro Departamento Pessoal DP PO.08 Controle de Pessoal R.02")
    elif tipo_contratacao == HR_TIPO_ADMIN:
        extras.append("Administrativo sede escritório Pessoas e Performance PO.06 Pessoas e Performance")
    if "toner" in q_norm:
        extras.append(
            "material de expediente suprimentos de escritório cartucho de impressão "
            "cartucho de impressora toner de impressora compras de materiais de expediente "
            "procedimento de solicitação de material de expediente F.18 F.45 Departamento de Compras"
        )
    if extras:
        return query + " " + " ".join(extras)
    return query

# ========================= METADATA FILTER (PRÉ-ANN) =========================
def _extract_query_pop_codes(query: str) -> list[str]:
    return _extract_pop_codes(query)

def _extract_query_department(query: str) -> Optional[str]:
    return _extract_department(query)

def _metadata_prefilter(blocks: list[dict], query: str, tipo_contratacao: Optional[str] = None) -> list[int]:
    """Retorna índices dos blocos que passam pelo filtro de metadados.
    Se nenhum filtro se aplica, retorna todos os índices (sem filtrar)."""
    q_codes = _extract_query_pop_codes(query)
    q_dept = _extract_query_department(query)

    # Também considera tipo_contratacao como filtro de departamento
    if tipo_contratacao == HR_TIPO_OBRA and not q_dept:
        q_dept = "pessoal"
    elif tipo_contratacao == HR_TIPO_ADMIN and not q_dept:
        q_dept = "pessoas_performance"

    # Se não há filtros, retorna tudo
    if not q_codes and not q_dept:
        return list(range(len(blocks)))

    matched_indices = set()
    for i, b in enumerate(blocks):
        b_codes = b.get("pop_codes", [])
        b_dept = b.get("department")

        # Match por código POP explícito (forte)
        if q_codes and b_codes:
            if any(c in b_codes for c in q_codes):
                matched_indices.add(i)
                continue

        # Match por departamento
        if q_dept and b_dept == q_dept:
            matched_indices.add(i)
            continue

    # Se o filtro é muito restritivo (< 5 blocos), relaxa e inclui tudo
    # para não perder contexto relevante
    if len(matched_indices) < 5:
        return list(range(len(blocks)))

    return sorted(matched_indices)

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
    # MiniLM: estável e já testado. Para upgrade futuro, testar
    # intfloat/multilingual-e5-base em ambiente de staging primeiro.
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

# ========================= PARSE DOCX — CHUNKING SEMÂNTICO =========================
def _split_text_blocks_with_overlap(text: str, max_words=MAX_WORDS_PER_BLOCK, overlap=OVERLAP_WORDS):
    """Divide texto em blocos com overlap entre consecutivos."""
    words = text.split()
    if not words:
        return []
    blocks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            blocks.append(chunk)
        # Próximo bloco começa (max_words - overlap) à frente
        start += max(max_words - overlap, 1)
    return blocks

def _detect_heading_level(style_name: str) -> Optional[int]:
    """Detecta se o estilo do parágrafo é um heading e retorna o nível."""
    if not style_name:
        return None
    s = style_name.lower()
    if s.startswith("heading"):
        try:
            return int(s.replace("heading", "").strip())
        except ValueError:
            return 1
    # Estilos personalizados comuns em docs brasileiros
    if "título" in s or "titulo" in s:
        return 1
    return None

def _docx_to_blocks_semantic(file_bytes, file_name, file_id,
                              max_words=MAX_WORDS_PER_BLOCK, overlap=OVERLAP_WORDS):
    """Chunking semântico: respeita headings e parágrafos do DOCX."""
    doc = Document(io.BytesIO(file_bytes))

    sections = []  # lista de {"heading": str, "paragraphs": [str]}
    current_heading = file_name
    current_paragraphs = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = para.style.name if para.style else ""
        heading_level = _detect_heading_level(style_name)

        if heading_level is not None:
            # Salva seção anterior
            if current_paragraphs:
                sections.append({"heading": current_heading, "paragraphs": current_paragraphs})
            current_heading = f"{file_name} — {text}"
            current_paragraphs = []
        else:
            current_paragraphs.append(text)

    # Última seção
    if current_paragraphs:
        sections.append({"heading": current_heading, "paragraphs": current_paragraphs})

    # Agora divide cada seção em blocos com overlap
    blocks = []
    for section in sections:
        section_text = "\n".join(section["paragraphs"])
        chunks = _split_text_blocks_with_overlap(section_text, max_words=max_words, overlap=overlap)
        for chunk in chunks:
            b = {
                "pagina": section["heading"],
                "texto": chunk,
                "file_id": file_id,
            }
            _enrich_block_metadata(b)
            blocks.append(b)

    # Fallback: se nenhum bloco (doc sem parágrafos com texto), tenta bruto
    if not blocks:
        full_text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        for chunk in _split_text_blocks_with_overlap(full_text, max_words=max_words, overlap=overlap):
            b = {"pagina": file_name, "texto": chunk, "file_id": file_id}
            _enrich_block_metadata(b)
            blocks.append(b)

    return blocks

# Mantém compatibilidade: função legada para JSONL
def _split_text_blocks(text, max_words=MAX_WORDS_PER_BLOCK):
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

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
            b = {"pagina": str(pagina), "texto": str(texto), "file_id": fid}
            _enrich_block_metadata(b)
            out.append(b)
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
    return _docx_to_blocks_semantic(_download_bytes(drive, file_id), name, file_id)

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

        merged = {
            "pagina": group[0].get("pagina", "?"),
            "texto": " ".join(b["texto"] for b in group),
            "file_id": current_file_id,
        }
        # Agrega metadados
        all_codes = []
        dept = None
        for b in group:
            all_codes.extend(b.get("pop_codes", []))
            if not dept:
                dept = b.get("department")
        merged["pop_codes"] = list(set(all_codes))
        merged["department"] = dept
        grouped.append(merged)

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

    # Textos para embedding (sem prefixo — MiniLM não usa)
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
    q = sbert.encode(
        [query_for_embed],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )[0]

    # --- Metadata prefilter ---
    allowed_indices = set(_metadata_prefilter(blocks, query_text, tipo_contratacao))

    if vecdb["use_faiss"]:
        import numpy as _np
        # Busca mais candidatos do FAISS, depois filtra
        search_n = min(top_n * 3, len(blocks))
        D, I = vecdb["index"].search(q.reshape(1, -1).astype(_np.float32), search_n)
        raw_idxs = I[0].tolist()
        raw_scores = D[0].tolist()
    else:
        emb = vecdb["emb"]
        scores_all = (emb @ q)
        raw_idxs = np.argsort(-scores_all)[:top_n * 3].tolist()
        raw_scores = [float(scores_all[i]) for i in raw_idxs]

    results = []
    for i, s in zip(raw_idxs, raw_scores):
        if i < 0:
            continue
        block = blocks[i]
        lex = _lexical_overlap(query_text, block.get("texto", ""))
        b_tipo = _tipo_boost(block, tipo_contratacao) if tipo_contratacao else 0.0

        # Blocos que passam no metadata filter ganham boost
        meta_boost = 0.05 if i in allowed_indices else 0.0

        # Boost por título/heading do bloco — se o nome da página/seção
        # bate com a pergunta, é um sinal muito forte de relevância
        pagina = block.get("pagina", "")
        titulo_overlap = _lexical_overlap(query_text, pagina)

        adj_score = float(s) + 0.25 * lex + 0.30 * titulo_overlap + b_tipo + meta_boost
        results.append({
            "idx": i,
            "score": adj_score,
            "raw_score": float(s),
            "block": block,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # --- Diversidade de documentos ---
    # Garante que o top-K não venha todo do mesmo documento.
    # Máximo MAX_PER_DOC blocos por file_id nos primeiros top_k resultados.
    MAX_PER_DOC = 3
    diverse = []
    doc_count = {}
    for r in results:
        fid = r["block"].get("file_id", "?")
        if doc_count.get(fid, 0) < MAX_PER_DOC:
            diverse.append(r)
            doc_count[fid] = doc_count.get(fid, 0) + 1
        if len(diverse) >= top_n:
            break
    # Se não encheu, completa com os restantes
    if len(diverse) < top_n:
        seen_idx = {r["idx"] for r in diverse}
        for r in results:
            if r["idx"] not in seen_idx:
                diverse.append(r)
                if len(diverse) >= top_n:
                    break

    return diverse[:top_n]

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
        pop_codes = ", ".join(b.get("pop_codes", [])) or "—"
        contexto_parts.append(f"[Trecho {i} – {pagina} | POPs: {pop_codes}]\n{texto}")

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
        "1. Identifique claramente qual processo está sendo descrito e deixe isso explícito no primeiro parágrafo.\n"
        "2. Se o contexto trouxer diferenças entre Sede/Escritório e Obras, organize a resposta em seções numeradas.\n"
        "3. Dentro de cada seção, escreva por extenso, em frases completas.\n"
        "4. Finalize com 'Em resumo,' reforçando o que o colaborador deve fazer na prática.\n"
        "5. IMPORTANTE: Se algum detalhe NÃO estiver nos trechos, NÃO invente. Diga que o documento não detalha esse ponto.\n\n"
        f"Trechos de contexto dos POPs:\n{contexto_str}\n\n"
        f"Pergunta do colaborador: {pergunta}"
    )
    return prompt_usuario

# ========================= HISTÓRICO DE CONVERSA =========================
def _get_conversation_history() -> list[dict]:
    """Recupera últimas N trocas do session_state para contexto conversacional."""
    history = _state_get("chat_history", [])
    if not history:
        return []
    # Retorna últimas HISTORY_TURNS trocas (user + assistant)
    recent = history[-(HISTORY_TURNS * 2):]
    return recent

def _append_to_history(role: str, content: str):
    """Adiciona mensagem ao histórico."""
    history = _state_get("chat_history", [])
    history.append({"role": role, "content": content})
    # Mantém no máximo 20 mensagens para não estourar memória
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
        linhas.append("Auditoria da base de conhecimento (v2)")
        linhas.append(f"FOLDER_ID: {FOLDER_ID}")
        linhas.append(f"CACHE_BUSTER: {CACHE_BUSTER}")
        linhas.append(f"Embedding model: sentence-transformers/all-MiniLM-L6-v2")
        linhas.append(f"RELEVANCE_THRESHOLD: {RELEVANCE_THRESHOLD}")
        linhas.append(f"TOP_N_ANN: {TOP_N_ANN} | TOP_K: {TOP_K}")
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

        # Contagem por documento
        contagem_por_documento = {}
        for b in blocks_raw:
            nome = b.get("pagina", "?")
            contagem_por_documento[nome] = contagem_por_documento.get(nome, 0) + 1

        linhas.append("")
        linhas.append(f"Documentos presentes nos blocos: {len(contagem_por_documento)}")
        for nome in sorted(contagem_por_documento):
            linhas.append(f"  -> {nome} ({contagem_por_documento[nome]} blocos)")

        # Contagem de metadados
        dept_counts = {}
        code_counts = {}
        for b in blocks_raw:
            dept = b.get("department") or "(sem departamento)"
            dept_counts[dept] = dept_counts.get(dept, 0) + 1
            for c in b.get("pop_codes", []):
                code_counts[c] = code_counts.get(c, 0) + 1

        linhas.append("")
        linhas.append("Metadados — Departamentos detectados:")
        for dept in sorted(dept_counts):
            linhas.append(f"  {dept}: {dept_counts[dept]} blocos")

        linhas.append("")
        linhas.append("Metadados — Códigos POP detectados:")
        for code in sorted(code_counts):
            linhas.append(f"  {code}: {code_counts[code]} blocos")

        linhas.append("")
        linhas.append("Previa da signature:")
        linhas.append(signature[:1200] + ("..." if len(signature) > 1200 else ""))

        return "\n".join(linhas)

    except Exception as e:
        return f"Erro ao auditar base: {e}"

def _is_negative_feedback(text: str) -> bool:
    """Detecta se o usuário está dizendo que a resposta anterior está errada
    ou insistindo que o documento existe."""
    t = _strip_accents((text or "").lower().strip())
    markers = [
        "incorret", "errad", "nao era isso", "não era isso",
        "resposta errad", "resposta incorret", "documento errad",
        "link errad", "nao e isso", "não é isso", "tá errad", "ta errad",
        "wrong", "nao esta certo", "não está certo",
        # Meta-feedback: usuário insiste que o documento existe
        "tem o documento", "tem na base", "tem na memoria", "tem na memória",
        "voce tem esse", "você tem esse", "ja respondi isso", "já respondi isso",
        "mas existe", "mas tem", "documento existe",
        "tenta de novo", "tente novamente", "busca de novo", "busque de novo",
    ]
    return any(m in t for m in markers)

# ========================= PRINCIPAL =========================
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY,
                        model_id: str = MODEL_ID, history: list[dict] = None):
    """
    Responde a pergunta usando RAG.

    Args:
        pergunta: texto da pergunta
        top_k: número de blocos no contexto
        api_key: chave da API
        model_id: modelo a usar
        history: lista de mensagens [{"role": "user"/"assistant", "content": "..."}]
                 Se None, tenta buscar do session_state.
    """
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

        # --- Detecção de feedback negativo ---
        # Se o usuário diz "incorreta/errada", exclui o documento da resposta anterior
        # e rebusca usando a pergunta original que gerou o erro.
        exclude_file_ids = set()
        effective_query = pergunta

        if _is_negative_feedback(pergunta):
            # Recupera último file_id linkado para excluí-lo
            last_linked = _state_get("last_linked_file_id")
            last_query = _state_get("last_query")
            if last_linked:
                exclude_file_ids.add(last_linked)
            if last_query:
                effective_query = last_query  # Rebusca a pergunta original
            print(f"[DEBUG QD-BOT] Feedback negativo: excluindo file_id={last_linked}, re-query='{effective_query}'")

        candidates = ann_search(effective_query, top_n=TOP_N_ANN, tipo_contratacao=tipo_contratacao)

        # Filtra documentos excluídos (feedback negativo)
        if exclude_file_ids:
            candidates = [c for c in candidates if c["block"].get("file_id") not in exclude_file_ids]

        # --- Threshold de relevância ---
        if not candidates or candidates[0]["raw_score"] < RELEVANCE_THRESHOLD:
            print(f"[DEBUG QD-BOT] Abaixo do threshold ({candidates[0]['raw_score']:.3f} < {RELEVANCE_THRESHOLD})" if candidates else "[DEBUG QD-BOT] Sem candidatos")
            resp = gerar_resposta_fallback_interativa(pergunta, api_key, model_id)
            _append_to_history("user", pergunta)
            _append_to_history("assistant", resp)
            return resp

        reranked = candidates[:top_k]
        blocos_relevantes = [r["block"] for r in reranked]

        t_rag = time.perf_counter()

        prompt = montar_prompt_rag(effective_query, blocos_relevantes, tipo_contratacao=tipo_contratacao)

        # Monta mensagens com histórico
        messages = [{"role": "system", "content": SYSTEM_PROMPT_RAG}]

        # Adiciona histórico conversacional
        conv_history = history if history is not None else _get_conversation_history()
        if conv_history:
            messages.extend(conv_history)

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
                timeout=REQUEST_TIMEOUT,
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

        # Adiciona link do documento
        linked_file_id = None
        if blocos_relevantes and not _is_off_domain_reply(resposta):
            bloco_link = _escolher_bloco_para_link(effective_query, resposta, blocos_relevantes)
            if bloco_link:
                doc_id = bloco_link.get("file_id")
                raw_nome = bloco_link.get("pagina", "?")
                doc_nome = sanitize_doc_name(raw_nome)
                if doc_id:
                    link = f"https://drive.google.com/file/d/{doc_id}/view?usp=sharing"
                    resposta += f"\n\nDocumento relacionado: {doc_nome}\n{link}"
                    linked_file_id = doc_id

        # Salva estado para mecanismo de feedback negativo
        _state_set("last_linked_file_id", linked_file_id)
        _state_set("last_query", effective_query)

        # Salva no histórico
        _append_to_history("user", pergunta)
        _append_to_history("assistant", resposta)

        t_end = time.perf_counter()
        best_score = candidates[0]["raw_score"] if candidates else 0
        print(f"[DEBUG QD-BOT] RAG: {t_rag - t0:.2f}s | Total: {t_end - t0:.2f}s | Best score: {best_score:.3f}")

        return resposta

    except Exception as e:
        return f"Erro interno: {e}"

# ========================= CLI =========================
if __name__ == "__main__":
    print("\nDigite sua pergunta (ou 'sair'):\n")
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
        # Mantém últimas N trocas no CLI também
        if len(cli_history) > HISTORY_TURNS * 2:
            cli_history = cli_history[-(HISTORY_TURNS * 2):]