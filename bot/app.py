# app.py - Frontend do Chatbot Quadra (Versão FINAL Corrigida)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape

# Importa a função de resposta do backend
try:
    from openai_backend import responder_pergunta
except ImportError:
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado."

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG DA PÁGINA ======
LOGO_PATH = "data/logo_quadra.png"
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ====== PRE-FLIGHT CSS (evita flash branco antes do restante do CSS) ======
st.markdown("""
<style>
html, body, .stApp { background:#0B1730 !important; }
</style>
""", unsafe_allow_html=True)

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== LOGOUT VIA QUERY PARAM (compatível com várias versões) ======
def _clear_query_params():
    try:
        st.query_params.clear()           # >= 1.33
    except Exception:
        st.experimental_set_query_params()  # legado

def _get_query_params():
    try:
        return dict(st.query_params)      # >= 1.33
    except Exception:
        return dict(st.experimental_get_query_params())  # legado

qp = _get_query_params()
if "logout" in qp:
    st.session_state.update({
        "authenticated": False,
        "user_name": "Usuário",
        "user_email": "nao_autenticado@quadra.com.vc",
        "awaiting_answer": False,
        "answering_started": False,
        "pending_index": None,
        "pending_question": None,
        "historico": []
    })
    _clear_query_params()
    do_rerun()

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

# Logo do header com tamanho inline (evita “flash” gigante)
if logo_b64:
    logo_img_tag = (
        f'<img alt="Logo Quadra" class="logo" '
        f'style="height:44px;width:auto;display:inline-block" '
        f'src="data:image/png;base64,{logo_b64}" />'
    )
else:
    logo_img_tag = '<span style="font-size: 2rem; color: #1C3364; font-weight: 900;">Q</span>'

def extract_name_from_email(email):
    if not email or "@" not in email:
        return "Usuário"
    local_part = email.split("@")[0]
    name_parts = re.sub(r'[\._]', ' ', local_part).split()
    return " ".join(p.capitalize() for p in name_parts)

# ====== ESTADO ======
if "historico" not in st.session_state:
    st.session_state.historico = []
st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)
# Modo: 'login' ou 'register'
st.session_state.setdefault("auth_mode", "login")
st.session_state.setdefault("just_registered", False)

# ====== TELAS DE AUTENTICAÇÃO ======

BASE_LOGIN_CSS = """
<style>
:root{ --login-max: 520px; --lift: 90px; }
.stApp{
    background: radial-gradient(1100px 620px at 50% 35%, #264E9A 0%, #16356B 50%, #0B1730 100%) !important;
    min-height:100vh !important; overflow:hidden !important;
}
header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer{ display:none !important; }

[data-testid="stAppViewContainer"] > .main{ height:100vh !important; }
.block-container{
    height:100%;
    display:flex; align-items:center; justify-content:center;
    padding:0 !important; margin:0 !important;
}

div[data-testid="column"]:has(#login_card_anchor) > div{
    background:transparent !important; box-shadow:none !important; border-radius:0; padding:0;
    text-align:center;
}

.login-stack{
    width:min(92vw, var(--login-max));
    margin:0 auto;
    text-align:center;
    transform: translateY(calc(var(--lift) * -1));
}

.login-title{
    display:block;
    text-align:center;
    font-size:1.5rem; font-weight:800; letter-spacing:.2px;
    color:#F5F7FF; margin:6px 0 6px;
    text-shadow: 0 1px 2px rgba(0,0,0,.35);
}

.login-sub{
    display:block; width:100%; text-align:center; font-size:1rem; color:#C9D7FF; margin:0 0 16px;
}

/* Inputs */
.login-stack [data-testid="stTextInput"]{ width:100%; margin:0 auto; }
.login-stack [data-testid="stTextInput"] > label{ display:none !important; }
.login-stack [data-testid="stTextInput"] input,
.login-stack [data-testid="stPassword"] input{
    width:100%; height:48px; font-size:1rem;
    border-radius:10px; border:1px solid rgba(255,255,255,.2) !important;
    background:#ffffff !important; color:#111827 !important;
    box-shadow:0 6px 20px rgba(6,16,35,.30);
}

/* ===== Reset dos botões na área de login: formato de botão discreto por padrão ===== */
.login-stack .stButton > button{
    height:44px !important; padding:0 16px !important;
    border-radius:10px !important; font-weight:600 !important; font-size:0.95rem !important;
    background:rgba(255,255,255,.08) !important; color:#E6EEFF !important;
    border:1px solid rgba(255,255,255,.18) !important;
    box-shadow:0 6px 16px rgba(7,22,50,.35) !important;
    text-decoration:none !important;
}
.login-stack .stButton > button:hover{ filter:brightness(1.06); }

/* ===== Botão primário (destaque) ===== */
.login-actions{ display:flex; justify-content:center; gap:12px; flex-wrap:wrap; }
.login-actions .stButton > button{
    height:48px !important; padding:0 20px !important;
    border-radius:10px !important; font-weight:700 !important; font-size:1rem !important;
    background:#2E5CB5 !important; color:#ffffff !important; border:1px solid rgba(255,255,255,.20) !important;
    box-shadow:0 10px 24px rgba(11,45,110,.45) !important;
}

/* ===== Botões secundários (harmonizados e discretos) ===== */
.secondary-actions{ width:100%; display:flex; justify-content:center; margin-top:28px; }
.secondary-actions .stButton > button{
    background:rgba(255,255,255,.08) !important; color:#D7E3FF !important;
    border:1px solid rgba(255,255,255,.18) !important; height:44px !important; padding:0 16px !important;
    box-shadow:0 6px 16px rgba(7,22,50,.35) !important;
}
.secondary-actions .stButton > button:hover{ background:rgba(255,255,255,.12) !important; }

@media (max-width: 480px){
    :root{ --lift: 28px; }
    .login-title{ font-size:1.4rem; }
}
</style>
"""

