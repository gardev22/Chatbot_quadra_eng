import streamlit as st
import base64
from openai_backend import responder_pergunta
import pandas as pd

# === CONFIGURAÇÃO DA PÁGINA ===
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# === ESCONDE MENU, FOOTER E SIDEBAR PADRÃO ===
st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden;}
[data-testid="stSidebar"] {display: none;}
</style>
""", unsafe_allow_html=True)

# === CARREGA IMAGENS ===
@st.cache(allow_output_mutation=True)
def carrega_img(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

LOGO = carrega_img("data/logo_quadra.png")
EMOJI = carrega_img("data/emoji_bot.png")

# === TOPO TIPO “APP BAR” ===
st.markdown(f"""
<div style="
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 30px;
    background: var(--bg-color);
    box-shadow: 0 1px 4px rgba(0,0,0,0.1);
">
  <div style="display:flex; align-items:center;">
    <img src="data:image/png;base64,{LOGO}" style="height:36px; margin-right:12px;" />
    <div>
      <div style="font-size:1.25rem; font-weight:600; color:var(--text-color);">
        Chatbot da Quadra Engenharia
      </div>
      <div style="font-size:0.9rem; color:var(--secondary-text-color);">
        Assistente Inteligente
      </div>
    </div>
  </div>
  <div style="display:flex; align-items:center;">
    <button style="all:unset; cursor:pointer; font-size:1.2rem; margin-right:20px;">⚙️</button>
    <div style="
      width:32px; height:32px; border-radius:50%;
      background: var(--sidebar-background-color);
      display:flex; align-items:center; justify-content:center;
      font-weight:600; color:var(--text-color); margin-right:20px;
    ">U</div>
    <button style="all:unset; cursor:pointer; font-size:1.2rem;">⏻</button>
  </div>
</div>
""", unsafe_allow_html=True)

# === HISTÓRICO DE MENSAGENS ===
if "historico" not in st.session_state:
    st.session_state.historico = []

# splash de boas-vindas
if not st.session_state.historico:
    st.markdown(f"""
    <div style="
      max-width:800px;
      margin:60px auto 30px;
      background: var(--secondary-background-color);
      border-radius:12px;
      padding:30px;
      text-align:center;
    ">
      <img src="data:image/png;base64,{EMOJI}" style="height:36px; margin-bottom:12px;" />
      <div style="font-size:1.1rem; font-weight:500; margin-bottom:4px; color:var(--text-color);">
        Comece uma conversa
      </div>
      <div style="color:var(--secondary-text-color);">
        Digite sua mensagem abaixo para começar a interagir com o assistente
      </div>
    </div>
    """, unsafe_allow_html=True)

for pergunta, resposta in st.session_state.historico:
    st.chat_message("user").markdown(pergunta)
    st.chat_message("assistant").markdown(resposta)

# === ESTILO DO INPUT (SEM FORÇAR CORES, HERDA DO TEMA) ===
st.markdown("""
<style>
/* apenas shape, margem e padding — cores vêm do tema do Streamlit */
div[data-testid="stChatInput"] > div {
  max-width: 800px;
  margin: 20px auto 40px;
  border-radius: 30px !important;
  padding: 8px 16px !important;
}

/* ajusta tamanho de fonte e espaçamento do botão */
div[data-testid="stChatInput"] textarea {
  font-size: 16px !important;
}
div[data-testid="stChatInput"] button {
  margin-left: 12px !important;
}
</style>
""", unsafe_allow_html=True)

# === CAMPO DE INPUT ===
pergunta = st.chat_input("Digite sua mensagem…")
if pergunta:
    resposta = responder_pergunta(pergunta)
    st.session_state.historico.append((pergunta, resposta))
