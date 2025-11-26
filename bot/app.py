# app.py - Frontend do Chatbot Quadra (Versão FINAL Corrigida + Supabase)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape

# ====== BACKEND LLM ======
try:
    from openai_backend import responder_pergunta
except ImportError:
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado."

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== SUPABASE (tolerante a falhas) ======
SB_URL = None
SB_KEY = None
SITE_URL = None
sb = None
try:
    from supabase import create_client, Client  # pip install supabase
    SB_URL = st.secrets.get("supabase", {}).get("url")
    SB_KEY = st.secrets.get("supabase", {}).get("anon_key")
    SITE_URL = st.secrets.get("supabase", {}).get("site_url", "http://localhost:8501")
    if SB_URL and SB_KEY:
        sb = create_client(SB_URL, SB_KEY)
except Exception:
    sb = None  # segue sem Supabase

# ====== CONFIG DA PÁGINA ======
LOGO_PATH = "data/logo_quadra.png"
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ====== PRE-FLIGHT CSS (estilo ChatGPT, antes de tudo) ======
st.markdown("""
<style>
html, body, .stApp {
    background:#202123 !important;
    color:#ECECF1 !important;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
</style>
""", unsafe_allow_html=True)


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

# Logo do header com tamanho inline
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

# === Helpers de erro ===
def _extract_err_msg(err) -> str:
    try:
        msg = getattr(err, "message", None) or getattr(err, "error", None)
        if isinstance(msg, str) and msg.strip():
            return msg
        if getattr(err, "args", None):
            a0 = err.args[0]
            if isinstance(a0, dict):
                return a0.get("msg") or a0.get("message") or str(a0)
            return str(a0)
    except Exception:
        pass
    return str(err)


def _friendly_auth_error(msg: str) -> str:
    low = (msg or "").lower()
    if "email not confirmed" in low or "not confirmed" in low or "confirm" in low:
        return "E-mail não confirmado. Abra o link de confirmação que foi enviado para o seu e-mail."
    if "invalid login credentials" in low or "invalid" in low:
        return "Credenciais inválidas. Verifique e-mail e senha."
    if "rate limit" in low:
        return "Muitas tentativas. Aguarde um pouco e tente novamente."
    return msg or "Falha na autenticação."

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
# IDs para Supabase
st.session_state.setdefault("user_id", None)
st.session_state.setdefault("conversation_id", None)
# Suporte a título da conversa (1ª pergunta) e lista local
st.session_state.setdefault("conversations_list", [])
st.session_state.setdefault("_title_set", False)
st.session_state.setdefault("_sb_last_error", None)
# Histórico global (Supabase) para a sidebar
st.session_state.setdefault("sidebar_history", [])
st.session_state.setdefault("_sidebar_loaded", False)

# ====== HELPERS SUPABASE ======
def _title_from_first_question(q: str) -> str:
    if not q:
        return "Nova conversa"
    t = re.sub(r"\s+", " ", q.strip())
    return (t[:60] + "…") if len(t) > 60 else t


def get_or_create_conversation():
    """
    Cria uma conversa no Supabase e memoriza o ID na sessão.
    IMPORTANTE: envia user_id para satisfazer a policy WITH CHECK (user_id = auth.uid()).
    """
    if not sb or not st.session_state.get("user_id"):
        return None
    if st.session_state.get("conversation_id"):
        return st.session_state["conversation_id"]

    payload = {
        "user_id": st.session_state.user_id,
        "title": f"Sessão de {st.session_state.user_name}",
    }
    try:
        r = sb.table("conversations").insert(payload).execute()
        cid = r.data[0]["id"]
        st.session_state["conversation_id"] = cid
        st.session_state.conversations_list.insert(0, {"id": cid, "title": payload["title"]})
        return cid
    except Exception as e:
        st.session_state["_sb_last_error"] = f"Supabase: conv.insert: {_extract_err_msg(e)}"
        return None