def render_login_screen():
    """Tela de Login"""
    st.markdown(BASE_LOGIN_CSS, unsafe_allow_html=True)
    col_esq, col_mid, col_dir = st.columns([1, 1, 1])
    with col_mid:
        st.markdown('<div id="login_card_anchor"></div>', unsafe_allow_html=True)
        st.markdown('<div class="login-stack">', unsafe_allow_html=True)

        if logo_b64:
            st.markdown(
                f'''
                <img alt="Logo Quadra"
                     src="data:image/png;base64,{logo_b64}"
                     style="height:88px;width:auto;display:block;margin:0 auto 14px;
                            filter:drop-shadow(0 6px 16px rgba(0,0,0,.35));" />
                ''',
                unsafe_allow_html=True
            )

        st.markdown('<span class="login-title">Quadra Engenharia</span>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">Entre com seu e-mail para começar a conversar com nosso assistente</div>',
                    unsafe_allow_html=True)

        # sucesso pós-cadastro
        if st.session_state.get("just_registered"):
            st.success("Usuário cadastrado com sucesso. Faça login para entrar.")
            st.session_state.just_registered = False

        # ---- ENTER sem form ----
        def _try_login():
            email_val = (st.session_state.get("login_email") or "").strip().lower()
            if "@" not in email_val:
                st.session_state["login_error"] = "Por favor, insira um e-mail válido."
                return
            if not email_val.endswith("@quadra.com.vc"):
                st.session_state["login_error"] = "Acesso restrito. Use seu e-mail **@quadra.com.vc**."
                return
            st.session_state["login_error"] = ""
            st.session_state.authenticated = True
            st.session_state.user_email = email_val
            st.session_state.user_name = extract_name_from_email(email_val)

        st.text_input(
            "E-mail",
            key="login_email",
            placeholder="seu.nome@quadra.com.vc",
            label_visibility="collapsed",
            on_change=_try_login,  # Enter
        )

        # Botão ENTRAR (primário/destaque)
        st.markdown('<div class="login-actions">', unsafe_allow_html=True)
        if st.button("Entrar", type="primary", key="btn_login"):
            _try_login()
            do_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # Botão secundário centralizado: Cadastrar usuário
        st.markdown('<div class="secondary-actions">', unsafe_allow_html=True)
        col_a, col_b, col_c = st.columns([1,1,1])
        with col_b:
            if st.button("Cadastrar usuário", key="btn_go_register"):
                st.session_state.auth_mode = "register"
                do_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])

        st.markdown('</div>', unsafe_allow_html=True)

    st.stop()

