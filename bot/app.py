import streamlit as st
import base64
from pathlib import Path

# --- 1) Função para carregar o PNG em Base64 ---
@st.cache_data
def load_image(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# --- 2) Resolve o caminho correto para o logo ---
# app.py está em .../bot, data/ está em .../data
APP_DIR     = Path(__file__).resolve().parent       # .../bot
PROJECT_ROOT = APP_DIR.parent                       # .../chatbot_quadra_eng
LOGO_PATH   = PROJECT_ROOT / "data" / "logo_quadra.png"

# Se não existir, interrompe mostrando erro
if not LOGO_PATH.exists():
    st.error(f"❌ Logo não encontrado em: {LOGO_PATH}")
    st.stop()

LOGO_ICON = load_image(LOGO_PATH)

# --- 3) Configuração da página ---
st.set_page_config(
    page_title="Login | Quadra Engenharia",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- 4) Injeta o CSS completo ---
st.markdown(f"""
<style>
  /* Esconde menu, header e footer do Streamlit */
  #MainMenu, header, footer {{ visibility: hidden; margin:0; padding:0; }}

  /* Fullscreen + gradiente + logo de fundo */
  .login-page {{
    position: fixed; inset: 0;
    background:
      url("data:image/png;base64,{LOGO_ICON}") no-repeat center top,
      linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #000000 100%);
    background-size: 600px auto, cover;
    display: flex; align-items: center; justify-content: center;
  }}

  /* Card branco */
  .login-card {{
    width: 360px;
    background: #F8FAFC;
    border-radius: 16px;
    padding: 2rem;
    box-shadow: 0 16px 40px rgba(0,0,0,0.25);
    text-align: center;
  }}

  /* Logo interna */
  .login-card .logo-sm {{
    width: 64px; height: 64px;
    margin: 0 auto 1rem; padding: 0.5rem;
    background: #FFF; border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  }}
  .login-card .logo-sm img {{ width: 100%; height: 100%; }}

  /* Títulos */
  .login-card h1 {{
    margin: 0.5rem 0 0.25rem;
    font-size: 1.5rem; font-weight: 600;
    color: #1F2937;
  }}
  .login-card .subtitle {{
    margin-bottom: 0.5rem;
    font-size: 1rem; color: #4B5563;
  }}
  .login-card .description {{
    margin-bottom: 1.5rem;
    font-size: 0.875rem; color: #4B5563;
  }}

  /* Botão Google */
  .login-card .google-btn {{
    display: flex; align-items: center; justify-content: center;
    gap: 0.5rem; width: 100%; height: 3rem;
    font-size: 1rem; color: #374
