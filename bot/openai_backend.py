import os
import re
import pandas as pd
import requests
import streamlit as st
from sentence_transformers import CrossEncoder


# === CONFIGURAÇÕES ===
API_KEY = st.secrets["openai"]["api_key"]
MODEL_ID = "gpt-4o"
CSV_PATH = "data/tabela_planejamento_comercial.csv"
TOP_K = 8

# === 1. Carregamento Universal de Blocos (CSV, TXT ou XLSX) ===
def carregar_blocos_universal(path):
    import warnings
    ext = os.path.splitext(path)[-1].lower()

    for encoding in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
        try:
            if ext == ".xlsx":
                df = pd.read_excel(path, header=0)
            elif ext == ".txt":
                df = pd.read_csv(path, header=None, sep="\n", engine="python", encoding=encoding, encoding_errors="replace")
            else:  # CSV
                try:
                    # tenta com header conhecido (caso seja bem estruturado)
                    df = pd.read_csv(path, header=0, sep=",", encoding=encoding, encoding_errors="replace")
                except Exception:
                    # tenta como vertical (uma coluna só, sem header)
                    df = pd.read_csv(path, header=None, sep=None, engine="python", encoding=encoding, encoding_errors="replace")
            break
        except Exception as e:
            warnings.warn(f"Tentativa com encoding {encoding} falhou: {e}")
            continue
    else:
        raise ValueError("❌ Não foi possível abrir o arquivo com codificações comuns.")

    # === Detecta estrutura ===
    if df.shape[1] == 1:
        linhas = df.iloc[:, 0].fillna("").astype(str)
        blocos, bloco_atual = [], []
        for linha in linhas:
            if re.match(r"^\\s*\\d+\\s*$", linha):
                if bloco_atual:
                    blocos.append(bloco_atual)
                    bloco_atual = []
            elif linha.strip():
                bloco_atual.append(linha.strip())
        if bloco_atual:
            blocos.append(bloco_atual)
        return [{"pagina": f"Etapa {i+1}", "texto": "\n".join(bloco)} for i, bloco in enumerate(blocos)]

    colunas_baixa = [c.strip().lower() for c in df.columns]
    if "texto" in colunas_baixa:
        col_pagina = next((c for c in df.columns if "pagina" in c.lower()), "?")
        col_texto = next((c for c in df.columns if "texto" in c.lower()), None)
        df["texto"] = df[col_texto].fillna("").astype(str)
        df["pagina"] = df.get(col_pagina, "?")
        return df[["pagina", "texto"]].to_dict(orient="records")

    df = df.fillna("")
    blocos = []
    for i, row in df.iterrows():
        texto = "\n".join([f"{col}: {str(row[col]).strip()}" for col in df.columns if str(row[col]).strip()])
        if texto:
            blocos.append({"pagina": f"Linha {i+1}", "texto": texto})
    return blocos


# === 2. Agrupa blocos em janelas deslizantes ===
def agrupar_blocos(blocos, janela=3):
    blocos_agrupados = []
    for i in range(len(blocos)):
        grupo = blocos[i:i+janela]
        texto_agregado = " ".join([b["texto"] for b in grupo])
        pagina = grupo[0].get("pagina", "?")
        blocos_agrupados.append({"pagina": pagina, "texto": texto_agregado})
    return blocos_agrupados

# === 3. Inicializa reranker ===
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# === 4. Prepara os blocos ===
blocos_raw = carregar_blocos_universal(CSV_PATH)
blocos_contexto = agrupar_blocos(blocos_raw, janela=3)

# === 5. Reranking semântico ===
def consultar_com_reranking(pergunta, top_k=TOP_K):
    pergunta = pergunta.strip().replace("\n", " ")
    pares = [(pergunta, bloco["texto"]) for bloco in blocos_contexto if bloco["texto"].strip()]
    scores = reranker.predict(pares)
    blocos_filtrados = [b for b in blocos_contexto if b["texto"].strip()]
    resultados = sorted(zip(blocos_filtrados, scores), key=lambda x: x[1], reverse=True)[:top_k]
    return [r[0] for r in resultados]

# === 6. Pergunta de ordem/sequência ===
def responder_etapa_seguinte(pergunta, blocos):
    if not any(x in pergunta.lower() for x in ["após", "depois de", "seguinte a"]):
        return None

    trecho = pergunta.lower().split("após")[-1].strip()
    trecho = trecho.split("depois de")[-1].strip() if "depois de" in pergunta.lower() else trecho
    trecho = trecho.split("seguinte a")[-1].strip() if "seguinte a" in pergunta.lower() else trecho

    for i, bloco in enumerate(blocos):
        if trecho.lower() in bloco["texto"].lower():
            if i + 1 < len(blocos):
                return f"A etapa após \"{trecho}\" é \"{blocos[i+1]['texto'].splitlines()[0]}\"."
            else:
                return f"A etapa \"{trecho}\" é a última registrada."
    return "Essa etapa não foi encontrada no conteúdo."

# === 7. Monta o prompt ===
def montar_prompt_rag(pergunta, blocos):
    contexto = "\n\n".join([f"[Página {b.get('pagina', '?')}]:\n{b['texto']}" for b in blocos])
    return (
        f"{contexto}\n\n"
        f"Com base apenas nas informações acima, responda à pergunta:\n{pergunta}\n"
        f"Se a resposta não estiver clara no conteúdo, diga: 'Essa informação não está disponível no conteúdo fornecido.'"
    )

# === 8. Requisição ao modelo ===
def responder_pergunta(pergunta, blocos=blocos_contexto, api_key=API_KEY, model_id=MODEL_ID, top_k=TOP_K):
    try:
        pergunta = pergunta.strip().replace("\n", " ").replace("\r", " ")
        if not pergunta:
            return "⚠️ Pergunta vazia."

        resposta_seq = responder_etapa_seguinte(pergunta, blocos_raw)
        if resposta_seq:
            return resposta_seq

        blocos_relevantes = consultar_com_reranking(pergunta, top_k)
        prompt = montar_prompt_rag(pergunta, blocos_relevantes)

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Você é um assistente que responde com base somente no conteúdo fornecido."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.2
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.ok:
            resultado = response.json()
            escolhas = resultado.get("choices", [])
            if escolhas and "message" in escolhas[0]:
                return escolhas[0]["message"]["content"]
            else:
                return "⚠️ A resposta da API veio vazia ou incompleta."
        else:
            return f"❌ Erro na chamada à API: {response.status_code} - {response.text}"

    except Exception as e:
        return f"❌ Erro interno: {e}"

# === 9. Teste manual (opcional) ===
if __name__ == "__main__":
    print("\nDigite sua pergunta com base no conteúdo. Digite 'sair' para encerrar.\n")
    while True:
        pergunta = input("Pergunta: ").strip()
        if pergunta.lower() in ["sair", "exit", "quit"]:
            print("\nEncerrando...")
            break
        elif not pergunta or len(pergunta) < 3:
            print("⚠️ Pergunta muito curta.")
            continue

        resposta = responder_pergunta(pergunta)
        print("\nResposta:\n", resposta, "\n")
