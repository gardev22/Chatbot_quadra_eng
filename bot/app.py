import streamlit as st
import base64
from pathlib import Path

# --- 1) Função para carregar PNG em Base64 e cachear ---
@st.cache_data
def load_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# --- 2) Resolve automaticamente a pasta data/ no root do projeto ---
ROOT       = Path.cwd()                                    # normalmente onde você rodou `streamlit run`
logo_file  = ROOT / "data" / "logo_quadra.png"

if not logo_file.exists():
    st.error(f"❌ Logo não encontrado em:\n{logo_file}")
    st.stop()

LOGO_ICON = load_image(str(logo_file))

# --- 3) Configurações da página ---
st.set_page_config(
    page_title="Login | Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- 4) Injeção de CSS/HTML para reproduzir o design Figma/React ---
st.markdown(f"""
<style>
  /* Esconde menu, header e footer nativos */
  #MainMenu, header, footer {{ visibility: hidden; margin:0; padding:0; }}

  /* Tela cheia com gradiente + logo gigante de fundo */
  .login-page {{
    position: fixed; inset: 0;
    background:
      url("data:image/png;base64,{LOGO_ICON}") no-repeat center top,
      linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #000000 100%);
    background-size: 600px auto, cover;
    display: flex; align-items: center; justify-content: center;
    padding: 1rem;
  }}

  /* Card central de 360px */
  .login-card {{
    width: 360px;
    background: #F8FAFC;
    border-radius: 16px;
    padding: 2rem;
    box-shadow: 0 16px 40px rgba(0,0,0,0.25);
    text-align: center;
  }}

  /* Logo interna 64×64 */
  .login-card .logo-sm {{
    width: 64px; height: 64px;
    margin: 0 auto 1rem;
    padding: 0.5rem;
    background: #FFFFFF;
    border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  }}
  .login-card .logo-sm img {{ width:100%; height:100%; }}

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
  .login-card .google-btn {{
    display: flex; align-items: center; justify-content: center;
    gap: 0.5rem;
    width: 100%; height: 3rem;
    font-size: 1rem; color: #374151;
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.2s;
  }}
  .login-card .google-btn:hover {{ background: #F3F4F6; }}
  .login-card .google-btn svg {{ width: 20px; height: 20px; }}

  /* Termos */
  .login-card .terms {{
    margin-top: 1.5rem;
    font-size: 0.75rem;
    color: #6B7280;
  }}
</style>
""", unsafe_allow_html=True)

# --- 5) Estrutura HTML do card de login ---
st.markdown('<div class="login-page">', unsafe_allow_html=True)
st.markdown('<div class="login-card">', unsafe_allow_html=True)

# Logo interna
st.markdown('<div class="logo-sm">', unsafe_allow_html=True)
st.markdown(f'<img src="data:image/png;base64,{LOGO_ICON}" />', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Títulos e descrições
st.markdown('<h1>Quadra Engenharia</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Faça login para acessar nosso assistente virtual</p>',
    unsafe_allow_html=True
)
st.markdown(
    '<p class="description">'
    'Entre com sua conta Google para começar a conversar com nosso assistente'
    '</p>',
    unsafe_allow_html=True
)

# Botão Google (ainda sem ação de callback)
st.markdown("""
<button class="google-btn">
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-..."/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98..."/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-..."/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56..."/>
  </svg>
  Entrar com Google
</button>
""", unsafe_allow_html=True)

# Termos de serviço
st.markdown(
    '<p class="terms">'
    'Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade'
    '</p>',
    unsafe_allow_html=True
)

# Fecha os containers
st.markdown('</div></div>', unsafe_allow_html=True)
st.stop()
