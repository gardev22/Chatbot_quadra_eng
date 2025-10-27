# app.py - Frontend do Chatbot Quadra (Última Correção: Tela de Login Exata como Imagem 2)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape
import json # Para lidar com a comunicação via JSON entre JS e Streamlit

# Importa a função de resposta do backend
try:
    from openai_backend import responder_pergunta 
except ImportError:
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado. Verifique se o arquivo existe."

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG DA PÁGINA ======
LOGO_PATH = "data/logo_quadra.png" 
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="expanded",
)

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== UTILITÁRIOS ======
def carregar_imagem_base64(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

logo_b64 = carregar_imagem_base64(LOGO_PATH)

# CORREÇÃO: Definição da logo_img_tag para uso no Header após o login
if logo_b64:
    logo_img_tag = f'<img class="logo" src="data:image/png;base64,{logo_b64}" />'
else:
    logo_img_tag = '<span style="font-size: 2rem; color: #1C3364; font-weight: 900;">Q</span>'


def extract_name_from_email(email):
    """Extrai um nome (capitalizado) de um email."""
    if not email or "@" not in email:
        return "Usuário"
    local_part = email.split("@")[0]
    name_parts = re.sub(r'[\._]', ' ', local_part).split()
    return " ".join(p.capitalize() for p in name_parts)

# ====== ESTADO (Início da Sessão) ======
if "historico" not in st.session_state:
    st.session_state.historico = []

st.session_state.setdefault("authenticated", False) 
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")

st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

# ====== AUTENTICAÇÃO (Renderização completa do Card com HTML/CSS/JS) ======

def render_login_screen_html_js():
    """
    Renderiza a tela de login completamente via HTML/CSS/JS para controle total do layout.
    Usa JS para enviar os dados de login de volta ao Streamlit via query_params.
    """
    
    # URL da logo para usar diretamente no HTML
    logo_url = f"data:image/png;base64,{logo_b64}" if logo_b64 else ""

    # CSS para a tela de login
    st.markdown(f"""
    <style>
    /* Reset Streamlit default layout */
    .stApp {{
        background: radial-gradient(circle at center, #1C3364 0%, #000000 100%) !important;
        height: 100vh;
        width: 100vw;
        overflow: hidden;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 0 !important;
    }}
    header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer, section[data-testid="stSidebar"] {{ 
        display: none !important; visibility: hidden !important; height: 0 !important; 
    }}
    .block-container {{
        padding: 0 !important;
        max-width: 100% !important;
        min-height: 100% !important;
        display: flex; /* Para centralizar o conteúdo do block-container */
        justify-content: center;
        align-items: center;
    }}

    /* Card de Login */
    .login-card-container {{
        background: white; 
        border-radius: 12px; 
        padding: 40px; 
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.2);
        max-width: 400px; 
        width: 100%; 
        text-align: center; 
        color: #333;
        font-family: 'Source Sans Pro', sans-serif; /* Consistência com Streamlit */
    }}
    .login-logo {{ width: 80px; height: 80px; margin: 0px auto 25px auto; border-radius: 12px; }}
    .login-title {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 8px; color: #1C3364; }}
    .login-subtitle {{ font-size: 1rem; margin-bottom: 25px; color: #666; line-height: 1.4; }}
    .login-email-prompt {{ font-size: 0.95rem; margin-bottom: 20px; color: #555; }}
    .login-input {{
        width: calc(100% - 20px); /* Ajuste para padding */
        height: 48px; 
        font-size: 1rem; 
        border-radius: 8px; 
        border: 1px solid #ddd;
        padding: 0 10px;
        color: #333; 
        background-color: white !important; 
        margin-bottom: 15px;
        text-align: center;
    }}
    .login-button {{
        width: 100%; 
        height: 48px; 
        font-weight: 600;
        background-color: #1C3364; 
        color: white; 
        border: none;
        border-radius: 8px; 
        cursor: pointer;
        font-size: 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        transition: background-color 0.2s ease;
    }}
    .login-button:hover {{ background-color: #2a4782; }}
    .login-button-icon {{ width: 24px; height: 24px; }} /* Ícone do Google */

    .login-disclaimer {{ font-size: 0.75rem; margin-top: 25px; color: #999; line-height: 1.4; }}
    .error-message {{ color: red; font-size: 0.85rem; margin-top: 10px; }}
    </style>
    """, unsafe_allow_html=True)

    # HTML puro para o card de login
    login_html = f"""
    <div class="login-card-container">
        <img class="login-logo" src="{logo_url}" alt="Logo Quadra Engenharia">
        <div class="login-title">Quadra Engenharia</div>
        <div class="login-subtitle">Faça login para acessar nosso assistente virtual</div>
        <div class="login-email-prompt">Entre com seu e-mail **@quadra.com.vc** para começar a conversar com nosso assistente</div>
        
        <input type="email" id="loginEmailInput" class="login-input" placeholder="seu.email@quadra.com.vc">
        <div id="loginError" class="error-message"></div>
        
        <button id="loginButton" class="login-button">
            <svg class="login-button-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M43.611 20.082H42V20H24V28H36.43C35.19 31.135 33.15 33.56 30.64 35.088L30.56 35.148L37.16 40.09C39.06 37.288 40.57 33.82 41.34 30.144C42.11 26.468 42.11 22.84 41.34 19.164C40.57 15.488 39.06 12.02 37.16 9.212L36.91 8.82L30.31 13.762C27.8 15.29 25.76 17.715 24.52 20.85H24V20.082L24.37 20.082H43.611Z" fill="#EA4335"/>
                <path d="M6.02344 24.0001C6.02344 21.6881 6.55144 19.5081 7.49944 17.5681L14.0994 12.6121C12.0434 16.5921 11.0234 20.2521 11.0234 24.0001C11.0234 27.7481 12.0434 31.4081 14.0994 35.3881L7.49944 40.3441C6.55144 38.4041 6.02344 36.2241 6.02344 33.9121V24.0001Z" fill="#FBBC04"/>
                <path d="M24.0001 5.99992C27.0291 5.99992 29.8371 7.02092 32.1931 8.94192L37.1611 4.00092C34.0481 1.49392 30.0861 0.000915527 24.0001 0.000915527C14.7711 0.000915527 7.02313 5.43892 6.02313 17.5679L14.0991 12.6119C15.0231 9.17092 18.0061 5.99992 24.0001 5.99992Z" fill="#4285F4"/>
                <path d="M24.0001 47.9999C29.6231 47.9999 34.6951 45.4989 38.1931 41.5649L30.6401 35.0879C27.7661 36.9089 24.0001 37.9999 24.0001 37.9999C18.4411 37.9999 14.4791 35.0359 12.6111 31.4079L6.02313 36.2239C7.02313 40.3439 14.7711 47.9999 24.0001 47.9999Z" fill="#34A853"/>
            </svg>
            Entrar com Google
        </button>

        <div class="login-disclaimer">Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade.</div>
    </div>
    """
    
    # JavaScript para enviar o email de volta ao Streamlit
    login_js = """
    <script>
    document.getElementById('loginButton').onclick = function() {
        var emailInput = document.getElementById('loginEmailInput');
        var email = emailInput.value.trim().toLowerCase();
        var errorDiv = document.getElementById('loginError');

        if (!email || !email.includes('@')) {
            errorDiv.textContent = "Por favor, insira um e-mail válido.";
            return;
        }
        if (!email.endsWith('@quadra.com.vc')) {
            errorDiv.textContent = "Acesso restrito. Use seu e-mail @quadra.com.vc.";
            return;
        }

        // Simula o login e envia o e-mail via query parameters para o Streamlit
        window.parent.postMessage({
            type: 'streamlit:setFrameHeight',
            height: 1
        }, '*'); // Truque para recarregar a página ou enviar um evento
        
        // st.experimental_set_query_params não funciona diretamente de JS no iframe do Streamlit
        // A melhor abordagem é forçar um rerun e usar um truque de sessão ou cookie,
        // mas para fins de demonstração e controle total do layout, esta é a próxima.
        // O mais direto é manipular a URL ou usar postMessage para o backend se estivesse em um ambiente mais complexo.
        // Para simular a navegação (que Streamlit irá re-executar):
        window.location.href = window.location.origin + window.location.pathname + '?logged_email=' + encodeURIComponent(email);
    };
    </script>
    """

    st.markdown(login_html, unsafe_allow_html=True)
    st.markdown(login_js, unsafe_allow_html=True)
    st.stop() # Interrompe a execução do chat até o login


# =================================================================
#                         FLUXO PRINCIPAL
# =================================================================

# 1. VERIFICAÇÃO DE AUTENTICAÇÃO
if not st.session_state.authenticated:
    # Tenta obter o email dos query parameters (enviado pelo JS do login)
    query_params = st.experimental_get_query_params()
    logged_email = query_params.get("logged_email", [None])[0]

    if logged_email:
        # Processa o email vindo do JS
        email = logged_email.strip().lower()
        if "@quadra.com.vc" in email: # Já validado pelo JS, mas por segurança
            st.session_state.authenticated = True
            st.session_state.user_email = email
            st.session_state.user_name = extract_name_from_email(email)
            
            # Limpa os query params para não ficar no histórico do navegador
            st.experimental_set_query_params(logged_email=None)
            do_rerun()
        else:
            # Caso raro de bypass JS, mas por segurança
            st.error("Acesso restrito. Use seu e-mail **@quadra.com.vc**.")
            render_login_screen_html_js() # Mantém na tela de login
    else:
        render_login_screen_html_js() # Renderiza a tela de login inicial
    st.stop() # Garante que nada mais é renderizado antes do login

# A partir daqui, o usuário está autenticado. O visual de chat será aplicado.

# ====== MARCAÇÃO (Formatação de Texto) ======
def formatar_markdown_basico(text: str) -> str:
    if not text: return ""
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = text.replace("\n", "<br>")
    return text

def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

# ====== CSS (Chat Customizado - Tema Escuro) ======
# O CSS abaixo é para o CHAT e é mantido inalterado
st.markdown(f"""
<style>
/* ========= RESET / BASE ========= */
* {{ box-sizing: border-box }}
html, body {{ margin: 0; padding: 0 }}
img {{ max-width: 100%; height: auto; display: inline-block }}
img.logo {{ height: 44px !important; width: auto !important }}

/* ========= VARS (Customização) ========= */
:root{{
    --content-max-width: min(96vw, 1400px);
    --header-height: 68px;
    --chat-safe-gap: 300px;
    --card-height: calc(100dvh - var(--header-height) - 24px);
    --input-max: 900px;
    --input-bottom: 60px;

    /* PALETA UNIFICADA (CHAT THEME) */
    --bg:#1C1F26;        
    --panel:#0B0D10;     
    --panel-header:#14171C; 
    --panel-alt:#1C1F26; 
    --border:#242833;

    --text:#E5E7EB;
    --text-dim:#C9D1D9;
    --muted:#9AA4B2;

    --link:#B9C0CA;
    --link-hover:#FFFFFF;

    --bubble-user:#222833;
    --bubble-assistant:#232833;

    --input-bg:#1E222B;
    --input-border:#323949;

    --sidebar-w:270px;

    --sidebar-items-top-gap: -45px;
    --sidebar-sub-top-gap: -30px; 
    --sidebar-list-start-gap: 3px; 
}}

/* ========= STREAMLIT CHROME (Remoção de elementos padrão) ========= */
header[data-testid="stHeader"]{{ display:none !important }}
div[data-testid="stToolbar"]{{ display:none !important }}
#MainMenu, footer{{ visibility:hidden; height:0 !important }}

html, body, .stApp, main, .stMain, .block-container, [data-testid="stAppViewContainer"]{{
    height:100dvh !important;
    max-height:100dvh !important;
    overflow:hidden !important;
    overscroll-behavior:none;
}}
.block-container{{ padding:0 !important; min-height:0 !important }}
.stApp{{ background:var(--bg) !important; color:var(--text) !important }}

/* ========= HEADER FIXO (Topo) ========= */
.header{{
    position:fixed; inset:0 0 auto 0; height:var(--header-height);
    display:flex; align-items:center; justify-content:space-between;
    padding:10px 16px; background:var(--panel-header); z-index:1000;
    border-bottom:1px solid var(--border);
}}
.header-left{{ display:flex; align-items:center; gap:10px; font-weight:600; color:var(--text) }}
.header-left .title-sub{{ font-weight:500; font-size:.85rem; color:var(--muted); margin-top:-4px }}
.header-right{{ display:flex; align-items:center; gap:12px; color:var(--text) }}
.header a{{
    color:var(--link) !important; text-decoration:none;
    border:1px solid var(--border); padding:8px 12px; border-radius:10px; display:inline-block;
}}
.header a:hover{{ color:var(--link-hover) !important; border-color:#3B4250 }}
.user-circle {{
    width: 32px; height: 32px; border-radius: 50%; 
    background: #007bff; color: white; 
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 1rem;
}}

/* ========= SIDEBAR ========= */
section[data-testid="stSidebar"]{{
    position:fixed !important;
    top:var(--header-height) !important;
    left:0 !important;
    height:calc(100dvh - var(--header-height)) !important;
    width:var(--sidebar-w) !important;
    min-width:var(--sidebar-w) !important;
    margin:0 !important; padding:0 !important;
    background:var(--panel) !important;
    border-right:1px solid var(--border);
    z-index:900 !important;
    transform:none !important;
    visibility:visible !important;
    overflow:hidden !important;
    color:var(--text);
}}
section[data-testid="stSidebar"] > div{{ padding-top:0 !important; margin-top:0 !important; }}
div[data-testid="stSidebarContent"]{{ padding-top:0 !important; margin-top:0 !important; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{ padding-top:0 !important; margin-top:0 !important; }}

section[data-testid="stSidebar"] .sidebar-header{{
    margin-top: var(--sidebar-items-top-gap) !important;
}}
.sidebar-bar p,
.sidebar-header p{{
    margin: 0 !important;
    line-height: 1.15 !important;
}}
.sidebar-bar{{
    margin-top: var(--sidebar-sub-top-gap) !important;
}}
.hist-row:first-of-type{{
    margin-top: var(--sidebar-list-start-gap) !important;
}}

div[data-testid="stAppViewContainer"]{{ margin-left:var(--sidebar-w) !important }}

.sidebar-header{{ font-size:1.1rem; font-weight:700; letter-spacing:.02em; color:var(--text); margin:0 4px -2px 2px }}
.sidebar-sub{{ font-size:.88rem; color:var(--muted) }}
.hist-empty{{ color:var(--muted); font-size:.9rem; padding:8px 10px }}
.hist-row{{ padding:6px 6px; font-size:1.1rem; color:var(--text-dim) !important; line-height:1.35; border-radius:8px }}
.hist-row + .hist-row{{ margin-top:6px }}
.hist-row:hover{{ background:#161a20 }}

/* ========= CONTEÚDO / CHAT (Mensagens) ========= */
.content{{ max-width:var(--content-max-width); margin:var(--header-height) auto 0; padding:8px }}
#chatCard, .chat-card{{
    position:relative;
    z-index:50 !important;
    background:var(--bg) !important; 
    border:none !important; border-radius:12px 12px 0 0 !important; box-shadow:none !important;
    padding:20px;
    height:var(--card-height);
    overflow-y:auto; scroll-behavior:smooth;
    padding-bottom:var(--chat-safe-gap); scroll-padding-bottom:var(--chat-safe-gap);
    color:var(--text);
}}
#chatCard *, .chat-card *{{ position:relative; z-index:51 !important }}

.message-row{{ display:flex !important; margin:12px 4px; scroll-margin-bottom:calc(var(--chat-safe-gap) + 16px) }}
.message-row.user{{ justify-content:flex-end }}
.message-row.assistant{{ justify-content:flex-start }}
.bubble{{
    max-width:88%; padding:14px 16px; border-radius:12px; font-size:15px; line-height:1.45;
    color:var(--text); word-wrap:break-word; border:1px solid transparent !important; box-shadow:none !important;
}}
.bubble.user{{ background:var(--bubble-user); border-bottom-right-radius:6px }}
.bubble.assistant{{ background:var(--bubble-assistant); border-bottom-left-radius:6px }}
.chat-card a{{ color:var(--link); text-decoration:underline }} .chat-card a:hover{{ color:var(--link-hover) }}

/* ========= CHAT INPUT (Fixação e Estilização) ========= */
[data-testid="stChatInput"]{{
    position:fixed !important;
    left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2) !important; 
    transform:translateX(-50%) !important;
    bottom:var(--input-bottom) !important;
    width:min(var(--input-max), 96vw) !important;
    z-index:5000 !important;
    background:transparent !important;
    border:none !important;
    box-shadow:none !important;
    padding:0 !important;
}}
[data-testid="stChatInput"] *{{
    background:transparent !important;
    color:var(--text) !important;
}}
[data-testid="stChatInput"] > div{{
    background:var(--input-bg) !important;
    border:1px solid var(--input-border) !important;
    border-radius:999px !important;
    box-shadow:0 10px 24px rgba(0,0,0,.35) !important;
    overflow:hidden;
    transition:border-color .12s ease, box-shadow .12s ease;
}}
[data-testid="stChatInput"] textarea{{
    width:100% !important;
    border:none !important; border-radius:999px !important;
    padding:18px 20px !important; font-size:16px !important;
    outline:none !important; height:auto !important;
    min-height:44px !important; max-height:220px !important;
    overflow-y:hidden !important;
    caret-color:#ffffff !important;
}}
[data-testid="stChatInput"] textarea::placeholder{{ color:var(--muted) !important }}
[data-testid="stChatInput"] textarea:focus::placeholder{{ color:transparent !important; opacity:0 !important }}
[data-testid="stChatInput"] button{{
    margin-right:8px !important; border:none !important; background:transparent !important; color:var(--text-dim) !important;
}}
[data-testid="stChatInput"] svg{{ fill:currentColor !important }}

/* MATA DEFINITIVAMENTE A FAIXA BRANCA (bottom block) */
[data-testid="stBottomBlockContainer"],
[data-testid="stBottomBlockContainer"] > div,
[data-testid="stBottomBlockContainer"] [data-testid="stVerticalBlock"],
[data-testid="stBottomBlockContainer"] [class*="block-container"],
[data-testid="stBottomBlockContainer"]::before,
[data-testid="stBottomBlockContainer"]::after{{
    background:transparent !important;
    box-shadow:none !important;
    border:none !important;
}}
[data-testid="stBottomBlockContainer"]{{
    padding:0 !important;
    margin:0 !important;
    height:0 !important;
    min-height:0 !important;
}}

/* EXTRAS */
[data-testid="stDecoration"], [data-testid="stStatusWidget"]{{ display:none !important }}
*::-webkit-scrollbar{{ width:10px; height:10px }}
*::-webkit-scrollbar-thumb{{ background:#2C3340; border-radius:8px }}
*::-webkit-scrollbar-track{{ background:#0F1115 }}

.spinner{{
    width:16px; height:16px;
    border:2px solid rgba(37,99,235,.25);
    border-top-color:#2563eb;
    border-radius:50%;
    display:inline-block;
    animation:spin .8s linear infinite;
}}
@keyframes spin{{ to{{ transform:rotate(360deg) }} }}
</style>
""", unsafe_allow_html=True)

# ====== HEADER HTML (Cabeçalho superior) ======
primeira_letra = st.session_state.user_name[0].upper() if st.session_state.user_name else 'U'
st.markdown(f"""
<div class="header">
    <div class="header-left">
        {logo_img_tag}
        <div>
            Chatbot Quadra
            <div class="title-sub">Assistente Inteligente</div>
        </div>
    </div>
    <div class="header-right">
        <a href="#" style="text-decoration:none;color:#2563eb;font-weight:600;border:1px solid rgba(37,99,235,0.12);padding:8px 12px;border-radius:10px;display:inline-block;">⚙ Configurações</a>
        <div style="text-align:right;font-size:0.9rem;color:var(--text);">
            <span style="font-weight:600;">{st.session_state.user_name}</span><br>
            <span style="font-weight:400;color:var(--muted);font-size:0.8rem;">{st.session_state.user_email}</span>
        </div>
        <div class="user-circle">{primeira_letra}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ====== SIDEBAR (Histórico) ======
with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="sidebar-bar" style="display:flex;align-items:center;justify-content:space-between;">
        <div class="sidebar-sub">Perguntas desta sessão</div>
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state.historico:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for pergunta_hist, _resp in st.session_state.historico:
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80:
                titulo = titulo[:80] + "…"
            st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

# ====== RENDER MENSAGENS (Chat Principal) ======
msgs_html = []
for pergunta, resposta in st.session_state.historico:
    p_html = linkify(pergunta)
    msgs_html.append(f'<div class="message-row user"><div class="bubble user">{p_html}</div></div>')
    if resposta:
        r_html = linkify(resposta)
        msgs_html.append(f'<div class="message-row assistant"><div class="bubble assistant">{r_html}</div></div>')

if st.session_state.awaiting_answer and st.session_state.answering_started:
    msgs_html.append('<div class="message-row assistant"><div class="bubble assistant"><span class="spinner"></span></div></div>')

if not msgs_html:
    msgs_html.append('<div style="color:#9ca3af; text-align:center; margin-top:20px;">.</div>')

msgs_html.append('<div id="chatEnd" style="height:1px;"></div>')

st.markdown(
    f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>',
    unsafe_allow_html=True
)

# ====== JS (Ajustes de Layout e Auto-scroll) ======
st.markdown("""
<script>
(function(){
    function ajustaEspaco(){
        const input = document.querySelector('[data-testid="stChatInput"]');
        const card = document.getElementById('chatCard');
        if(!input||!card) return;
        const rect = input.getBoundingClientRect();
        const gapVar = getComputedStyle(document.documentElement).getPropertyValue('--chat-safe-gap').trim();
        const gap = parseInt(gapVar || '24', 10);
        const alturaEfetiva = (window.innerHeight - rect.top) + gap; 
        card.style.paddingBottom = alturaEfetiva + 'px';
        card.style.scrollPaddingBottom = alturaEfetiva + 'px';
    }
    function autoGrow(){
        const ta = document.querySelector('[data-testid="stChatInput"] textarea');
        if(!ta) return;
        const MAX = 220;
        ta.style.height='auto';
        const desired = Math.min(ta.scrollHeight, MAX);
        ta.style.height = desired+'px';
        ta.style.overflowY=(ta.scrollHeight>MAX)?'auto':'hidden';
    }
    function scrollToEnd(smooth=true){
        const end = document.getElementById('chatEnd');
        if(!end) return;
        end.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'end'});
    }

    const ro = new ResizeObserver(()=>{ajustaEspaco();});
    ro.observe(document.body);
    
    window.addEventListener('load',()=>{ autoGrow(); ajustaEspaco(); scrollToEnd(false); });
    window.addEventListener('resize',()=>{autoGrow();ajustaEspaco();});
    
    document.addEventListener('input',(e)=>{
        if(e.target&&e.target.matches('[data-testid="stChatInput"] textarea')){
            autoGrow();ajustaEspaco();
        }
    });
    
    setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
    setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
    
    const card = document.getElementById('chatCard');
    if(card){
        const mo = new MutationObserver(()=>{ ajustaEspaco(); scrollToEnd(true); });
        mo.observe(card, {childList:true, subtree:false});
    }
})();
</script>
""", unsafe_allow_html=True)

# ====== INPUT (Componente nativo do Streamlit) ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")

# ====== FLUXO PRINCIPAL DO CHAT ======

# 1. Nova pergunta enviada
if pergunta and pergunta.strip():
    q = pergunta.strip()
    st.session_state.historico.append((q, ""))
    st.session_state.pending_index = len(st.session_state.historico)-1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer=True
    st.session_state.answering_started=False
    do_rerun()

# 2. Inicia o processo de resposta no próximo rerun (para mostrar o spinner)
if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started=True
    do_rerun()

# 3. Processa a resposta do backend
if st.session_state.awaiting_answer and st.session_state.answering_started:
    
    # Chama a função do backend
    resposta = responder_pergunta(st.session_state.pending_question)

    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        pergunta_fix = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (pergunta_fix, resposta)

    # Reseta o estado
    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    
    do_rerun()