def update_conversation_title_if_first_question(cid, first_question: str):
    if not sb or not cid or not first_question or st.session_state.get("_title_set"):
        return
    title = _title_from_first_question(first_question)
    try:
        sb.table("conversations").update({"title": title}).eq("id", cid).execute()
        for it in st.session_state.conversations_list:
            if it.get("id") == cid:
                it["title"] = title
                break
        st.session_state["_title_set"] = True
    except Exception as e:
        st.session_state["_sb_last_error"] = f"conv.update_title: {_extract_err_msg(e)}"


def save_message(cid, role, content):
    if not sb or not cid or not content:
        return
    try:
        sb.table("messages").insert({
            "conversation_id": cid,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        st.session_state["_sb_last_error"] = f"msg.insert: {_extract_err_msg(e)}"


def load_sidebar_history_from_supabase():
    if not sb or not st.session_state.get("user_id"):
        return
    try:
        res = (
            sb.table("messages")
            .select("content, role, created_at, conversations!inner(user_id)")
            .eq("role", "user")
            .eq("conversations.user_id", st.session_state.user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        rows = res.data or []
        rows_sorted = sorted(rows, key=lambda r: r.get("created_at") or "")
        st.session_state.sidebar_history = [r["content"] for r in rows_sorted]
    except Exception as e:
        st.session_state["_sb_last_error"] = f"sidebar.load: {_extract_err_msg(e)}"

# ====== LOGOUT VIA QUERY PARAM ======
def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()


def _get_query_params():
    try:
        return dict(st.query_params)
    except Exception:
        return dict(st.experimental_get_query_params())


qp = _get_query_params()
if "logout" in qp:
    try:
        if sb:
            try:
                sb.postgrest.auth(None)
            except Exception:
                pass
            sb.auth.sign_out()
    except Exception:
        pass

    st.session_state.update({
        "authenticated": False,
        "user_name": "Usuário",
        "user_email": "nao_autenticado@quadra.com.vc",
        "awaiting_answer": False,
        "answering_started": False,
        "pending_index": None,
        "pending_question": None,
        "historico": [],
        "user_id": None,
        "conversation_id": None,
        "_title_set": False,
        "_sb_last_error": None,
        "conversations_list": [],
        "sidebar_history": [],
        "_sidebar_loaded": False,
    })
    _clear_query_params()
    do_rerun()

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

/* ===== Reset geral de botões na área de login ===== */
.login-stack .stButton > button{
    height:44px !important; padding:0 16px !important;
    border-radius:10px !important; font-weight:600 !important; font-size:0.95rem !important;
    background:rgba(255,255,255,.08) !important; color:#E6EEFF !important;
    border:1px solid rgba(255,255,255,.18) !important;
    box-shadow:0 6px 16px rgba(7,22,50,.35) !important;
    text-decoration:none !important;
}
.login-stack .stButton > button:hover{ filter:brightness(1.06); }

/* ===== Botão primário (destaque) - ENTRAR / CADASTRAR ===== */
.login-actions{ display:flex; justify-content:center; gap:12px; flex-wrap:wrap; }
.login-actions .stButton > button{
    height:48px !important; padding:0 20px !important;
    border-radius:10px !important; font-weight:700 !important; font-size:1rem !important;
    background:#2E5CB5 !important; color:#ffffff !important; border:1px solid rgba(255,255,255,.20) !important;
    box-shadow:0 10px 24px rgba(11,45,110,.45) !important;
}

/* ===== Contêiner dos botões SECUNDÁRIOS ===== */
.secondary-actions{
    width:100%; display:flex; justify-content:center; margin-top:28px;
}

/* ===== Estilo GLOBAL para botões kind="secondary"
   (Cadastrar usuário / Voltar para login) ===== */
button[kind="secondary"],
button[data-testid="baseButton-secondary"]{
    height:46px !important; padding:0 22px !important;
    border-radius:999px !important;
    font-weight:600 !important; font-size:0.96rem !important;
    background:rgba(15,23,42,0.45) !important;
    color:#E5ECFF !important;
    border:1px solid rgba(148,163,184,0.70) !important;
    box-shadow:0 8px 20px rgba(0,0,0,.30), inset 0 1px 0 rgba(255,255,255,.10) !important;
    transition: transform .12s ease, box-shadow .12s ease, border-color .12s ease, filter .12s ease !important;
}
button[kind="secondary"]:hover,
button[data-testid="baseButton-secondary"]:hover{
    filter:brightness(1.04);
    transform:translateY(-1px);
    box-shadow:0 12px 24px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.12) !important;
    border-color:rgba(129,140,248,0.9) !important;
}
button[kind="secondary"]:active,
button[data-testid="baseButton-secondary"]:active{
    transform:translateY(0);
    box-shadow:0 6px 16px rgba(0,0,0,.26) !important;
}
button[kind="secondary"]:focus,
button[data-testid="baseButton-secondary"]:focus{
    outline:none !important;
    box-shadow:0 0 0 3px rgba(59,130,246,.35), 0 8px 20px rgba(0,0,0,.26) !important;
}

/* ===== Responsivo ===== */
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
        st.markdown(
            '<div class="login-sub">Entre com seu e-mail para começar a conversar com nosso assistente</div>',
            unsafe_allow_html=True
        )

        if st.session_state.get("just_registered"):
            st.success("Usuário cadastrado com sucesso. Faça login para entrar.")
            st.session_state.just_registered = False

        def _try_login():
            email_val = (st.session_state.get("login_email") or "").strip().lower()
            pwd_val = (st.session_state.get("login_senha") or "")
            if "@" not in email_val:
                st.session_state["login_error"] = "Por favor, insira um e-mail válido."
                return
            if not email_val.endswith("@quadra.com.vc"):
                st.session_state["login_error"] = "Acesso restrito. Use seu e-mail **@quadra.com.vc**."
                return
            if not pwd_val:
                st.session_state["login_error"] = "Digite a senha."
                return

            if pwd_val == "quadra123":
                try:
                    if sb:
                        sb.postgrest.auth(None)
                except Exception:
                    pass
                st.session_state.update({
                    "login_error": "",
                    "authenticated": True,
                    "user_email": email_val,
                    "user_name": extract_name_from_email(email_val),
                    "user_id": None,
                    "conversation_id": None,
                    "_title_set": False,
                    "conversations_list": [],
                    "sidebar_history": [],
                    "_sidebar_loaded": False,
                })
                return

            if not sb:
                st.session_state["login_error"] = "Serviço de autenticação indisponível no momento."
                return
            try:
                try:
                    sb.postgrest.auth(None)
                except Exception:
                    pass
                try:
                    sb.auth.sign_out()
                except Exception:
                    pass

                res = sb.auth.sign_in_with_password({"email": email_val, "password": pwd_val})
                user = getattr(res, "user", None)
                if user is None and isinstance(res, dict):
                    user = res.get("user")

                if not user or not getattr(user, "id", None):
                    raise Exception("Resposta inválida do Auth.")

                session_obj = getattr(res, "session", None)
                if session_obj is None and isinstance(res, dict):
                    session_obj = res.get("session")
                access_token = getattr(session_obj, "access_token", None) if session_obj else None
                if access_token:
                    try:
                        sb.postgrest.auth(access_token)
                    except Exception:
                        pass

                st.session_state["login_error"] = ""
                st.session_state.authenticated = True
                st.session_state.user_email = email_val
                st.session_state.user_name = extract_name_from_email(email_val)
                st.session_state.user_id = user.id
                st.session_state.conversation_id = None
                st.session_state._title_set = False
                st.session_state.conversations_list = []
                st.session_state.sidebar_history = []
                st.session_state._sidebar_loaded = False

                try:
                    sb.table("profiles").upsert({"id": user.id, "email": email_val}).execute()
                except Exception:
                    pass

            except Exception as e:
                raw = _extract_err_msg(e)
                st.session_state["login_error"] = _friendly_auth_error(raw)

        st.markdown('<div style="color:#FFFFFF;font-weight:600;margin:6px 2px 6px;">Email</div>',
                    unsafe_allow_html=True)
        st.text_input(
            label="", key="login_email",
            placeholder="seu.nome@quadra.com.vc",
            label_visibility="collapsed"
        )

        st.markdown('<div style="color:#FFFFFF;font-weight:600;margin:10px 2px 6px;">Senha</div>',
                    unsafe_allow_html=True)
        st.text_input(
            label="", key="login_senha",
            type="password", placeholder="Digite sua senha",
            label_visibility="collapsed",
            on_change=_try_login
        )

        st.markdown('<div class="login-actions">', unsafe_allow_html=True)
        if st.button("Entrar", type="primary", key="btn_login"):
            _try_login()
            do_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # Botão secundário: Cadastrar usuário
        st.markdown('<div class="secondary-actions">', unsafe_allow_html=True)
        col_a, col_b, col_c = st.columns([1, 1, 1])
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
        st.markdown('<div class="login-stack reg">', unsafe_allow_html=True)

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

        st.markdown('<div style="color:#FFFFFF;font-weight:600;margin:6px 2px 6px;">Email</div>',
                    unsafe_allow_html=True)
        email = st.text_input(
            label="", key="reg_email",
            placeholder="seu.nome@quadra.com.vc",
            label_visibility="collapsed"
        )

        st.markdown('<div style="color:#FFFFFF;font-weight:600;margin:6px 2px 6px;">Senha</div>',
                    unsafe_allow_html=True)
        senha = st.text_input(
            label="", key="reg_senha",
            type="password", placeholder="Crie uma senha",
            label_visibility="collapsed"
        )

        st.markdown('<div style="color:#FFFFFF;font-weight:600;margin:6px 2px 6px;">Confirmar Senha</div>',
                    unsafe_allow_html=True)
        confirma = st.text_input(
            label="", key="reg_confirma",
            type="password", placeholder="Repita a senha",
            label_visibility="collapsed"
        )

        st.markdown('<div class="login-actions">', unsafe_allow_html=True)
        criar = st.button("Cadastrar", type="primary", key="btn_register")
        st.markdown('</div>', unsafe_allow_html=True)

        # Botão secundário: Voltar para login
        st.markdown('<div class="secondary-actions">', unsafe_allow_html=True)
        col_a, col_b, col_c = st.columns([1, 1, 1])
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
                if sb:
                    try:
                        sb.auth.sign_up({
                            "email": email.strip().lower(),
                            "password": senha,
                            "options": {"email_redirect_to": SITE_URL or "http://localhost:8501"}
                        })
                        st.success("Cadastro realizado. Verifique seu e-mail (ou faça login se a confirmação estiver desativada).")
                    except Exception as e:
                        st.error(f"Erro ao cadastrar: {_friendly_auth_error(_extract_err_msg(e))}")
                        st.stop()
                st.session_state.login_email = email.strip().lower()
                st.session_state.auth_mode = "login"
                st.session_state.just_registered = True
                do_rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    st.stop()

# =================================================================
#                         FLUXO PRINCIPAL
# =================================================================

if not st.session_state.authenticated:
    if st.session_state.auth_mode == "register":
        render_register_screen()
    else:
        render_login_screen()

if sb and st.session_state.get("user_id") and not st.session_state.get("_sidebar_loaded"):
    load_sidebar_history_from_supabase()
    st.session_state["_sidebar_loaded"] = True

# ====== MARCAÇÃO ======
def formatar_markdown_basico(text: str) -> str:
    if not text:
        return ""
    safe = escape(text)
    safe = re.sub(
        r'(https?://[^\s<>"\]]+)',
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>',
        safe
    )
    safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
    safe = re.sub(r'\*(.+?)\*', r'<i>\1</i>', safe)
    return safe.replace('\n', '<br>')


def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

# ====== CSS (Chat) ======
st.markdown(f"""
<style>
* {{ box-sizing: border-box }}
html, body {{ margin: 0; padding: 0 }}
img {{ max-width: 100%; height: auto; display: inline-block }}
img.logo {{ height: 44px !important; width: auto !important }}

/* Paleta ChatGPT dark */
:root{{
    --content-max-width: min(96vw, 1400px);
    --header-height: 68px;
    --chat-safe-gap: 300px;
    --card-height: calc(100dvh - var(--header-height) - 24px);
    --input-max: 900px;
    --input-bottom: 60px;
                    
    --bg:#202123;
    --panel:#050509;
    --panel-header:#26272F;
    --panel-alt:#343541;

    --border:#565869;

    --text:#ECECF1;
    --text-dim:#D1D5DB;
    --muted:#9CA3AF;

    /* links em azul */
    --link:#60A5FA;
    --link-hover:#93C5FD;

    --bubble-user:#343541;
    --bubble-assistant:#444654;

    --input-bg:#26272F;
    --input-border:#565869;

    --sidebar-w:270px;
    --sidebar-items-top-gap: -45px;
    --sidebar-sub-top-gap: -30px;
    --sidebar-list-start-gap: 3px;
}}

body, .stApp {{
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    background:var(--bg) !important;
    color:var(--text) !important;
}}

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

/* HEADER */
.header{{
    position:fixed;
    inset:0 0 auto 0;
    height:var(--header-height);
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:10px 16px;
    background:var(--panel-header);
    z-index:1000;
    border-bottom:1px solid var(--border);
}}
.header-left{{
    display:flex;
    align-items:center;
    gap:10px;
    font-weight:600;
    color:var(--text);
}}
.header-left .title-sub{{
    font-weight:500;
    font-size:.85rem;
    color:var(--muted);
    margin-top:-4px;
}}
.header-right{{
    display:flex;
    align-items:center;
    gap:12px;
    color:var(--text);
}}

/* Botão Sair */
.header a{{
    color:#FFFFFF !important;
    text-decoration:none;
    border:1px solid #2563EB;
    padding:8px 12px;
    border-radius:10px;
    display:inline-block;
    background:#3B82F6;
    font-weight:600;
    cursor:pointer;
}}
.header a:hover{{
    color:#FFFFFF !important;
    border-color:#1D4ED8;
    background:#2563EB;
}}

/* Avatar */
.user-circle {{
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #3B82F6;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 1rem;
}}

/* SIDEBAR */
section[data-testid="stSidebar"]{{
    position:fixed !important;
    top:var(--header-height) !important;
    left:0 !important;
    height:calc(100dvh - var(--header-height)) !important;
    width:var(--sidebar-w) !important;
    min-width:var(--sidebar-w) !important;
    margin:0 !important;
    padding:0 !important;
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

section[data-testid="stSidebar"] .sidebar-header{{ margin-top: var(--sidebar-items-top-gap) !important; }}
.sidebar-bar p, .sidebar-header p{{ margin: 0 !important; line-height: 1.15 !important; }}
.sidebar-bar{{ margin-top: var(--sidebar-sub-top-gap) !important; }}
.hist-row:first-of-type{{ margin-top: var(--sidebar-list-start-gap) !important; }}

div[data-testid="stAppViewContainer"]{{ margin-left:var(--sidebar-w) !important }}

/* textos histórico */
.sidebar-header{{
    font-size:0.9rem;
    font-weight:600;
    letter-spacing:.02em;
    color:var(--text);
    margin:0 4px -2px 2px;
}}
.sidebar-sub{{
    font-size:0.78rem;
    color:var(--muted);
    font-weight:400;
}}
.hist-empty{{
    color:var(--muted);
    font-size:.9rem;
    padding:8px 10px;
}}
.hist-row{{
    padding:6px 6px;
    font-size:0.9rem;
    font-weight:400;
    color:var(--text-dim) !important;
    line-height:1.35;
    border-radius:8px;
}}
.hist-row + .hist-row{{ margin-top:6px }}
.hist-row:hover{{ background:#2A2B32 }}

/* ÁREA CENTRAL */
.content{{
    max-width:var(--content-max-width);
    margin:var(--header-height) auto 0;
    padding:8px;
}}
#chatCard, .chat-card{{
    position:relative;
    z-index:50 !important;
    background:var(--bg) !important;
    border:none !important;
    border-radius:12px 12px 0 0 !important;
    box-shadow:none !important;
    padding:20px;
    height:var(--card-height);
    overflow-y:auto;
    scroll-behavior:smooth;
    padding-bottom:var(--chat-safe-gap);
    scroll-padding-bottom:var(--chat-safe-gap);
    color:var(--text);
}}
#chatCard *, .chat-card *{{ position:relative; z-index:51 !important }}

.message-row{{
    display:flex !important;
    margin:12px 4px;
    scroll-margin-bottom:calc(var(--chat-safe-gap) + 16px);
}}
.message-row.user{{ justify-content:flex-end }}
.message-row.assistant{{ justify-content:flex-start }}

.bubble{{
    max-width:88%;
    padding:14px 16px;
    border-radius:12px;
    font-size:15px;
    line-height:1.45;
    color:var(--text);
    word-wrap:break-word;
    border:1px solid transparent !important;
    box-shadow:none !important;
}}
.bubble.user{{
    background:var(--bubble-user);
    border-bottom-right-radius:6px;
}}
.bubble.assistant{{
    background:var(--bubble-assistant);
    border-bottom-left-radius:6px;
}}

.chat-card a{{
    color:var(--link) !important;
    text-decoration:underline;
}}
.chat-card a:hover{{ color:var(--link-hover) }}

/* CHAT INPUT */
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
    box-shadow:0 10px 24px rgba(0,0,0,.45) !important;
    overflow:hidden;
    transition:border-color .12s ease, box-shadow .12s ease;
}}
[data-testid="stChatInput"] textarea{{
    width:100% !important;
    border:none !important;
    border-radius:999px !important;
    padding:18px 20px !important;
    font-size:16px !important;
    outline:none !important;
    height:auto !important;
    min-height:44px !important;
    max-height:220px !important;
    overflow-y:hidden !important;
    caret-color:#ffffff !important;
}}
[data-testid="stChatInput"] textarea::placeholder{{
    color:var(--muted) !important;
}}
[data-testid="stChatInput"] textarea:focus::placeholder{{
    color:transparent !important;
    opacity:0 !important;
}}
[data-testid="stChatInput"] button{{
    margin-right:8px !important;
    border:none !important;
    background:transparent !important;
    color:var(--text-dim) !important;
}}
[data-testid="stChatInput"] svg{{ fill:currentColor !important }}

/* bottom container fantasma */
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

/* Scrollbar */
[data-testid="stDecoration"],
[data-testid="stStatusWidget"]{{ display:none !important }}
*::-webkit-scrollbar{{ width:10px; height:10px }}
*::-webkit-scrollbar-thumb{{
    background:#565869;
    border-radius:8px;
}}
*::-webkit-scrollbar-track{{ background:#171717 }}

/* Spinner */
.spinner{{
    width:16px;
    height:16px;
    border:2px solid rgba(37,99,235,.25);
    border-top-color:#2563eb;
    border-radius:50%;
    display:inline-block;
    animation:spin .8s linear infinite;
}}
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
        <a href="?logout=1" target="_self">
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

# Toast Supabase
if st.session_state.get("_sb_last_error"):
    st.toast("Falha ao salvar no Supabase (ver RLS/defaults).", icon="⚠️")
    st.error(f"💾 Detalhes Supabase: {st.session_state['_sb_last_error']}")
    st.session_state["_sb_last_error"] = None

# ====== SIDEBAR (Histórico) ======
with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="sidebar-bar" style="display:flex;align-items:center;justify-content:space-between;">
        <div class="sidebar-sub">Perguntas desta sessão</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.get("user_id") and st.session_state.sidebar_history:
        perguntas_sidebar = st.session_state.sidebar_history[-20:]
    else:
        perguntas_sidebar = [p for p, _ in st.session_state.historico][-20:]

    if not perguntas_sidebar:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for pergunta_hist in perguntas_sidebar:
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

# âncora mínima, o “colchão” agora é feito via scrollToEnd
msgs_html.append('<div id="chatEnd" style="height:1px;"></div>')

st.markdown(
    f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>',
    unsafe_allow_html=True
)

# ====== JS (layout + autoscroll com limiar) ======
st.markdown("""
<script>
(function(){
    function ajustaEspaco(){
        const input = document.querySelector('[data-testid="stChatInput"]');
        const card  = document.getElementById('chatCard');
        if(!input || !card) return;

        const rect   = input.getBoundingClientRect();
        const gapVar = getComputedStyle(document.documentElement)
                        .getPropertyValue('--chat-safe-gap').trim();
        const gap    = parseInt(gapVar || '300', 10);

        const alturaEfetiva = (window.innerHeight - rect.top) + gap;
        card.style.paddingBottom       = alturaEfetiva + 'px';
        card.style.scrollPaddingBottom = alturaEfetiva + 'px';
    }

    function autoGrow(){
        const ta = document.querySelector('[data-testid="stChatInput"] textarea');
        if(!ta) return;
        const MAX = 220;
        ta.style.height = 'auto';
        const desired   = Math.min(ta.scrollHeight, MAX);
        ta.style.height = desired + 'px';
        ta.style.overflowY = (ta.scrollHeight > MAX) ? 'auto' : 'hidden';
    }

    // Scroll até um pouco antes do final do card,
    // deixando espaço visível acima do input fixo.
    function scrollToEnd(smooth=true){
        const card = document.getElementById('chatCard');
        if(!card) return;

        const gapVar = getComputedStyle(document.documentElement)
                        .getPropertyValue('--chat-safe-gap').trim();
        const gap    = parseInt(gapVar || '300', 10);

        const margin = gap * 0.5;  // quanto queremos de “respiro” antes do input
        let target   = card.scrollHeight - card.clientHeight - margin;
        if (target < 0) target = 0;

        card.scrollTo({
            top: target,
            behavior: smooth ? 'smooth' : 'auto'
        });
    }

    const ro = new ResizeObserver(()=>{ ajustaEspaco(); });
    ro.observe(document.body);

    window.addEventListener('load', ()=>{
        autoGrow();
        ajustaEspaco();
        scrollToEnd(false);
    });

    window.addEventListener('resize', ()=>{
        autoGrow();
        ajustaEspaco();
    });

    document.addEventListener('input', (e)=>{
        if(e.target && e.target.matches('[data-testid="stChatInput"] textarea')){
            autoGrow();
            ajustaEspaco();
        }
    });

    setTimeout(()=>{ autoGrow(); ajustaEspaco(); scrollToEnd(false); }, 0);
    setTimeout(()=>{ autoGrow(); ajustaEspaco(); scrollToEnd(true); }, 150);

    const card = document.getElementById('chatCard');
    if(card){
        const mo = new MutationObserver(()=>{
            ajustaEspaco();
            scrollToEnd(true);
        });
        mo.observe(card, { childList:true, subtree:false });
    }
})();
</script>
""", unsafe_allow_html=True)

# ====== INPUT CHAT ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")

# ====== FLUXO PRINCIPAL DO CHAT ======
if pergunta and pergunta.strip():
    q = pergunta.strip()
    st.session_state.historico.append((q, ""))

    if st.session_state.get("user_id"):
        st.session_state.sidebar_history.append(q)
        if len(st.session_state.sidebar_history) > 20:
            st.session_state.sidebar_history = st.session_state.sidebar_history[-20:]

    try:
        cid = get_or_create_conversation()
        save_message(cid, "user", q)
        update_conversation_title_if_first_question(cid, q)
    except Exception as e:
        st.session_state["_sb_last_error"] = f"save.user: {_extract_err_msg(e)}"

    st.session_state.pending_index = len(st.session_state.historico) - 1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer = True
    st.session_state.answering_started = False
    do_rerun()

if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started = True
    do_rerun()

if st.session_state.awaiting_answer and st.session_state.answering_started:
    resposta = responder_pergunta(st.session_state.pending_question)
    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        pergunta_fix = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (pergunta_fix, resposta)

    try:
        cid = get_or_create_conversation()
        save_message(cid, "assistant", resposta)
    except Exception as e:
        st.session_state["_sb_last_error"] = f"save.assistant: {_extract_err_msg(e)}"

    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    do_rerun()
