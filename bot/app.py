import streamlit as st
import base64
from openai_backend import responder_pergunta

# === 1) Carrega imagem de logo com cache_data ===
@st.cache_data
def load_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

LOGO = load_image("data/logo_quadra.png")

# === 2) Configuração da página e esconder UI nativa ===
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
      #MainMenu, footer, header { visibility: hidden; }
      [data-testid="stSidebar"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# === 3) Header full-width + container centrado ===
st.markdown(
    f"""
    <style>
    .header {{
      width: 100%;
      background-color: var(--color-background);
      border-bottom: 1px solid var(--border-color);
    }}
    .header-content {{
      max-width: 960px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 20px;
    }}
    .header-left {{ display: flex; align-items: center; }}
    .header-left .logo {{ height: 36px; margin-right: 10px; }}
    .header-text .main {{
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--color-primary-text);
      line-height: 1.2;
    }}
    .header-text .sub {{
      font-size: 0.9rem;
      color: var(--color-secondary-text);
    }}
    .header-right {{ display: flex; align-items: center; }}
    .icon-btn {{
      all: unset;
      cursor: pointer;
      font-size: 1.2rem;
      margin-left: 20px;
      color: var(--color-secondary-text);
    }}
    .icon-btn:hover {{ color: var(--color-primary-text); }}
    .avatar {{
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background-color: var(--color-secondary-background);
      display: flex;
      align-items: center;
      justify-content: center;
      margin-left: 20px;
      font-weight: 600;
      color: var(--color-primary-text);
    }}
    </style>

    <div class="header">
      <div class="header-content">
        <div class="header-left">
          <img class="logo" src="data:image/png;base64,{LOGO}" />
          <div class="header-text">
            <div class="main">Chatbot da Quadra Engenharia</div>
            <div class="sub">Assistente Inteligente</div>
          </div>
        </div>
        <div class="header-right">
          <button class="icon-btn" title="Configurações">⚙️</button>
          <div class="avatar">U</div>
          <button class="icon-btn" title="Sair">⮕ Sair</button>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# === 4) Histórico de sessão ===
if "historico" not in st.session_state:
    st.session_state.historico = []

# === 5) Splash “Comece uma conversa” com sparkles ===
st.markdown(
    """
    <style>
    .splash-card {
      max-width: 800px;
      margin: 60px auto 30px;
      padding: 30px;
      background-color: var(--color-background-alt);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      text-align: center;
      box-shadow: none;
    }
    .splash-card .icon {
      font-size: 2rem;
      color: var(--color-primary);
      margin-bottom: 12px;
    }
    .splash-card .title {
      font-size: 1.1rem;
      font-weight: 500;
      color: var(--color-primary-text);
      margin-bottom: 4px;
    }
    .splash-card .subtitle {
      font-size: 0.95rem;
      color: var(--color-secondary-text);
    }
    </style>
    """,
    unsafe_allow_html=True,
)
if not st.session_state.historico:
    st.markdown(
        """
        <div class="splash-card">
          <div class="icon">✨</div>
          <div class="title">Comece uma conversa</div>
          <div class="subtitle">
            Digite sua mensagem abaixo para começar a interagir com o assistente
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# === 6) Exibe histórico como bolhas ===
for pergunta, resposta in st.session_state.historico:
    st.chat_message("user").markdown(pergunta)
    st.chat_message("assistant").markdown(resposta)

# === 7) Estiliza o input como “pill”, herdando tema ===
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
      box-shadow: none !important;
    }
    div[data-testid="stChatInput"] textarea {
      font-size: 16px !important;
      color: var(--color-primary-text) !important;
    }
    div[data-testid="stChatInput"] button {
      margin-left: 12px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# === 8) Campo de input e lógica de envio ===
pergunta = st.chat_input("Digite sua mensagem…")
if pergunta:
    resposta = responder_pergunta(pergunta)
    st.session_state.historico.append((pergunta, resposta))
