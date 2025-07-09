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
/* Remove qualquer borda de containers externos do chat_input */
section[data-testid="stChatInput"] div {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}

/* Remove o fieldset padrão */
section[data-testid="stChatInput"] fieldset {
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

/* Remove o título do fieldset */
section[data-testid="stChatInput"] legend {
    display: none !important;
}

/* Estilo do input do usuário */
textarea {
    border: 2px solid transparent !important;
    outline: none !important;
    box-shadow: none !important;
    border-radius: 999px !important;
    padding: 10px 16px !important;
    color: white !important;
    background-color: #1e1e1e !important;
    transition: border 0.2s ease, box-shadow 0.2s ease;
}

/* Ao focar: borda azul e aura */
textarea:focus {
    border: 2px solid #1E90FF !important;
    box-shadow: 0 0 0 3px rgba(30,144,255,0.35) !important;
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

