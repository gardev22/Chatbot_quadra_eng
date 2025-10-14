import os
import re
import time
import json
import numpy as np
import requests
import streamlit as st

# ========= CONFIG =========
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o-mini"
TOP_K = 4
TOP_N_ANN = 60
MAX_TOKENS = 350
TEMPERATURE = 0.15
REQUEST_TIMEOUT = 30

CACHE_BUSTER = "2025-10-14-01"

# ========= MENSAGEM PADRÃO =========
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

# ========= UTIL =========
def sanitize_doc_name(name: str) -> str:
    name = re.sub(r"^(C[oó]pia de|Copy of)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\.(docx?|pdf|txt)$", "", name, flags=re.IGNORECASE)
    return name.strip()

# ========= MODELOS =========
@st.cache_resource(show_spinner=False)
def get_sbert_model(_v=CACHE_BUSTER):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

@st.cache_resource(show_spinner=False)
def get_cross_encoder(_v=CACHE_BUSTER):
    import torch
    from sentence_transformers import CrossEncoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)

# ========= BLOCO CACHEADO =========
@st.cache_resource(show_spinner=False)
def load_blocks_from_cache(_v=CACHE_BUSTER):
    """Lê os blocos processados de blocks_cache.json."""
    path = os.path.join("bot", "blocks_cache.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    blocks = data.get("blocks", [])
    emb = np.array(data.get("embeddings", []), dtype=np.float32)
    return {"blocks": blocks, "emb": emb}

# ========= VETORIAL (ANN) =========
def ann_search(query_text: str, top_n: int):
    vecdb = load_blocks_from_cache()
    blocks = vecdb["blocks"]
    emb = vecdb["emb"]
    if not blocks or emb.size == 0:
        return []

    sbert = get_sbert_model()
    q = sbert.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    scores = emb @ q
    idxs = np.argsort(-scores)[:top_n]
    candidates = [{"idx": int(i), "score": float(scores[i]), "block": blocks[i]} for i in idxs]
    return candidates

# ========= RERANKING =========
def crossencoder_rerank(query: str, candidates, top_k: int):
    if not candidates:
        return []
    ce = get_cross_encoder()
    pairs = [(query, c["block"]["texto"]) for c in candidates]
    scores = ce.predict(pairs, batch_size=64)
    ranked = [{"block": c["block"], "score": float(s)} for c, s in zip(candidates, scores)]
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]

# ========= ETAPA SEGUINTE =========
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
        "2. Se a resposta não estiver escrita de forma explícita, mas puder ser deduzida a partir dos documentos, apresente a dedução de forma clara. Se atente a sinônimos para não dizer que não há resposta de forma equivocada.\n"
        f"3. Se realmente não houver nenhuma evidência, diga exatamente:\n{FALLBACK_MSG}\n"
        "4. Estruture a resposta em tópicos ou frases completas, e cite trechos relevantes totalmente em maiúsculo sempre que possível.\n\n"
        f"{contexto}\n"
        f"Pergunta: {pergunta}\n\n"
        "➡️ Resposta:"
    )

# ========= PRINCIPAL =========
def responder_pergunta(pergunta, top_k: int = TOP_K, api_key: str = API_KEY, model_id: str = MODEL_ID):
    try:
        pergunta = (pergunta or "").strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        vecdb = load_blocks_from_cache()
        blocos_raw = vecdb["blocks"]

        seq = responder_etapa_seguinte(pergunta, blocos_raw)
        if seq:
            return seq

        candidates = ann_search(pergunta, top_n=TOP_N_ANN)
        if not candidates:
            return FALLBACK_MSG

        reranked = crossencoder_rerank(pergunta, candidates, top_k=top_k)
        best_score = reranked[0]["score"] if reranked else 0.0
        if best_score < CE_SCORE_THRESHOLD:
            return FALLBACK_MSG

        blocos_relevantes = [r["block"] for r in reranked]
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Você é um assistente que responde com base somente no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE
        }

        resp = session.post("https://api.openai.com/v1/chat/completions", json=payload, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            return f"❌ Erro na API: {resp.status_code} - {resp.text}"

        data = resp.json()
        escolhas = data.get("choices", [])
        if not escolhas or "message" not in escolhas[0]:
            return "⚠️ A resposta da API veio vazia ou incompleta."

        resposta = escolhas[0]["message"]["content"]

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
