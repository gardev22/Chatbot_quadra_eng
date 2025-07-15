import streamlit as st
import base64
from openai_backend import responder_pergunta

# --- 1) Carrega logo com cache ---
@st.cache_data
def load_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# Use o seu logo quadradinho com fundo transparente (ex: 512×512)  
LOGO = load_image("data/logo_quadra_circle.png")

# --- 2) Configura página e remove chrome/padding ---
st.set_page_config(
    page_title="Login | Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown("""
<style>
  /* Remove menu, header e footer nativos */
  #MainMenu, header, footer { visibility: hidden; }
  /* Container full-screen com gradiente */
  .login-page {
    position: fixed;
    top: 0; left: 0;
    width: 100vw; height: 100vh;
    background: linear-gradient(135deg,
      #0f172a 0%,
      #1e3a8a 60%,
      #000000 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  /* Card central */
  .login-card {
    max-width: 400px;
    width: 100%;
    background: #F8FAFC;
    border-radius: 12px;
    padding: 2rem;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    text-align: center;
  }
  /* Contêiner do logo */
  .logo-container {
    width: 72px; height: 72px;
    margin: 0 auto 1rem;
    background: #FFFFFF;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .logo-container img {
    width: 48px; height: 48px;
  }
  /* Título e textos */
  .login-card h1 {
    margin: 0.5rem 0;
    color: #1F2937;
    font-size: 1.5rem;
    font-weight: 600;
  }
  .login-card .subtitle {
    font-size: 1rem;
    color: #4B5563;
    margin-bottom: 0.5rem;
  }
  .login-card .description {
    font-size: 0.875rem;
    color: #4B5563;
    margin-bottom: 1.5rem;
  }
  /* Botão Google */
  .google-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.75rem 1rem;
    font-size: 1rem;
    color: #374151;
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.2s ease;
  }
  .google-btn:hover {
    background: #F3F4F6;
  }
  .google-btn svg {
    width: 18px; height: 18px;
  }
  /* Termos */
  .login-card .terms {
    font-size: 0.75rem;
    color: #6B7280;
    margin-top: 1.5rem;
  }
</style>
""", unsafe_allow_html=True)

# --- 3) Renderiza o card ---
st.markdown('<div class="login-page">', unsafe_allow_html=True)
st.markdown('<div class="login-card">', unsafe_allow_html=True)

# Logo
st.markdown('<div class="logo-container">', unsafe_allow_html=True)
st.markdown(f'<img src="data:image/png;base64,{LOGO}" />', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Títulos
st.markdown('<h1>Quadra Engenharia</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Faça login para acessar nosso assistente virtual</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="description">'
    'Entre com sua conta Google para começar a conversar com nosso assistente'
    '</p>',
    unsafe_allow_html=True
)

# Botão “Entrar com Google” (por enquanto não dispara nada)
st.markdown("""
<div>
  <button class="google-btn">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 
          1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 
          3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 
          7.28-2.66l-3.57-2.77c-.98.66-2.23 
          1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 
          20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 
          8.55 1 10.22 1 12s.43 3.45 
          1.18 4.93l2.85-2.22.81-.62z"/>
      <path fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 
          4.21 1.64l3.15-3.15C17.45 2.09 
          14.97 1 12 1 7.7 1 3.99 3.47 
          2.18 7.07l3.66 2.84c.87-2.6 
          3.3-4.53 6.16-4.53z"/>
    </svg>
    Entrar com Google
  </button>
</div>
""", unsafe_allow_html=True)

# Termos
st.markdown(
    '<p class="terms">'
    'Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade'
    '</p>',
    unsafe_allow_html=True
)

# Fecha os divs e interrompe o resto da página
st.markdown('</div></div>', unsafe_allow_html=True)
st.stop()
