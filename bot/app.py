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
  /* Remove sombra e borda globais */
  section:has(input) * {
    box-shadow: none !important;
    border: none !important;
  }

  /* Estilização do input */
  input[type="text"].st-bd {
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
  input[type="text"].st-bd:focus {
    border: 2px solid #1E90FF !important;
  }

  /* Esconde hints/labels que o Streamlit injeta dinamicamente */
  [role="status"], form p, form label {
    display: none !important;
  }

  /* Posiciona o text_input (muda aqui) */
  div[data-testid="stTextInput"] {
    margin-top: 40vh;    /* ajuste vertical */
    margin-bottom: 2vh;  /* ajuste conforme quiser */
  }
</style>

<script>
document.addEventListener('DOMContentLoaded', () => {
  const inp = document.querySelector('input[type="text"].st-bd');
  if (inp) {
    // Desliga autofill/autocorrect/spellcheck
    inp.setAttribute('autocomplete', 'off');
    inp.setAttribute('autocorrect', 'off');
    inp.setAttribute('autocapitalize', 'off');
    inp.setAttribute('spellcheck', 'false');
  }

  // MutationObserver para remover o hint "Press Enter..."
  const observer = new MutationObserver(() => {
    document.querySelectorAll('[role="status"]').forEach(el => {
      if (el.textContent.includes('Press Enter')) {
        el.style.display = 'none';
      }
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
});
</script>
""", unsafe_allow_html=True)



# === Input sem form, dispara no Enter ===
if "submitted" not in st.session_state:
    st.session_state.submitted = False

def on_enter():
    st.session_state.submitted = True

user_input = st.text_input(
    label="",
    placeholder="Digite sua pergunta",
    label_visibility="collapsed",
    key="user_input",
    on_change=on_enter,
    autocomplete="off"
)

if st.session_state.submitted:
    pergunta = st.session_state.user_input
    st.write(f"Você perguntou: **{pergunta}**")
    # reseta para próxima pergunta
    st.session_state.submitted = False
    st.session_state.user_input = ""


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

