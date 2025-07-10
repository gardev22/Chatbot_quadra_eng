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

st.markdown("""
<style>
  /* ========================
     Estilo do input
     ======================== */
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
  }

  /* ========================
     Esconde tudo no form 
     exceto o input
     ======================== */
  form > *:not(input) {
    display: none !important;
  }

  /* ========================
     Força form sem autocomplete
     ======================== */
  form {
    autocomplete: off !important;
  }

  /* ========================
     Garante que o botão continue escondido
     ======================== */
  .stForm button {
    display: none !important;
  }

  /* ========================
     Posicionamento
     ======================== */
  div[data-testid="stForm"] {
    margin-top: 40vh;
    margin-bottom: 2vh;
  }
</style>

<script>
window.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('form');
  if (!form) return;

  // burlar autofill
  form.setAttribute('autocomplete', 'off');
  const inp = form.querySelector('input[type="text"]');
  if (inp) {
    // nome randomizado para não casar com histórico do navegador
    inp.setAttribute('name', 'inp-'+Date.now());
    inp.setAttribute('autocomplete', 'new-password');
    inp.setAttribute('autocorrect', 'off');
    inp.setAttribute('spellcheck', 'false');
  }

  // ocultar qualquer hint contendo "Press Enter"
  form.querySelectorAll('*').forEach(el => {
    if (el.textContent.includes('Press Enter')) {
      el.style.display = 'none';
    }
  });
});
</script>
""", unsafe_allow_html=True)

# === INPUT DO USUÁRIO ===

with st.form("chat_form", clear_on_submit=True):
    user_input = st.text_input(
        label="",
        placeholder="Digite sua pergunta",
        label_visibility="collapsed",
        # se sua versão de Streamlit suportar, garanta:
        autocomplete="off",
    )
    st.form_submit_button("Enviar")  # já escondido pelo CSS


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