def render_register_screen():
    """Tela de Cadastro (e-mail + senha)"""
    st.markdown(BASE_LOGIN_CSS, unsafe_allow_html=True)
    col_esq, col_mid, col_dir = st.columns([1, 1, 1])
    with col_mid:
        st.markdown('<div id="login_card_anchor"></div>', unsafe_allow_html=True)
        st.markdown('<div class="login-stack">', unsafe_allow_html=True)

        if logo_b64:
            st.markdown(
                f'''
                <img alt="Logo Quadra"
                     src="data:image/png;base64,{logo_b64}"
                     style="height:88px;width:auto;display:block;margin:0 auto 14px;
                            filter:drop-shadow(0 6px 16px rgba(0,0,0,.35));" />
                ''',
                unsafe_allow_html=True
            )

        st.markdown('<span class="login-title">Criar conta</span>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">Preencha os campos para cadastrar seu acesso</div>',
                    unsafe_allow_html=True)

        email = st.text_input("E-mail corporativo", key="reg_email",
                              placeholder="seu.nome@quadra.com.vc", label_visibility="collapsed")
        senha = st.text_input("Senha", key="reg_senha", type="password", placeholder="Crie uma senha")
        confirma = st.text_input("Confirmar senha", key="reg_confirma", type="password", placeholder="Repita a senha")

        # Botão principal Cadastrar (primário)
        st.markdown('<div class="login-actions">', unsafe_allow_html=True)
        criar = st.button("Cadastrar", type="primary", key="btn_register")
        st.markdown('</div>', unsafe_allow_html=True)

        # Botão secundário: Voltar para login
        st.markdown('<div class="secondary-actions">', unsafe_allow_html=True)
        col_a, col_b, col_c = st.columns([1,1,1])
        with col_b:
            voltar = st.button("Voltar para login", key="btn_back_login")
        st.markdown('</div>', unsafe_allow_html=True)

        if voltar:
            st.session_state.auth_mode = "login"
            do_rerun()

        if criar:
            email_ok = email and "@" in email and email.strip().lower().endswith("@quadra.com.vc")
            if not email_ok:
                st.error("Use um e-mail válido **@quadra.com.vc**.")
            elif not senha or len(senha) < 6:
                st.error("A senha deve ter pelo menos 6 caracteres.")
            elif senha != confirma:
                st.error("As senhas não conferem.")
            else:
                # Plugue seu backend aqui (Supabase/DB). Por enquanto, só volta ao login com aviso.
                st.session_state.login_email = email.strip().lower()
                st.session_state.auth_mode = "login"
                st.session_state.just_registered = True
                do_rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    st.stop()

# =================================================================
#                         FLUXO PRINCIPAL
# =================================================================

# Se não autenticado, mostra login ou cadastro
if not st.session_state.authenticated:
    if st.session_state.auth_mode == "register":
        render_register_screen()
    else:
        render_login_screen()

# ====== MARCAÇÃO ======

def formatar_markdown_basico(text: str) -> str:
    """Converte um subset simples de markdown para HTML seguro (links, **negrito**, *itálico*, quebras de linha)."""
    if not text:
        return ""

    # Escapa HTML de origem para evitar injeção
    safe = escape(text)

    # Links (usa lambda para não ter problema de \1 literal)
    safe = re.sub(
        r'(https?://[^\s<>"\]]+)',
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>',
        safe
    )

    # **negrito** e *itálico*
    safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
    safe = re.sub(r'\*(.+?)\*', r'<i>\1</i>', safe)

    # Quebra de linha real
    safe = safe.replace('\n', '<br>')
    return safe

def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

