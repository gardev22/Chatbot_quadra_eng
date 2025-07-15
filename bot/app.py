import streamlit as st
import base64
from pathlib import Path
from datetime import datetime
from openai_backend import responder_pergunta

# --- Função para carregar PNG como Base64 ---
@st.cache_data
def load_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()

# --- Caminhos ---
ROOT = Path.cwd()
LOGO_PATH = ROOT / "data" / "logo_quadra.png"
if not LOGO_PATH.exists():
    st.error(f"Logo não encontrado em: {LOGO_PATH}")
    st.stop()
LOGO_B64 = load_base64(LOGO_PATH)

# --- Configuração de página ---
st.set_page_config(
    page_title="Chatbot da Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Estado de sessão ---
if "user" not in st.session_state:
    st.session_state.user = None
if "historico" not in st.session_state:
    st.session_state.historico = []

# --- Tela de Login ---
if st.session_state.user is None:
    st.markdown(f"""
    <style>
      #MainMenu, header, footer {{ visibility: hidden; }}
      .login-page {{
        position: fixed; inset: 0;
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #000000 100%);
        display: flex; align-items: center; justify-content: center;
        padding: 1rem;
      }}
      .login-card {{
        width: 360px; background: #F8FAFC;
        border-radius: 12px; padding: 2rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        text-align: center; position: relative;
      }}
      .login-card::before {{
        content: '';
        position: absolute; top: -36px; left: 50%; transform: translateX(-50%);
        width: 72px; height: 72px;
        background: #FFF url('data:image/png;base64,{LOGO_B64}') center/48px no-repeat;
        border-radius: 16px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      }}
      .login-card h1 {{ margin: 44px 0 0.25rem; font-size:1.5rem; font-weight:600; color:#1F2937; }}
      .login-card .subtitle {{ margin-bottom:0.5rem; font-size:1rem; color:#4B5563; }}
      .login-card .description {{ margin-bottom:1.5rem; font-size:0.875rem; color:#4B5563; }}
      .stButton > button {{
        display:flex; align-items:center; justify-content:center; gap:0.5rem;
        width:100%; height:3rem;
        background:#FFF; border:1px solid #D1D5DB; border-radius:8px;
        font-size:1rem; color:#374151; cursor:pointer; transition:background .2s;
      }}
      .stButton > button:hover {{ background:#F3F4F6; }}
      .login-card .terms {{ margin-top:1.5rem; font-size:0.75rem; color:#6B7280; }}
    </style>
    <div class="login-page">
      <div class="login-card">
        <h1>Quadra Engenharia</h1>
        <p class="subtitle">Faça login para acessar nosso assistente virtual</p>
        <p class="description">Entre com sua conta Google para começar a conversar com nosso assistente</p>
    """, unsafe_allow_html=True)

    if st.button("Entrar com Google"):
        st.session_state.user = {'name': 'Usuário Demo', 'email': 'demo@quadra.com'}
        st.experimental_rerun()

    st.markdown("""
        <p class="terms">Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# --- Chat após login ---
user = st.session_state.user

# Insere mensagem inicial se não existir
if not st.session_state.historico:
    st.session_state.historico.append((
        f"Olá, {user['name']}! Bem-vindo ao chat da Quadra Engenharia. Como posso ajudá-lo hoje?",
        None
    ))

st.markdown(f"""
<style>
  .stApp {{ background: linear-gradient(to bottom right, #EFF6FF, #BFDBFE); }}
  .chat-header {{ background:#fff; border-bottom:1px solid #DBEAFE; box-shadow:0 1px 2px rgba(0,0,0,0.05); padding:12px 0; }}
  .inner {{ max-width:800px; margin:0 auto; display:flex; justify-content:space-between; align-items:center; }}
  .logo img {{ width:40px; height:40px; border-radius:8px; }}
  .logo .texts h1 {{ margin:0; font-size:1.25rem; color:#1E3A8A; }}
  .logo .texts p {{ margin:0; font-size:0.875rem; color:#2563EB; }}
  .user-info {{ display:flex; align-items:center; gap:16px; }}
  .user-info .name-email p:first-child {{ margin:0; font-weight:500; color:#1F2937; }}
  .user-info .name-email p:last-child {{ margin:0; font-size:0.75rem; color:#4B5563; }}
  .user-info .avatar {{ width:32px; height:32px; border-radius:50%; background:#DBEAFE; display:flex; justify-content:center; align-items:center; font-weight:600; color:#1E3A8A; }}
  .user-info button {{ all:unset; cursor:pointer; font-size:1.125rem; color:#2563EB; }}
  .chat-container {{ max-width:800px; margin:24px auto; display:flex; flex-direction:column; height:calc(100vh - 100px); padding:0 8px; }}
  .chat-box {{ flex:1; background:rgba(255,255,255,0.8); backdrop-filter:blur(6px); border:1px solid #DBEAFE; border-radius:8px; overflow-y:auto; padding:16px; }}
  .message.user {{ justify-content:flex-end; display:flex; margin-bottom:12px; }}
  .message.bot {{ justify-content:flex-start; display:flex; margin-bottom:12px; }}
  .bubble {{ max-width:70%; padding:8px 12px; border-radius:9999px; font-size:0.875rem; line-height:1.2; }}
  .bubble.user {{ background:#2563EB; color:#fff; border-bottom-right-radius:0; }}
  .bubble.bot {{ background:#F3F4F6; color:#1F2937; border-bottom-left-radius:0; }}
  .bubble .ts {{ display:block; font-size:0.75rem; margin-top:4px; color:rgba(31,41,55,0.6); text-align:right; }}
  .chat-input {{ border-top:1px solid #DBEAFE; padding:12px; display:flex; gap:8px; }}
  .chat-input input {{ flex:1; padding:8px 12px; font-size:0.875rem; border:1px solid #DBEAFE; border-radius:9999px; }}
  .chat-input button {{ all:unset; width:40px; height:40px; background:#2563EB; border-radius:9999px; display:flex; align-items:center; justify-content:center; cursor:pointer; }}
</style>

<!-- HEADER -->
<div class="chat-header"><div class="inner">
  <div class="logo">
    <img src="data:image/png;base64,{LOGO_B64}" alt="Quadra Engenharia"/>
    <div class="texts"><h1>Quadra Engenharia</h1><p>Assistente Virtual</p></div>
  </div>
  <div class="user-info">
    <div class="name-email"><p>{user['name']}</p><p>{user['email']}</p></div>
    <div class="avatar">{user['name'][0].upper()}</div>
    <button onclick="window.location.reload()">↩️</button>
  </div>
</div></div>

<!-- CHAT BOX -->
<div class="chat-container"><div class="chat-box">
""", unsafe_allow_html=True)

# Render histórico
for pergunta, resposta in st.session_state.historico:
    ts = datetime.now().strftime("%H:%M")
    bot_html = f"<div class=\"message bot\"><div class=\"bubble bot\">{resposta}<span class=\"ts\">{ts}</span></div></div>" if resposta else ""
    st.markdown(f"""
    <div class=\"message user\"><div class=\"bubble user\">{pergunta}<span class=\"ts\">{ts}</span></div></div>
    {bot_html}
    """, unsafe_allow_html=True)

st.markdown("""
</div>
<div class=\"chat-input\">""", unsafe_allow_html=True)

# Input e envio
mensagem = st.chat_input("Digite sua mensagem…")
if mensagem:
    resp = responder_pergunta(mensagem)
    st.session_state.historico.append((mensagem, resp))
    st.experimental_rerun()

st.markdown("""
<button onclick=\"document.querySelector('button[title=\\\"Send message\\\"]').click()\">✈️</button>
</div></div>
""", unsafe_allow_html=True)
