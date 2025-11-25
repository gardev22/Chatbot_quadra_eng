# openai_backend.py — RAG conversacional detalhado + link do POP correto

import os
import io
import re
import json
import time
import unicodedata
import numpy as np
import requests
import streamlit as st
from docx import Document
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ========= CONFIG BÁSICA =========
API_KEY = st.secrets["openai"]["api_key"]
# Ajuste aqui se quiser outro modelo (ex.: "gpt-4.1" ou "gpt-4.1-mini")
MODEL_ID = "gpt-4o"

# ========= PERFORMANCE & QUALIDADE =========
USE_JSONL = True
USE_CE = False  # CrossEncoder desativado para manter leve/rápido

TOP_N_ANN = 12   # candidatos na ANN
TOP_K = 5        # blocos que vão para o contexto

MAX_WORDS_PER_BLOCK = 180
GROUP_WINDOW = 2

# espaço para respostas ricas, estilo POP detalhado
MAX_TOKENS = 750
REQUEST_TIMEOUT = 20
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
- Estruture a resposta de forma parecida com um manual interno bem escrito, por exemplo:

  • Comece com um parágrafo inicial explicando de forma geral:
    - do que trata o processo;
    - em qual categoria ele se encaixa (ex.: material de expediente, benefício, controle de pessoal);
    - qual é o departamento responsável.

  • Depois, use seções numeradas quando houver cenários diferentes, por exemplo:
    1. Na Sede da Empresa (Escritório)
    2. Em Obras
    3. Contexto Geral da Compra de Materiais

    Dentro de cada seção, escreva por extenso, em frases completas.
    Você pode usar marcadores com o símbolo “•” ou apenas parágrafos separados.
    Não use linhas iniciadas com hífen simples (“- ”) para listar itens.

    Inclua, sempre que aparecer no contexto:
    - frequência e prazos;
    - responsáveis (gestor, Comprador, Gerente de Compras, Diretor, DP, PP, Almoxarife etc.);
    - formulários e códigos (F.14, F.16, F.17, F.18, F.45, F.101 etc.);
    - etapas do fluxo (solicitação, cotação com 3 fornecedores, análise do mapa de cotações,
      aprovação, emissão do pedido, retirada do material).

  • Conclua com um parágrafo de resumo começando com “Em resumo,” ou equivalente,
    amarrando o que o colaborador precisa fazer no caso específico da pergunta.

- Escreva de forma fluida, por extenso, sem excesso de tópicos telegráficos.
- Não omita detalhes relevantes que estejam nos trechos de contexto apenas para encurtar a resposta.

Regras de conteúdo:
- Use APENAS as informações dos trechos de documentos fornecidos no contexto.
- Quando o contexto trouxer regras gerais (por exemplo, compras de materiais de expediente ou gestão de férias),
  aplique essas regras ao caso específico perguntado (por exemplo, toner, benefício, formulário), mesmo que a palavra exata não apareça.
- Só diga que não há informação quando o contexto realmente não trouxer nada relacionado ao tema.
- Se a pergunta fugir totalmente de procedimentos internos, você NÃO deve tentar responder sobre o assunto externo.
  Nessas situações, responda de forma curta e educada, começando com a frase exata:

  "Meu foco é ajudar com procedimentos operacionais padrão (POPs), políticas e rotinas internas da Quadra Engenharia."

  Depois dessa frase, explique brevemente que não consegue ajudar nesse tema externo e convide o usuário a reformular a dúvida
  com foco nos processos internos da empresa.
