import streamlit as st
import base64
from openai_backend import responder_pergunta

# —————————————————————————————————————————————————————————————
# 1) CACHE ATUALIZADO (sem warning de depreciação)
@st.cache_data
def load_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

LOGO  = load_image("data/logo_quadra.png")
EMOJI = load_image("data/emoji_bot.png")

# —————————————————————————————————————————————————————————————
# 2) CONFIGURAÇÃO DA PÁGINA
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# —————————————————————————————————————————————————————————————
# 3) ESCONDE MENU, FOOTER E SIDEBAR PADRÃO
st.markdown(
    """
    <style>
      #MainMenu, footer, header {visibility: hidden;}
      [data-testid="stSidebar"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True
)

# —————————————————————————————————————————————————————————————
# 4) CSS DO HEADER (“AppBar” igual Lovable)
st.markdown(
    """
    <style>
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 40px;
      background-color: var(--color-background);
      border-bottom: 1px solid var(--border-color);
    }
    .header-title {
      display: flex;
      align-items: center;
    }
    .header-title img {
      height: 36px;
      margin-right: 12px;
    }
    .header-title .text .main {
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--color-primary-text);
      line-height: 1.2;
    }
    .header-title .text .sub {
      font-size: 0.9rem;
      color: var(--color-secondary-text);
    }
    .header-actions {
      display: flex;
      align-items: center;
    }
    .header-actions button,
    .header-actions .avatar {
      all: unset;
      cursor: pointer;
      font-size: 1.2rem;
      margin-left: 20px;
    }
    .header-actions .avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background-color: var(--color-secondary-background);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      color: var(--color-primary-text);
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(f"""
<div class="header">
  <div class="header-title">
    <img src="data:image/png;base64,{LOGO}" />
    <div class="text">
      <div class="main">Chatbot da Quadra Engenharia</div>
      <div class="sub">Assistente Inteligente</div>
    </div>
  </div>
  <div class="header-actions">
    <button title="Configurações">⚙️</button>
    <div class="avatar">U</div>
    <button title="Sair">⏻</button>
  </div>
</div>
""", unsafe_allow_html=True)

# —————————————————————————————————————————————————————————————
# 5) INICIALIZAÇÃO DO HISTÓRICO
if "historico" not in st.session_state:
    st.session_state.historico = []

# —————————————————————————————————————————————————————————————
# 6) SPLASH “COMECE UMA CONVERSA” (card amplo, com sombra leve)
if not st.session_state.historico:
    st.markdown(f"""
    <div style="
      max-width: 800px;
      margin: 60px auto;
      padding: 30px;
      background-color: var(--color-background-alt);
      border-radius: 12px;
      text-align: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    ">
      <img src="data:image/png;base64,{EMOJI}" style="height:36px; margin-bottom:12px;" />
      <div style="font-size:1.1rem; font-weight:500; color: var(--color-primary-text); margin-bottom:4px;">
        Comece uma conversa
      </div>
      <div style="color: var(--color-secondary-text);">
        Digite sua mensagem abaixo para começar a interagir com o assistente
      </div>
    </div>
    """, unsafe_allow_html=True)

# —————————————————————————————————————————————————————————————
# 7) EXIBE HISTÓRICO COMO BOLHAS NATIVAS
for pergunta, resposta in st.session_state.historico:
    st.chat_message("user").markdown(pergunta)
    st.chat_message("assistant").markdown(resposta)

# —————————————————————————————————————————————————————————————
# 8) CSS DO INPUT (pill gigante, herdando cores do tema)
st.markdown(
    """
    <style>
    div[data-testid="stChatInput"] > div {
      max-width: 800px;
      margin: 20px auto 40px;
      background-color: var(--color-background);
      border: 1px solid var(--border-color);
      border-radius: 30px;
      padding: 8px 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    div[data-testid="stChatInput"] textarea {
      color: var(--color-primary-text) !important;
      font-size: 16px !important;
    }
    div[data-testid="stChatInput"] button {
      margin-left: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# —————————————————————————————————————————————————————————————
# 9) CAMPO DE INPUT E LÓGICA DE ENVIO
pergunta = st.chat_input("Digite sua mensagem…")
if pergunta:
    resposta = responder_pergunta(pergunta)
    st.session_state.historico.append((pergunta, resposta))