# ====== CSS (Chat) ======
st.markdown(f"""
<style>
* {{ box-sizing: border-box }}
html, body {{ margin: 0; padding: 0 }}
img {{ max-width: 100%; height: auto; display: inline-block }}
img.logo {{ height: 44px !important; width: auto !important }}

:root{{
    --content-max-width: min(96vw, 1400px);
    --header-height: 68px;
    --chat-safe-gap: 300px;
    --card-height: calc(100dvh - var(--header-height) - 24px);
    --input-max: 900px;
    --input-bottom: 60px;

    --bg:#1C1F26; --panel:#0B0D10; --panel-header:#14171C; --panel-alt:#1C1F26; --border:#242833;
    --text:#E5E7EB; --text-dim:#C9D1D9; --muted:#9AA4B2;
    --link:#B9C0CA; --link-hover:#FFFFFF;
    --bubble-user:#222833; --bubble-assistant:#232833;
    --input-bg:#1E222B; --input-border:#323949;
    --sidebar-w:270px;
    --sidebar-items-top-gap: -45px; --sidebar-sub-top-gap: -30px; --sidebar-list-start-gap: 3px;
}}

header[data-testid="stHeader"]{{ display:none !important }}
div[data-testid="stToolbar"]{{ display:none !important }}
#MainMenu, footer{{ visibility:hidden; height:0 !important }}

html, body, .stApp, main, .stMain, .block-container, [data-testid="stAppViewContainer"]{{
    height:100dvh !important; max-height:100dvh !important; overflow:hidden !important; overscroll-behavior:none;
}}
.block-container{{ padding:0 !important; min-height:0 !important }}
.stApp{{ background:var(--bg) !important; color:var(--text) !important }}

.header{{
    position:fixed; inset:0 0 auto 0; height:var(--header-height);
    display:flex; align-items:center; justify-content:space-between;
    padding:10px 16px; background:var(--panel-header); z-index:1000; border-bottom:1px solid var(--border);
}}
.header-left{{ display:flex; align-items:center; gap:10px; font-weight:600; color:var(--text) }}
.header-left .title-sub{{ font-weight:500; font-size:.85rem; color:var(--muted); margin-top:-4px }}
.header-right{{ display:flex; align-items:center; gap:12px; color:var(--text) }}
.header a{{ color:var(--link) !important; text-decoration:none; border:1px solid var(--border); padding:8px 12px; border-radius:10px; display:inline-block; }}
.header a:hover{{ color:var(--link-hover) !important; border-color:#3B4250 }}
.user-circle {{ width: 32px; height: 32px; border-radius: 50%; background: #007bff; color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 1rem; }}

section[data-testid="stSidebar"]{{ position:fixed !important; top:var(--header-height) !important; left:0 !important; height:calc(100dvh - var(--header-height)) !important; width:var(--sidebar-w) !important; min-width:var(--sidebar-w) !important; margin:0 !important; padding:0 !important; background:var(--panel) !important; border-right:1px solid var(--border); z-index:900 !important; transform:none !important; visibility:visible !important; overflow:hidden !important; color:var(--text); }}
section[data-testid="stSidebar"] > div{{ padding-top:0 !important; margin-top:0 !important; }}
div[data-testid="stSidebarContent"]{{ padding-top:0 !important; margin-top:0 !important; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{ padding-top:0 !important; margin-top:0 !important; }}

section[data-testid="stSidebar"] .sidebar-header{{ margin-top: var(--sidebar-items-top-gap) !important; }}
.sidebar-bar p, .sidebar-header p{{ margin: 0 !important; line-height: 1.15 !important; }}
.sidebar-bar{{ margin-top: var(--sidebar-sub-top-gap) !important; }}
.hist-row:first-of-type{{ margin-top: var(--sidebar-list-start-gap) !important; }}

div[data-testid="stAppViewContainer"]{{ margin-left:var(--sidebar-w) !important }}

.sidebar-header{{ font-size:1.1rem; font-weight:700; letter-spacing:.02em; color:var(--text); margin:0 4px -2px 2px }}
.sidebar-sub{{ font-size:.88rem; color:var(--muted) }}
.hist-empty{{ color:var(--muted); font-size:.9rem; padding:8px 10px }}
.hist-row{{ padding:6px 6px; font-size:1.1rem; color:var(--text-dim) !important; line-height:1.35; border-radius:8px }}
.hist-row + .hist-row{{ margin-top:6px }}
.hist-row:hover{{ background:#161a20 }}

.content{{ max-width:var(--content-max-width); margin:var(--header-height) auto 0; padding:8px }}
#chatCard, .chat-card{{ position:relative; z-index:50 !important; background:var(--bg) !important; border:none !important; border-radius:12px 12px 0 0 !important; box-shadow:none !important; padding:20px; height:var(--card-height); overflow-y:auto; scroll-behavior:smooth; padding-bottom:var(--chat-safe-gap); scroll-padding-bottom:var(--chat-safe-gap); color:var(--text); }}
#chatCard *, .chat-card *{{ position:relative; z-index:51 !important }}

.message-row{{ display:flex !important; margin:12px 4px; scroll-margin-bottom:calc(var(--chat-safe-gap) + 16px) }}
.message-row.user{{ justify-content:flex-end }}
.message-row.assistant{{ justify-content:flex-start }}
.bubble{{ max-width:88%; padding:14px 16px; border-radius:12px; font-size:15px; line-height:1.45; color:var(--text); word-wrap:break-word; border:1px solid transparent !important; box-shadow:none !important; }}
.bubble.user{{ background:var(--bubble-user); border-bottom-right-radius:6px }}
.bubble.assistant{{ background:var(--bubble-assistant); border-bottom-left-radius:6px }}
.chat-card a{{ color:var(--link); text-decoration:underline }} .chat-card a:hover{{ color:var(--link-hover) }}

[data-testid="stChatInput"]{{ position:fixed !important; left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2) !important; transform:translateX(-50%) !important; bottom:var(--input-bottom) !important; width:min(var(--input-max), 96vw) !important; z-index:5000 !important; background:transparent !important; border:none !important; box-shadow:none !important; padding:0 !important; }}
[data-testid="stChatInput"] *{{ background:transparent !important; color:var(--text) !important; }}
[data-testid="stChatInput"] > div{{ background:var(--input-bg) !important; border:1px solid var(--input-border) !important; border-radius:999px !important; box-shadow:0 10px 24px rgba(0,0,0,.35) !important; overflow:hidden; transition:border-color .12s ease, box-shadow .12s ease; }}
[data-testid="stChatInput"] textarea{{ width:100% !important; border:none !important; border-radius:999px !important; padding:18px 20px !important; font-size:16px !important; outline:none !important; height:auto !important; min-height:44px !important; max-height:220px !important; overflow-y:hidden !important; caret-color:#ffffff !important; }}
[data-testid="stChatInput"] textarea::placeholder{{ color:var(--muted) !important }}
[data-testid="stChatInput"] textarea:focus::placeholder{{ color:transparent !important; opacity:0 !important }}
[data-testid="stChatInput"] button{{ margin-right:8px !important; border:none !important; background:transparent !important; color:var(--text-dim) !important; }}
[data-testid="stChatInput"] svg{{ fill:currentColor !important }}

[data-testid="stBottomBlockContainer"], [data-testid="stBottomBlockContainer"] > div, [data-testid="stBottomBlockContainer"] [data-testid="stVerticalBlock"], [data-testid="stBottomBlockContainer"] [class*="block-container"], [data-testid="stBottomBlockContainer"]::before, [data-testid="stBottomBlockContainer"]::after{{ background:transparent !important; box-shadow:none !important; border:none !important; }}
[data-testid="stBottomBlockContainer"]{{ padding:0 !important; margin:0 !important; height:0 !important; min-height:0 !important; }}

[data-testid="stDecoration"], [data-testid="stStatusWidget"]{{ display:none !important }}
*::-webkit-scrollbar{{ width:10px; height:10px }}
*::-webkit-scrollbar-thumb{{ background:#2C3340; border-radius:8px }}
*::-webkit-scrollbar-track{{ background:#0F1115 }}

.spinner{{ width:16px; height:16px; border:2px solid rgba(37,99,235,.25); border-top-color:#2563eb; border-radius:50%; display:inline-block; animation:spin .8s linear infinite; }}
@keyframes spin{{ to{{ transform:rotate(360deg) }} }}
</style>
""", unsafe_allow_html=True)

# ====== HEADER ======
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
        <a href="?logout=1" target="_self"
          style="text-decoration:none;background:transparent;
          border:1px solid rgba(255,255,255,0.14);
          color:#e5e7eb;font-weight:600;padding:8px 12px;border-radius:10px;
          display:inline-block;cursor:pointer;">
   Sair
        </a>
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

# ====== RENDER MENSAGENS ======
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

# ====== JS (layout + autoscroll) ======
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
if pergunta and pergunta.strip():
    q = pergunta.strip()
    st.session_state.historico.append((q, ""))
    st.session_state.pending_index = len(st.session_state.historico)-1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer=True
    st.session_state.answering_started=False
    do_rerun()

if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started=True
    do_rerun()

if st.session_state.awaiting_answer and st.session_state.answering_started:
    resposta = responder_pergunta(st.session_state.pending_question)
    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        pergunta_fix = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (pergunta_fix, resposta)

    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    do_rerun()
