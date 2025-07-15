import streamlit as st
import base64
from pathlib import Path

import streamlit as st
import base64
from pathlib import Path

# --- 1) Carrega o logo da Quadra em Base64 ---
@st.cache_data
def load_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()

# Assume que você executa `streamlit run bot/app.py` a partir do root
ROOT      = Path.cwd()
LOGO_PATH = ROOT / "data" / "logo_quadra.png"
if not LOGO_PATH.exists():
    st.error(f"Logo não encontrado em:\n{LOGO_PATH}")
    st.stop()
LOGO_B64 = load_base64(LOGO_PATH)

# --- 2) Configura página ---
st.set_page_config(
    page_title="Login | Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- 3) Injeta CSS/HTML para reproduzir o design exato ---
st.markdown(f"""
<style>
  /* Esconde menu/header/footer */
  #MainMenu, header, footer {{ visibility: hidden; margin:0; padding:0; }}

  /* Fundo fullscreen com gradiente */
  .login-wrapper {{
    position: fixed; inset: 0;
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #000000 100%);
    display: flex; align-items: center; justify-content: center;
  }}

  /* Card central */
  .login-card {{
    position: relative;
    width: 360px;
    background: #F8FAFC;
    border-radius: 12px;
    padding: 48px 24px 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    text-align: center;
  }}

  /* Logo circular sobre o card */
  .login-card::before {{
    content: "";
    position: absolute;
    top: -36px;
    left: 50%;
    transform: translateX(-50%);
    width: 72px; height: 72px;
    background: #FFF url("data:image/png;base64,{LOGO_B64}") center/48px no-repeat;
    border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  }}

  /* Textos */
  .login-card h1 {{
    margin: 0.5rem 0 0.25rem;
    font-size: 1.5rem;
    font-weight: 600;
    color: #1F2937;
  }}
  .login-card .subtitle {{
    margin-bottom: 0.5rem;
    font-size: 1rem;
    color: #4B5563;
  }}
  .login-card .description {{
    margin-bottom: 1.5rem;
    font-size: 0.875rem;
    color: #4B5563;
  }}

  /* Botão “Entrar com Google” */
  .login-card .login-btn {{
    display: flex; align-items: center; justify-content: center;
    gap: 0.5rem; width: 100%; height: 3rem;
    background: #FFF; border: 1px solid #D1D5DB; border-radius: 8px;
    font-size: 1rem; color: #374151; cursor: pointer;
    transition: background 0.2s;
  }}
  .login-card .login-btn:hover {{ background: #F3F4F6; }}

  /* Termos */
  .login-card .terms {{
    margin-top: 1.5rem;
    font-size: 0.75rem;
    color: #6B7280;
  }}
</style>
""", unsafe_allow_html=True)

# --- 4) HTML puro para montar a janela ---
st.markdown("""
<div class="login-wrapper">
  <div class="login-card">
    <h1>Quadra Engenharia</h1>
    <p class="subtitle">Faça login para acessar nosso assistente virtual</p>
    <p class="description">
      Entre com sua conta Google para começar a conversar com nosso assistente
    </p>
    <button class="login-btn">
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
""", unsafe_allow_html=True)

st.stop()
