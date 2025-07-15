import streamlit as st
import base64
from pathlib import Path
from openai_backend import responder_pergunta

# --- 1) Função para carregar PNG em Base64 ---
@st.cache_data
def load_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()

# --- 2) Resolve o caminho do logo em data/logo_quadra.png ---
ROOT      = Path.cwd()
LOGO_PATH = ROOT / "data" / "logo_quadra.png"
if not LOGO_PATH.exists():
    st.error(f"Logo não encontrado em:\n{LOGO_PATH}")
    st.stop()
LOGO_B64 = load_base64(LOGO_PATH)

# --- 3) Configurações da página ---
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- 4) Inicializa usuário e histórico ---
if "user" not in st.session_state:
    st.session_state.user = None
if "historico" not in st.session_state:
    st.session_state.historico = []

# --- 5) Tela de Login ---
if st.session_state.user is None:
    st.markdown(f"""
    <style>
      /* Esconde menu/header/footer */
      #MainMenu, header, footer {{ visibility: hidden; margin:0; padding:0; }}

      /* Fullscreen com gradiente */
      .login-wrapper {{
        position: fixed; inset: 0;
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #000000 100%);
        display: flex; align-items: center; justify-content: center;
      }}

      /* Card de login */
      .login-card {{
        position: relative; width: 360px;
        background: #F8FAFC; border-radius: 12px;
        padding: 48px 24px 24px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        text-align: center;
      }}

      /* Logo circular sobre o card */
      .login-card::before {{
        content: "";
        position: absolute; top: -36px; left: 50%;
        transform: translateX(-50%);
        width: 72px; height: 72px;
        background: #FFF url("data:image/png;base64,{LOGO_B64}") center/48px no-repeat;
        border-radius: 16px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      }}

      .login-card h1 {{
        margin: 0.5rem 0 0.25rem; font-size:1.5rem;
        font-weight:600; color:#1F2937;
      }}
      .login-card .subtitle {{
        margin-bottom:0.5rem; font-size:1rem; color:#4B5563;
      }}
      .login-card .description {{
        margin-bottom:1.5rem; font-size:0.875rem; color:#4B5563;
      }}
      .login-card .login-btn {{
        display:flex; align-items:center; justify-content:center;
        gap:0.5rem; width:100%; height:3rem;
        background:#FFF; border:1px solid #D1D5DB; border-radius:8px;
        font-size:1rem; color:#374151; cursor:pointer;
        transition:background .2s;
      }}
      .login-card .login-btn:hover {{ background:#F3F4F6; }}
      .login-card .terms {{
        margin-top:1.5rem; font-size:0.75rem; color:#6B7280;
      }}
    </style>

    <div class="login-wrapper">
      <div class="login-card">
        <h1>Quadra Engenharia</h1>
        <p class="subtitle">Faça login para acessar nosso assistente virtual</p>
        <p class="description">
          Entre com sua conta Google para começar a conversar com nosso assistente
        </p>
        <button class="login-btn" onclick="streamlitAuthentication()">
          <svg width="20" height="20" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          Entrar com Google
        </button>
        <p class="terms">
          Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade
        </p>
      </div>
    </div>
    <script>
      function streamlitAuthentication() {{
        const url = new URL(window.location);
        url.searchParams.set("login", "1");
        window.history.replaceState(null, "", url);
        window.location.reload();
      }}
    </script>
    """, unsafe_allow_html=True)

    # Detecta query param ?login=1
    if st.experimental_get_query_params().get("login") == ["1"]:
        st.session_state.user = {"name": "Usuário Demo", "email": "demo@quadra.com"}
        st.experimental_set_query_params()
        st.experimental_rerun()

    st.stop()

# --- 6) Chat – layout Lovable ---
user = st.session_state.user

