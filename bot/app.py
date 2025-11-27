# app.py - Frontend do Chatbot Quadra (Versão Visual Corrigida + Menu Flutuante)

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

# ====== SUPABASE (Tolerante a falhas) ======
SB_URL = None
SB_KEY = None
SITE_URL = None
sb = None
try:
    from supabase import create_client, Client
    SB_URL = st.secrets.get("supabase", {}).get("url")
    SB_KEY = st.secrets.get("supabase", {}).get("anon_key")
    SITE_URL = st.secrets.get("supabase", {}).get("site_url", "http://localhost:8501")
    if SB_URL and SB_KEY:
        sb = create_client(SB_URL, SB_KEY)
except Exception:
    sb = None

# ====== CONFIG DA PÁGINA ======
LOGO_PATH = "data/logo_quadra.png"
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ====== ESTILO BASE (Pre-load) ======
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
        return "E-mail não confirmado. Abra o link de confirmação enviado."
    if "invalid login credentials" in low or "invalid" in low:
        return "Credenciais inválidas."
    if "rate limit" in low:
        return "Muitas tentativas. Aguarde."
    return msg or "Falha na autenticação."

# ====== ESTADO DA SESSÃO ======
if "historico" not in st.session_state:
    st.session_state.historico = []

st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)
st.session_state.setdefault("auth_mode", "login")
st.session_state.setdefault("just_registered", False)
st.session_state.setdefault("user_id", None)
st.session_state.setdefault("conversation_id", None)
st.session_state.setdefault("conversations_list", [])
st.session_state.setdefault("_title_set", False)
st.session_state.setdefault("_sb_last_error", None)
st.session_state.setdefault("_sidebar_loaded", False)
st.session_state.setdefault("selected_conversation_id", None)
st.session_state.setdefault("open_menu_conv", None)

# ====== FUNÇÕES SUPABASE ======
def _title_from_first_question(q: str) -> str:
    if not q:
        return "Nova conversa"
    t = re.sub(r"\s+", " ", q.strip())
    return (t[:60] + "…") if len(t) > 60 else t

