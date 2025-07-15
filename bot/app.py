import streamlit as st
import base64
from pathlib import Path
from datetime import datetime
from openai_backend import responder_pergunta

# --- 1) Carrega logo Quadra em Base64 ---
@st.cache_data
def load_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()

ROOT      = Path.cwd()
LOGO_PATH = ROOT / "data" / "logo_quadra.png"
if not LOGO_PATH.exists():
    st.error(f"Logo não encontrado em:\n{LOGO_PATH}")
    st.stop()
LOGO_B64 = load_base64(LOGO_PATH)

# --- 2) Config página ---
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- 3) Estado de autenticação ---
if "user" not in st.session_state:
    st.session_state.user = None

# --- 4) Se não logado, exibe apenas o card de login ---
if st.session_state.user is None:
    st.markdown(f"""
    <style>
      /* Aqui entra TODO o CSS que você já tinha para .login-wrapper / .login-card */
      #MainMenu, header, footer {{ visibility: hidden; }}
      /* ... */
    </style>

    <div class="login-wrapper">
      <div class="login-card">
        <h1>Quadra Engenharia</h1>
        <p class="subtitle">Faça login para acessar nosso assistente virtual</p>
        <p class="description">
          Entre com sua conta Google para começar a conversar com nosso assistente
        </p>
        <button class="login-btn" onclick="
          (function() {{
            const url = new URL(window.location);
            url.searchParams.set('_login_event','1');
            window.location.href = url;
          }})();
        ">
          <!-- seu SVG do Google -->
          Entrar com Google
        </button>
        <p class="terms">
          Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade
        </p>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # --- JS -> Python: detecta o click via query param e faz login ---
    params = st.experimental_get_query_params()
    if params.get("_login_event") is not None:
        # Simula o login (substitua por OAuth real se quiser)
        st.session_state.user = {
            "name":  "Usuário Demo",
            "email": "demo@quadra.com"
        }
        # Limpa o parâmetro para não ficar em loop
        st.experimental_set_query_params()
        st.experimental_rerun()

    st.stop()

# --- 5) Se estiver logado, mostra o chat inteiro ---
user = st.session_state.user

# (opcional) sidebar com info + botão de sair
with st.sidebar:
    st.markdown(f"👤 **{user['name']}**  \n{user['email']}")
    if st.button("🔄 Sair"):
        st.session_state.user = None
        st.experimental_rerun()

# --- 6) Aqui vai o seu CSS/HTML fiel ao Lovable para o chat! ---
st.markdown(f"""
<style>
  /* copia todo o CSS que você já tinha para header, chat-box, bolhas, input... */
  .stApp {{ background: linear-gradient(to bottom right, #EFF6FF, #BFDBFE); }}
  /* ... */
</style>

<!-- HEADER -->
<div class="chat-header">
  <div class="inner">
    <div class="logo">
      <img src="data:image/png;base64,{LOGO_B64}" alt="Quadra Engenharia"/>
      <div class="texts">
        <h1>Quadra Engenharia</h1>
        <p>Assistente Virtual</p>
      </div>
    </div>
    <div class="user-info">
      <div class="name-email">
        <p>{user['name']}</p>
        <p>{user['email']}</p>
      </div>
      <div class="avatar">{user['name'][0].upper()}</div>
      <button onclick="window.location.reload()">↩️</button>
    </div>
  </div>
</div>

<!-- CHAT BOX -->
<div class="chat-container">
  <div class="chat-box">
""", unsafe_allow_html=True)

# --- 7) Histórico e Input via st.chat_... (ou via seu HTML) ---
if "historico" not in st.session_state:
    st.session_state.historico = []

# Splash inicial
if not st.session_state.historico:
    st.info("✨ Comece uma conversa…")

# Renderiza histórico
for pergunta, resposta in st.session_state.historico:
    st.chat_message("user").markdown(pergunta)
    st.chat_message("assistant").markdown(resposta)

# Campo de input
pergunta = st.chat_input("Digite sua mensagem…")
if pergunta:
    resposta = responder_pergunta(pergunta)
    st.session_state.historico.append((pergunta, resposta))
    st.experimental_rerun()

# Fecha o container se você estiver usando HTML puro
st.markdown("""
  </div>
</div>
""", unsafe_allow_html=True)