st.markdown(f"""
<style>
  /* Fundo gradiente azul-claro */
  .stApp {{
    background: linear-gradient(to bottom right, #EFF6FF, #BFDBFE);
  }}

  /* Header estilo Lovable */
  .chat-header {{
    width:100%; background:#fff;
    border-bottom:1px solid #DBEAFE;
    box-shadow:0 1px 2px rgba(0,0,0,0.05);
    padding:12px 0;
  }}
  .chat-header .inner {{
    max-width:800px; margin:0 auto;
    display:flex; justify-content:space-between; align-items:center;
  }}
  .chat-header .logo {{
    display:flex; align-items:center; gap:8px;
  }}
  .chat-header .logo img {{
    width:40px; height:40px; border-radius:8px;
  }}
  .chat-header .logo .texts h1 {{
    margin:0; font-size:1.25rem; color:#1E3A8A;
  }}
  .chat-header .logo .texts p {{
    margin:0; font-size:0.875rem; color:#2563EB;
  }}
  .chat-header .user-info {{
    display:flex; align-items:center; gap:16px;
  }}
  .chat-header .user-info .name-email p:first-child {{
    margin:0; font-weight:500; color:#1F2937;
  }}
  .chat-header .user-info .name-email p:last-child {{
    margin:0; font-size:0.75rem; color:#4B5563;
  }}
  .chat-header .user-info .avatar {{
    width:32px; height:32px; border-radius:50%;
    background:#DBEAFE; display:flex; justify-content:center; align-items:center;
    font-weight:600; color:#1E3A8A;
  }}
  .chat-header .user-info button {{
    all:unset; cursor:pointer; font-size:1.125rem; color:#2563EB;
  }}

  /* Container do chat */
  .chat-container {{
    max-width:800px; margin:24px auto;
    display:flex; flex-direction:column; height:calc(100vh - 100px);
    padding:0 8px;
  }}
  .chat-box {{
    flex:1; background:rgba(255,255,255,0.8);
    backdrop-filter:blur(6px); border:1px solid #DBEAFE;
    border-radius:8px; overflow-y:auto; padding:16px;
  }}
  .message.user {{ display:flex; justify-content:flex-end; margin-bottom:12px; }}
  .message.bot  {{ display:flex; justify-content:flex-start; margin-bottom:12px; }}
  .bubble {{
    max-width:70%; padding:8px 12px; border-radius:9999px;
    font-size:0.875rem; line-height:1.2; position:relative;
  }}
  .bubble.user {{ background:#2563EB; color:#fff; border-bottom-right-radius:0; }}
  .bubble.bot  {{ background:#F3F4F6; color:#1F2937; border-bottom-left-radius:0; }}
  .bubble .ts {{
    display:block; font-size:0.75rem; margin-top:4px;
    color:rgba(31,41,55,0.6); text-align:right;
  }}

  /* Input footer */
  .chat-input {{
    border-top:1px solid #DBEAFE; padding:12px; display:flex; gap:8px;
  }}
  .chat-input input {{
    flex:1; padding:8px 12px; font-size:0.875rem;
    border:1px solid #DBEAFE; border-radius:9999px;
  }}
  .chat-input button {{
    all:unset; width:40px; height:40px;
    background:#2563EB; border-radius:9999px;
    display:flex; align-items:center; justify-content:center;
    cursor:pointer;
  }}
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
        <p>{user["name"]}</p>
        <p>{user["email"]}</p>
      </div>
      <div class="avatar">{user["name"][0].upper()}</div>
      <button onclick="window.location.reload()">↩️</button>
    </div>
  </div>
</div>

<!-- CHAT BOX -->
<div class="chat-container">
  <div class="chat-box">
""", unsafe_allow_html=True)

# Exibe o histórico
for pergunta, resposta in st.session_state.historico:
    st.markdown(f"""
    <div class="message user">
      <div class="bubble user">
        {pergunta}
        <span class="ts"></span>
      </div>
    </div>
    <div class="message bot">
      <div class="bubble bot">
        {resposta}
        <span class="ts"></span>
      </div>
    </div>
    """, unsafe_allow_html=True)

# Fecha chat-box e abre footer
st.markdown("""
  </div>
  <div class="chat-input">
""", unsafe_allow_html=True)

# Campo de input
mensagem = st.chat_input("Digite sua mensagem…")
if mensagem:
    st.session_state.historico.append((mensagem, responder_pergunta(mensagem)))
    st.experimental_rerun()

# Botão de envio
st.markdown("""
  <button onclick="document.querySelector('button[title=\"Send message\"]').click()">✈️</button>
  </div>
</div>
""", unsafe_allow_html=True)