def load_conversations_from_supabase():
    if not sb or not st.session_state.get("user_id"):
        return
    try:
        res = (
            sb.table("conversations")
            .select("id,title,created_at")
            .eq("user_id", st.session_state.user_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        st.session_state.conversations_list = res.data or []
    except Exception as e:
        st.session_state["_sb_last_error"] = f"conv.load: {_extract_err_msg(e)}"

def load_conversation_messages(cid):
    if not sb or not cid:
        return
    try:
        res = (
            sb.table("messages")
            .select("role,content,created_at")
            .eq("conversation_id", cid)
            .order("created_at", desc=False)
            .execute()
        )
        rows = res.data or []
        historico = []
        for row in rows:
            role = row.get("role")
            content = row.get("content") or ""
            if role == "user":
                historico.append((content, ""))
            elif role == "assistant":
                if historico and historico[-1][1] == "":
                    historico[-1] = (historico[-1][0], content)
                else:
                    historico.append(("[sistema]", content))
        st.session_state.historico = historico
        st.session_state.conversation_id = cid
        st.session_state.selected_conversation_id = cid
    except Exception as e:
        st.session_state["_sb_last_error"] = f"conv.load_msgs: {_extract_err_msg(e)}"

def delete_conversation(cid):
    if not sb or not cid:
        return
    try:
        sb.table("messages").delete().eq("conversation_id", cid).execute()
        sb.table("conversations").delete().eq("id", cid).execute()
    except Exception as e:
        st.session_state["_sb_last_error"] = f"conv.delete: {_extract_err_msg(e)}"

def get_or_create_conversation():
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
        st.session_state["selected_conversation_id"] = cid
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

# ====== LOGOUT ======
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
            sb.auth.sign_out()
    except: pass

    st.session_state.update({
        "authenticated": False,
        "user_name": "Usuário",
        "historico": [],
        "user_id": None,
        "conversation_id": None,
        "conversations_list": [],
    })
    _clear_query_params()
    do_rerun()

# ====== TELAS DE LOGIN/REGISTRO ======
BASE_LOGIN_CSS = """
<style>
:root{ --login-max: 520px; --lift: 90px; }
.stApp{
    background: radial-gradient(1100px 620px at 50% 35%, #264E9A 0%, #16356B 50%, #0B1730 100%) !important;
    min-height:100vh !important; overflow:hidden !important;
}
header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer{ display:none !important; }
[data-testid="stAppViewContainer"] > .main{ height:100vh !important; }
.block-container{ padding:0 !important; margin:0 !important; display:flex; align-items:center; justify-content:center; }
.login-stack{ width:min(92vw, var(--login-max)); margin:0 auto; text-align:center; transform: translateY(calc(var(--lift) * -1)); }
.login-title{ font-size:1.5rem; font-weight:800; color:#F5F7FF; margin:6px 0 6px; }
.login-sub{ font-size:1rem; color:#C9D7FF; margin:0 0 16px; }
.login-stack [data-testid="stTextInput"] input {
    width:100%; height:48px; border-radius:10px; border:1px solid rgba(255,255,255,.2) !important;
    background:#ffffff !important; color:#111827 !important;
}
.login-stack .stButton > button { height:44px; border-radius:10px; background:rgba(255,255,255,.08); color:#E6EEFF; border:1px solid rgba(255,255,255,.18); }
.login-actions .stButton > button { background:#2E5CB5 !important; color:#ffffff !important; font-weight:700 !important; }
</style>
"""

def render_login_screen():
    st.markdown(BASE_LOGIN_CSS, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown('<div class="login-stack">', unsafe_allow_html=True)
        if logo_b64:
            st.markdown(f'<img src="data:image/png;base64,{logo_b64}" style="height:88px;margin:0 auto 14px;display:block;" />', unsafe_allow_html=True)
        st.markdown('<span class="login-title">Quadra Engenharia</span>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">Entre com seu e-mail</div>', unsafe_allow_html=True)

        if st.session_state.get("just_registered"):
            st.success("Cadastrado! Faça login.")
            st.session_state.just_registered = False

        def _try_login():
            email = (st.session_state.get("login_email") or "").strip().lower()
            pwd = (st.session_state.get("login_senha") or "")
            if not email.endswith("@quadra.com.vc"):
                st.session_state["login_error"] = "Use e-mail @quadra.com.vc"
                return
            if pwd == "quadra123": # Bypass
                st.session_state.update({
                    "authenticated": True, "user_email": email, "user_name": extract_name_from_email(email),
                    "login_error": "", "user_id": None, "conversation_id": None, "conversations_list": [], "historico": []
                })
                return
            if not sb:
                st.session_state["login_error"] = "Sem Supabase."
                return
            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": pwd})
                user = res.user if hasattr(res, "user") else res.get("user")
                if user:
                    st.session_state.update({
                        "authenticated": True, "user_email": email, "user_name": extract_name_from_email(email),
                        "user_id": user.id, "login_error": "", "conversation_id": None, "conversations_list": [], "historico": []
                    })
            except Exception as e:
                st.session_state["login_error"] = _friendly_auth_error(_extract_err_msg(e))

        st.text_input("Email", key="login_email", placeholder="email@quadra.com.vc")
        st.text_input("Senha", key="login_senha", type="password", placeholder="Senha", on_change=_try_login)
        
        st.markdown('<div class="login-actions">', unsafe_allow_html=True)
        if st.button("Entrar", type="primary"):
            _try_login()
            do_rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        if st.button("Criar conta"):
            st.session_state.auth_mode = "register"
            do_rerun()

        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

def render_register_screen():
    st.markdown(BASE_LOGIN_CSS, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown('<div class="login-stack">', unsafe_allow_html=True)
        st.markdown('<span class="login-title">Criar conta</span>', unsafe_allow_html=True)
        
        st.text_input("Email", key="reg_email", placeholder="@quadra.com.vc")
        st.text_input("Senha", key="reg_senha", type="password")
        st.text_input("Confirmar", key="reg_confirma", type="password")
        
        if st.button("Cadastrar", type="primary"):
            email = st.session_state.reg_email
            pwd = st.session_state.reg_senha
            if "@" in email and pwd == st.session_state.reg_confirma:
                if sb:
                    try:
                        sb.auth.sign_up({"email": email, "password": pwd, "options": {"email_redirect_to": SITE_URL}})
                        st.success("Verifique seu e-mail.")
                    except Exception as e:
                        st.error(_friendly_auth_error(_extract_err_msg(e)))
                else:
                    st.session_state.auth_mode = "login"
                    st.session_state.just_registered = True
                    do_rerun()

        if st.button("Voltar"):
            st.session_state.auth_mode = "login"
            do_rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

if not st.session_state.authenticated:
    if st.session_state.auth_mode == "register":
        render_register_screen()
    else:
        render_login_screen()

if sb and st.session_state.get("user_id") and not st.session_state.get("_sidebar_loaded"):
    load_conversations_from_supabase()
    st.session_state["_sidebar_loaded"] = True

# ====== CSS PRINCIPAL & SIDEBAR VISUAL FIX ======
st.markdown("""
<style>
/* Reset básico */
* { box-sizing: border-box }
html, body { margin:0; padding:0; background: #202123; }

/* VARIÁVEIS VISUAIS */
:root{
    --bg:#202123; --panel:#050509; --panel-header:#26272F;
    --text:#ECECF1; --text-dim:#D1D5DB;
    --sidebar-w:270px;
    --header-height:68px;
}

/* HEADER FIXO */
.header {
    position:fixed; top:0; left:0; width:100%; height:var(--header-height);
    display:flex; align-items:center; justify-content:space-between;
    padding:10px 16px; background:var(--panel-header); border-bottom:1px solid #565869;
    z-index:1000;
}
.header-left { display:flex; gap:10px; align-items:center; color:var(--text); font-weight:600; }
.header-right { display:flex; gap:12px; align-items:center; color:var(--text); }
.user-circle { width:32px; height:32px; border-radius:50%; background:#3B82F6; display:flex; align-items:center; justify-content:center; }
.header a { color:#FFF; padding:8px 12px; background:#3B82F6; border-radius:8px; text-decoration:none; font-size:0.9rem; }

/* SIDEBAR FIXA E LIMPA */
section[data-testid="stSidebar"] {
    top:var(--header-height) !important;
    height:calc(100vh - var(--header-height)) !important;
    background:var(--panel) !important;
    border-right:1px solid #565869;
    width:var(--sidebar-w) !important;
    min-width:var(--sidebar-w) !important;
    overflow:visible !important; /* Importante para o menu flutuar pra fora */
    z-index:2000;
}
/* Remove paddings excessivos do Streamlit */
section[data-testid="stSidebar"] .block-container { padding: 1rem 0.5rem !important; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0 !important; }

/* ESTILO DA LINHA DE CONVERSA (Removedor de barras estranhas) */
.sidebar-row {
    position: relative;
    border-radius: 6px;
    margin: 2px 0 !important;
    padding: 2px 4px !important;
    background: transparent; /* Fundo transparente por padrão */
    transition: background 0.1s;
}
.sidebar-row-active { background: #343541 !important; }
.sidebar-row:hover { background: #2A2B32; }

/* Botões invisíveis dentro da sidebar */
.sidebar-row button {
    border:none !important; background:transparent !important; color:#ECECF1 !important;
    text-align:left; box-shadow:none !important; padding: 4px !important;
}

/* --- O HACK DO MENU FLUTUANTE (POSIÇÃO CORRETA) --- */
/* Isso força o container seguinte ao marcador a flutuar para a direita */
div[data-testid="stSidebar"] div.stMarkdown:has(.floating-delete-marker) + div.element-container {
    position: absolute !important;
    right: -170px !important; /* Joga pra fora da sidebar (direita) */
    top: -42px !important;    /* Ajuste vertical para alinhar com a linha */
    width: 160px !important;
    z-index: 99999 !important;
}

/* Estilo do botão de deletar flutuante */
div[data-testid="stSidebar"] div.stMarkdown:has(.floating-delete-marker) + div.element-container button {
    background-color: #202123 !important;
    border: 1px solid #565869 !important;
    color: #ef4444 !important;
    border-radius: 6px !important;
    text-align: center !important;
    font-size: 0.9rem !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
    padding: 8px !important;
    width: 100% !important;
}
div[data-testid="stSidebar"] div.stMarkdown:has(.floating-delete-marker) + div.element-container button:hover {
    background-color: #343541 !important;
}

/* ÁREA DE CHAT */
.content { max-width:900px; margin:calc(var(--header-height) + 20px) auto 160px; padding:0 16px; }
.message-row { display:flex; margin-bottom:24px; }
.message-row.user { justify-content:flex-end; }
.bubble { padding:16px; border-radius:8px; max-width:85%; line-height:1.5; }
.bubble.user { background:#343541; }
.bubble.assistant { background:transparent; }

/* INPUT */
[data-testid="stChatInput"] { bottom:30px !important; }
[data-testid="stChatInput"] textarea { background:#40414F !important; color:#FFF !important; border:1px solid #565869 !important; }
</style>
""", unsafe_allow_html=True)

# ====== RENDER HEADER ======
primeira = st.session_state.user_name[0].upper()
st.markdown(f"""
<div class="header">
    <div class="header-left">{logo_img_tag}<span>Chatbot Quadra</span></div>
    <div class="header-right">
        <a href="?logout=1">Sair</a>
        <div class="user-circle">{primeira}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ====== SIDEBAR LOOP ======
with st.sidebar:
    st.markdown('<div style="font-weight:600;margin-bottom:8px;color:#ECECF1;">Histórico</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:#9CA3AF;margin-bottom:10px;">Conversas</div>', unsafe_allow_html=True)

    conversas = st.session_state.conversations_list
    if not conversas:
        st.markdown('<span style="color:#666;font-size:0.9rem;padding:0 10px;">Sem conversas.</span>', unsafe_allow_html=True)
    
    for conv in conversas:
        cid = conv.get("id")
        title = conv.get("title", "Nova conversa").strip().replace("\n", " ")
        if len(title) > 30: title = title[:30] + "..."
        
        isActive = (st.session_state.get("selected_conversation_id") == cid)
        activeClass = " sidebar-row-active" if isActive else ""
        
        # Container da linha
        st.markdown(f'<div class="sidebar-row{activeClass}">', unsafe_allow_html=True)
        
        c1, c2 = st.columns([0.85, 0.15])
        with c1:
            if st.button(title, key=f"t_{cid}", help=conv.get("title")):
                load_conversation_messages(cid)
                st.session_state.open_menu_conv = None
                do_rerun()
        with c2:
            if st.button("⋯", key=f"m_{cid}"):
                cur = st.session_state.get("open_menu_conv")
                st.session_state.open_menu_conv = None if cur == cid else cid
                do_rerun()
        
        # --- LÓGICA DO MENU FLUTUANTE (MARKER HACK) ---
        if st.session_state.get("open_menu_conv") == cid:
            # 1. Este span invisível ativa o CSS 'has(.floating-delete-marker)'
            st.markdown('<span class="floating-delete-marker"></span>', unsafe_allow_html=True)
            # 2. O botão abaixo será capturado pelo CSS e jogado para fora da sidebar
            if st.button("🗑 Excluir conversa", key=f"del_{cid}"):
                delete_conversation(cid)
                if st.session_state.conversation_id == cid:
                    st.session_state.historico = []
                    st.session_state.conversation_id = None
                    st.session_state.selected_conversation_id = None
                st.session_state.open_menu_conv = None
                load_conversations_from_supabase()
                do_rerun()

        st.markdown('</div>', unsafe_allow_html=True)

# ====== ÁREA DE CHAT ======
def linkify(text):
    return escape(text or "").replace("\n", "<br>")

html_msgs = []
for p, r in st.session_state.historico:
    html_msgs.append(f'<div class="message-row user"><div class="bubble user">{linkify(p)}</div></div>')
    if r:
        html_msgs.append(f'<div class="message-row assistant"><div class="bubble assistant">{linkify(r)}</div></div>')

if st.session_state.awaiting_answer and st.session_state.answering_started:
    html_msgs.append('<div class="message-row assistant"><div class="bubble assistant">Digitando...</div></div>')

st.markdown(f'<div class="content">{"".join(html_msgs)}</div>', unsafe_allow_html=True)

# ====== INPUT ======
q = st.chat_input("Mensagem para o assistente...")
if q:
    st.session_state.historico.append((q, ""))
    cid = get_or_create_conversation()
    save_message(cid, "user", q)
    update_conversation_title_if_first_question(cid, q)
    
    st.session_state.pending_index = len(st.session_state.historico) - 1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer = True
    st.session_state.answering_started = False
    do_rerun()

if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started = True
    do_rerun()

if st.session_state.awaiting_answer and st.session_state.answering_started:
    resp = responder_pergunta(st.session_state.pending_question)
    idx = st.session_state.pending_index
    if idx is not None:
        orig = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (orig, resp)
    
    cid = get_or_create_conversation()
    save_message(cid, "assistant", resp)
    
    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    do_rerun()