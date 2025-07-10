import streamlit as st
import base64
import pandas as pd
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from openai_backend import responder_pergunta
import requests

# === CONFIGURAÇÕES FIXAS ===

LOGO_PATH = "data/logo_quadra.png"
EMOJI_PATH = "data/emoji_bot.png"


# === FUNÇÃO PARA CARREGAR IMAGENS ===
def carregar_imagem(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo = carregar_imagem(LOGO_PATH)
emoji = carregar_imagem(EMOJI_PATH)

# === CONFIGURAÇÃO DA PÁGINA ===
st.set_page_config(page_title="Chatbot Quadra", layout="wide")

if "historico" not in st.session_state:
    st.session_state.historico = []

# === CABEÇALHO CENTRAL ===
st.markdown(f"""
    <div style='text-align: center;'>
        <img src='data:image/png;base64,{logo}' style='width: 150px; margin-bottom: 10px;'>
        <h2 style='font-size: 2rem; font-weight: 600;'>
            <img src='data:image/png;base64,{emoji}' style='width: 44px; vertical-align: middle; margin-right: 8px;'>
            Bem-vindo ao CHATBOT da QUADRA ENGENHARIA
        </h2>
    </div>
""", unsafe_allow_html=True)

# === EXIBIR HISTÓRICO DE MENSAGENS ===
for pergunta, resposta in st.session_state.historico:
    st.chat_message("user").markdown(pergunta)
    st.chat_message("assistant").markdown(resposta)


# === ESTILO DO INPUT CHAT ===

st.markdown("""
<style>
  /* === 1) Wrapper externo: contorno azul + fundo escuro === */
  div[data-testid="stChatInput"] > div {
    border: 2px solid #1E90FF !important;
    border-radius: 12px !important;
    background-color: #1e1e1e !important;
    display: flex !important;
    align-items: center !important;
    padding: 0 16px !important;   /* padding só nas laterais */
    height: 56px !important;      /* controle aqui a altura total */
    box-sizing: border-box !important;
  }

  /* === 2) Zera qualquer fundo ou sombra nas camadas abaixo === */
  div[data-testid="stChatInput"] > div > div,
  div[data-testid="stChatInput"] > div > div * {
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
  }

  /* === 3) Textarea puro, ocupa tudo e centraliza texto === */
  div[data-testid="stChatInput"] textarea {
    flex: 1 1 auto !important;
    background: transparent !important;
    border: none !important;
    outline: none !important;
    color: #fff !important;
    font-size: 16px !important;
    line-height: 1.5 !important;
    padding: 0 !important;
    margin: 0 !important;
    height: auto !important;
    resize: none !important;
  }

  /* === 4) Placeholder suavizado === */
  div[data-testid="stChatInput"] textarea::placeholder {
    color: #777 !important;
  }

  /* === 5) Espaço entre o textarea e o botão === */
  div[data-testid="stChatInput"] button {
    margin-left: 12px !important;
  }

  /* === 6) Garante que foco não gere sombra extra === */
  div[data-testid="stChatInput"] > div:focus-within {
    box-shadow: none !important;
  }
</style>
""", unsafe_allow_html=True)

# === INPUT DO USUÁRIO ===
pergunta = st.chat_input("Digite sua pergunta")
if pergunta:
    resposta = responder_pergunta(pergunta)
    st.session_state.historico.append((pergunta, resposta))
    st.rerun()

# === SIDEBAR COM HISTÓRICO ===
st.sidebar.markdown("## 📄 Histórico de Sessão")
if st.session_state.historico:
    for i, (p, _) in enumerate(reversed(st.session_state.historico)):
        st.sidebar.markdown(f"{len(st.session_state.historico) - i}. **{p}**")
else:
    st.sidebar.markdown(
        "<span style='color: #ccc; font-style: normal;'>Nenhuma pergunta feita ainda.</span>",
        unsafe_allow_html=True
    )