"""

# ========= CACHE BUSTER =========
CACHE_BUSTER = "2025-11-25-RAG-GERAL-OFFDOMAIN-01"

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
    """
    Escolhe o bloco mais parecido com a resposta e a pergunta
    para linkar o documento correto.
    """
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


def _expand_query_for_hr(query: str) -> str:
    """
    Expande queries para melhorar match semântico.
    Inclui padrões de RH e de Compras (toner -> material de expediente).
    """
    q_norm = _strip_accents(query.lower())
    extras = []

    # RH
    if "contrat" in q_norm:
        extras.append(
            "contratação de funcionários admissão de colaboradores "
            "processo de admissão contratação de pessoal recrutamento seleção de candidatos"
        )

    if "admiss" in q_norm:
        extras.append(
            "admissão de pessoal contratação de funcionários contratação de colaboradores "
            "processo de admissão recrutamento"
        )

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


def _is_off_domain_reply(text: str) -> bool:
    """
    Detecta se a resposta é do tipo "fora de escopo",
    usando a frase padrão definida no SYSTEM_PROMPT_RAG.
    """
    if not text:
        return False
    t = _strip_accents(text.lower())
    gatilho = _strip_accents(
        "Meu foco é ajudar com procedimentos operacionais padrão (POPs), políticas e rotinas internas da Quadra Engenharia."
    ).lower()
    return gatilho[:60] in t

# ========================= FALLBACK INTERATIVO =========================
def gerar_resposta_fallback_interativa(pergunta: str,
                                       api_key: str = API_KEY,
                                       model_id: str = MODEL_ID) -> str:
    """
    Só usamos esse fallback quando REALMENTE não há nenhum bloco retornado.
    """
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
    """
    Agrupa blocos em janelas pequenas, sem misturar documentos diferentes.
    """
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
def ann_search(query_text: str, top_n: int):
    vecdb = get_vector_index()
    blocks = vecdb["blocks"]
    if not blocks:
        return []

    sbert = get_sbert_model()

    query_for_embed = _expand_query_for_hr(query_text)
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
        adj_score = float(s) + 0.25 * lex  # boost lexical leve
        results.append({
            "idx": i,
            "score": adj_score,
            "block": block,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


# ========================= PROMPT RAG =========================
def montar_prompt_rag(pergunta, blocos):
    """
    Monta o texto que vai na mensagem do usuário:
    - contexto dos POPs
    - instruções para usar esse contexto de forma detalhada
    - pergunta do colaborador
    """
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
        # deixa espaço para o modelo trabalhar, mas evita estourar token demais
        if len(texto) > 3000:
            texto = texto[:3000]
        pagina = b.get("pagina", "?")
        contexto_parts.append(f"[Trecho {i} – {pagina}]\n{texto}")

    contexto_str = "\n\n".join(contexto_parts)

    prompt_usuario = (
        "Abaixo estão trechos de documentos internos e POPs da Quadra Engenharia.\n"
        "Você deve usar ESSES trechos para responder à pergunta sobre processos, políticas ou rotinas internas.\n\n"
        "Instruções para montar a resposta:\n"
        "1. Identifique claramente qual processo está sendo descrito (por exemplo, compra de materiais de expediente,\n"
        "   gestão de férias, controle de pessoal etc.) e deixe isso explícito no primeiro parágrafo.\n"
        "2. Se o contexto trouxer diferenças entre Sede/Escritório e Obras, organize a resposta em seções numeradas,\n"
        "   como por exemplo:\n"
        "   1. Na Sede da Empresa (Escritório)\n"
        "   2. Em Obras\n"
        "   3. Contexto Geral da Compra de Materiais\n"
        "3. Dentro de cada seção, escreva por extenso, em frases completas, sem usar linhas iniciadas com hífen simples (“- ”).\n"
        "   Você pode usar o símbolo “•” ou apenas parágrafos separados para destacar frequência, prazos, responsáveis,\n"
        "   formulários (F.18, F.45 etc.) e etapas do fluxo.\n"
        "4. Quando a pergunta for sobre um item específico (como um tipo de material, um benefício ou um documento),\n"
        "   deixe claro em qual categoria geral ele se enquadra (por exemplo, material de expediente, benefício de alimentação,\n"
        "   documento de admissão) e explique o passo a passo aplicando o procedimento geral ao caso específico.\n"
        "5. Inclua, sempre que estiver presente nos trechos, informações como:\n"
        "   • frequência das solicitações e prazos de atendimento;\n"
        "   • responsáveis em cada etapa (gestor, Comprador, Gerente de Compras, Diretor, DP, PP, Almoxarife etc.);\n"
        "   • formulários e códigos (F.14, F.16, F.17, F.18, F.45, F.101 etc.);\n"
        "   • etapas do fluxo (solicitação, cotação com 3 fornecedores, análise do mapa de cotações, aprovação,\n"
        "     emissão do pedido, retirada do material).\n"
        "6. Finalize com um parágrafo de resumo começando com “Em resumo,” ou frase equivalente, reforçando\n"
        "   o que o colaborador deve fazer na prática.\n\n"
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

        # 1) Busca ANN
        candidates = ann_search(pergunta, top_n=TOP_N_ANN)
        if not candidates:
            # Nenhum bloco em lugar nenhum: aí sim usamos fallback
            return gerar_resposta_fallback_interativa(pergunta, api_key, model_id)

        # 2) Usa os TOP_K blocos, sem thresholds agressivos
        reranked = candidates[:top_k]
        blocos_relevantes = [r["block"] for r in reranked]

        t_rag = time.perf_counter()

        # 3) Monta prompt
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

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

        # 4) Chamada à API
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

        # 5) Link para o documento mais provável
        #    NÃO anexar link se a resposta for fora de escopo (ex.: pergunta sobre futebol, política etc.)
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
        print(
            f"[DEBUG QD-BOT] RAG: {t_rag - t0:.2f}s | Total responder_pergunta: {t_end - t0:.2f}s"
        )

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
