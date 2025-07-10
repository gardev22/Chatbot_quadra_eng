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


# === ESTILO FINAL DO CHAT INPUT ===
# === ESTILO DO INPUT CHAT ===
st.markdown("""
    <style>
    /* Remove sombras e bordas do contêiner */
    section:has(input) * {
        box-shadow: none !important;
        border: none !important;
    }

    /* Estilização do input */
    input[type="text"] {
        border: 2px solid transparent !important;
        outline: none !important;
        border-radius: 12px !important;
        padding: 10px !important;
        background-color: #1e1e1e !important;
        color: #fff !important;
        width: 100% !important;
        font-size: 16px !important;
        box-shadow: none !important;
    }

    input[type="text"]:focus {
        border: 2px solid #1E90FF !important;
        box-shadow: none !important;
    }

    /* Remove a mensagem "Press Enter to submit form" */
    .stForm > div > div:nth-child(2) {
        display: none !important;
    }

    /* Esconde o botão "Enviar" */
    .stForm button {
        display: none !important;
    }

    /* Centraliza melhor o input, sem causar rolagem */
    div[data-testid="stForm"] {
        margin-top: 25vh;
        margin-bottom: 2vh;
    }
    </style>
""", unsafe_allow_html=True)

# === INPUT DO USUÁRIO (customizado) ===
with st.form("chat_form", clear_on_submit=True):
    user_input = st.text_input(
        label="", 
        placeholder="Digite sua pergunta", 
        label_visibility="collapsed"
    )
    st.form_submit_button("Enviar")  # será ocultado via CSS



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

