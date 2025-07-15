import streamlit as st
import base64
from openai_backend import responder_pergunta

import streamlit as st
import base64

# --- 1) Carrega logo com cache ---
@st.cache_data
def load_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

LOGO = load_image("data/logo_quadra.png")

# --- 2) Configura página e esconde chrome nativo ---
st.set_page_config(
    page_title="Login Quadra Engenharia",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
      /* Esconder menu, footer e header padrão */
      #MainMenu, footer, header { visibility: hidden; }
      /* Tela cheia com gradiente */
      .login-page {
        min-height: 100vh;
        display: flex;
        justify-content: center;
        align-items: center;
        background: linear-gradient(
          to bottom right,
          #0f172a, /* slate-900 */
          #1e3a8a, /* blue-900 */
          #000000
        );
        padding: 1rem;
      }
      /* Card */
      .login-card {
        max-width: 400px;
        width: 100%;
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(8px);
        border-radius: 1rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        padding: 2rem;
        text-align: center;
      }
      .login-card img {
        width: 96px;
        height: 96px;
        margin: 0 auto 1rem;
        background: white;
        padding: 1rem;
        border-radius: 1.5rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      }
      .login-card h1 {
        font-size: 1.75rem;
        margin: 0.5rem 0;
        color: #1e293b; /* slate-900 */
      }
      .login-card p.subtitle {
        color: #475569; /* slate-600 */
        margin-bottom: 1.5rem;
      }
      /* Botão Google */
      .stButton > button {
        width: 100% !important;
        height: 3rem;
        border: 1px solid #cbd5e1; /* gray-300 */
        border-radius: 0.5rem;
        background: white;
        color: #374151; /* gray-700 */
        font-size: 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
      }
      .stButton > button:hover {
        background: #f8fafc; /* gray-50 */
      }
      .login-card p.terms {
        font-size: 0.75rem;
        color: #94a3b8; /* gray-500 */
        margin-top: 1.5rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 3) Estado de autenticação ---
if "user" not in st.session_state:
    st.session_state.user = None

# --- 4) Tela de Login ---
if st.session_state.user is None:
    st.markdown('<div class="login-page">', unsafe_allow_html=True)
    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.markdown(f'<img src="data:image/png;base64,{LOGO}" />', unsafe_allow_html=True)
    st.markdown('<h1>Quadra Engenharia</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="subtitle">Faça login para acessar nosso assistente virtual</p>',
        unsafe_allow_html=True
    )
    # Botão estilizado dispara callback
    if st.button("Entrar com Google"):
        # Aqui você colocaria Firebase Auth ou OAuth real.
        st.session_state.user = {
            "name": "Usuário Demo",
            "email": "usuario@exemplo.com",
            "photoURL": None
        }
        st.experimental_rerun()
    st.markdown(
        '<p class="terms">'
        'Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade'
        '</p>',
        unsafe_allow_html=True
    )
    st.markdown('</div></div>', unsafe_allow_html=True)
    st.stop()

# --- 5) Após login, mostra nome e foto (se houver) e segue para o app ---
user = st.session_state.user
st.set_page_config(page_title=f"Olá, {user['name']}")
st.markdown(f"### Bem-vindo, **{user['name']}** ({user['email']})")
if user.get("photoURL"):
    st.image(user["photoURL"], width=64)
st.button("Sair", on_click=lambda: st.session_state.pop("user", None))


