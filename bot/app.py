# app.py — Gate visual padronizado (cartão 460px, sem borda dupla/tooltip) + logout mesma aba
# Funcionalidade permanece: valida e-mail @quadra.com.vc antes do app.

import streamlit as st
import base64
import os
import re
import warnings
from html import escape
from openai_backend import responder_pergunta

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

# ====== UTILS ======
def carregar_imagem_base64(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def get_query_params():
    try:
        return st.query_params.to_dict()
    except Exception:
        return st.experimental_get_query_params()

def set_query_params(**kwargs):
    try:
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)

logo_b64 = carregar_imagem_base64(LOGO_PATH)

# ====== LOGOUT (sem loop; mesma aba) ======
params = get_query_params()
if "logout" in params:
    for k in ["gate_ok", "user", "historico", "awaiting_answer",
              "answering_started", "pending_index", "pending_question"]:
        st.session_state.pop(k, None)
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()
    st.markdown("""
    <script>
      (function(){
        const u = new URL(window.location.href);
        u.search = "";
        window.history.replaceState({}, "", u.pathname);
      })();
    </script>
    """, unsafe_allow_html=True)

# ===================== GATE (ANTES DO APP) =====================
ALLOWED_DOMAIN = "quadra.com.vc"

def render_gate():
    # ===== VISUAL: igual à 2ª imagem (card 460px, input clean, sem tooltip, botão Google) =====
    st.markdown(f"""
    <style>
      /* Fundo e ocupação */
      html, body, .stApp, [data-testid="stAppViewContainer"] {{
        height: 100dvh !important; max-height: 100dvh !important; overflow: hidden !important;
      }}
      [data-testid="stAppViewContainer"]::before {{
        content:""; position: fixed; inset: 0;
        background:
          radial-gradient(1200px 600px at 30% 20%, #1f3a8a33, transparent),
          radial-gradient(1000px 700px at 80% 80%, #1d4ed833, transparent),
          linear-gradient(135deg, #0f172a 0%, #0b1226 100%);
        z-index: 0;
      }}

      /* Some chrome e sidebar */
      header[data-testid="stHeader"], div[data-testid="stToolbar"] {{ display:none !important }}
      #MainMenu, footer {{ visibility:hidden; height:0 !important }}
      section[data-testid="stSidebar"] {{ display:none !important }}
      div[data-testid="stAppViewContainer"] {{ margin-left:0 !important }}
      .block-container {{ padding:0 !important }}

      /* Cartão central (máx 460px) */
      [data-testid="stForm"] {{
        position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%);
        width: min(460px, 94vw);
        background: #ffffff;
        border-radius: 16px;
        box-shadow: 0 28px 80px rgba(0,0,0,.35);
        padding: 26px 26px 18px;
        z-index: 1;
      }}

      .gate-logo {{
        width:76px; height:76px; border-radius:20px; display:grid; place-items:center;
        background:#eef2ff; margin:2px auto 12px; overflow:hidden;
      }}
      .gate-title  {{ font-weight:800; font-size:24px; color:#0f172a; text-align:center; margin:2px 0 6px }}
      .gate-sub    {{ color:#475569; text-align:center; margin-bottom:8px }}
      .gate-helper {{ color:#64748b; text-align:center; margin:2px 0 16px }}

      /* ====== INPUT: sem borda duplicada + sem tooltip ====== */
      /* remove "Press Enter to submit form" */
      [data-testid="InputInstructions"] {{ display:none !important }}

      /* zera borda/sombra do container do TextInput */
      [data-testid="stTextInput"] > div {{ border:none !important; box-shadow:none !important; background:transparent !important; }}

      /* campo em si */
      [data-testid="stTextInput"] label {{ display:none !important }}
      [data-testid="stTextInput"] input {{
        width: 100%; height: 44px; padding: 0 14px; font-size: 15px;
        border: 1px solid #e5e7eb; border-radius: 12px; outline: none; background:#fff;
        box-shadow: none !important;
      }}
      [data-testid="stTextInput"] input:focus {{
        border-color:#3b82f6; box-shadow: 0 0 0 3px #93c5fd66 !important;
      }}
      [data-testid="stTextInput"] {{ margin-bottom: 12px !important }}

      /* ====== Botão Google ====== */
      .stButton > button {{
        width: 100%; height: 48px; border-radius: 12px;
        border: 1px solid #e2e8f0; background: #ffffff; cursor: pointer;
        font-weight: 700; font-size: 15px; color: #0f172a;
        display: inline-flex; align-items: center; justify-content: center; gap: 8px;
        transition: box-shadow .15s ease, transform .02s ease;
      }}
      .stButton > button:hover  {{ box-shadow: 0 10px 28px rgba(2,6,23,.10) }}
      .stButton > button:active {{ transform: translateY(1px) }}
      .stButton > button::before {{
        content:""; width:18px; height:18px; display:inline-block;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 48 48'%3E%3Cpath fill='%234285F4' d='M24 9.5c3.1 0 5.9 1.1 8.1 3.2l6-6C34.9 3 29.7 1 24 1 14.6 1 6.7 6.3 3 14.1l7 5.4C11.5 13.8 17.3 9.5 24 9.5z'/%3E%3Cpath fill='%2334A853' d='M46.5 24.5c0-1.5-.1-2.6-.4-3.8H24v7.3h12.7c-.6 3.4-2.5 6.3-5.4 8.2l6.6 5.1c3.9-3.6 6.6-8.9 6.6-16.8z'/%3E%3Cpath fill='%23FBBC05' d='M10 28.7c-1-3-1-6.3 0-9.3l-7-5.4C-1.2 19.1-1.2 28.9 3 35.9l7-5.4z'/%3E%3Cpath fill='%23EA4335' d='M24 47c6.5 0 12.1-2.1 16.1-5.8l-6.6-5.1c-3 2-6.8 3.2-9.5 3.2-6.7 0-12.5-4.3-14.5-10.2l-7 5.4C6.8 41.7 14.6 47 24 47z'/%3E%3C/svg%3E");
        background-size: cover; background-repeat: no-repeat;
        margin-right: 6px;
      }}

      .gate-terms {{ color:#94a3b8; font-size:12px; text-align:center; margin-top:14px }}
    </style>
    """, unsafe_allow_html=True)

    logo_tag = (
        f'<img src="data:image/png;base64,{logo_b64}" style="width:56px;height:56px"/>'
        if logo_b64 else "🔷"
    )

    with st.form("quadra_gate_form", clear_on_submit=False):
        st.markdown(
            f"""
            <div class="gate-logo">{logo_tag}</div>
            <div class="gate-title">Quadra Engenharia</div>
            <div class="gate-sub">Faça login para acessar nosso assistente virtual</div>
            <div class="gate-helper">Entre com sua conta do domínio <b>@{ALLOWED_DOMAIN}</b></div>
            """,
            unsafe_allow_html=True,
        )

        email = st.text_input(
            "Email corporativo",
            placeholder=f"seu.email@{ALLOWED_DOMAIN}",
            label_visibility="collapsed",
            key="gate_email_input",
        )
        ok = st.form_submit_button("Entrar com Google")

        if ok:
            e = (email or "").strip().lower()
            if re.fullmatch(rf"[^@\s]+@{re.escape(ALLOWED_DOMAIN)}", e):
                st.session_state["gate_ok"] = True
                st.session_state["user"] = {
                    "email": e,
                    "name": e.split("@")[0].replace(".", " ").replace("_", " ").title() or "Usuário Quadra",
                }
                do_rerun()
            else:
                st.error(f"Use um email @{ALLOWED_DOMAIN}")

        st.markdown(
            '<div class="gate-terms">Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade.</div>',
            unsafe_allow_html=True,
        )

    st.stop()

if not st.session_state.get("gate_ok", False):
    render_gate()

# =================== FIM DO GATE / INÍCIO DO APP ======================

# ====== ESTADO ======
if "historico" not in st.session_state:
    st.session_state.historico = []
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

# ====== MARCAÇÃO ======
def formatar_markdown_basico(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = text.replace("\n", "<br>")
    return text

def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

def reenviar_pergunta(q: str):
    q = (q or "").strip()
    if not q:
        return
    st.session_state.historico.append((q, ""))
    st.session_state.pending_index = len(st.session_state.historico) - 1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer = True
    st.session_state.answering_started = False
    do_rerun()

# ====== CSS do APP (inalterado do seu) ======
st.markdown("""
<style>
/* RESET / BASE */
* { box-sizing: border-box }
html, body { margin: 0; padding: 0 }
img { max-width: 100%; height: auto; display: inline-block }
img.logo { height: 44px !important; width: auto !important }

/* VARS */
:root{
  --content-max-width: min(96vw, 1400px);
  --header-height: 68px;
  --sidebar-w:270px;

  --input-bottom: 60px;
  --input-h: 72px;
  --extra-gap: 20px;

  --panel-alt:#1C1F26;
  --bg: var(--panel-alt);
  --panel: var(--panel-alt);
  --panel-header: var(--panel-alt);

  --sidebar-bg: #000000;

  --input-bg-light:#262D38;

  --border:#242833;
  --text:#E5E7EB; --text-dim:#C9D1D9; --muted:#9AA4B2;

  --link:#3B82F6; --link-hover:#93C5FD;

  --bubble-user:#222833; --bubble-assistant:#232833;
  --input-border:#323949;

  --sidebar-items-top-gap: -45px;
  --sidebar-sub-top-gap: -30px;
  --sidebar-list-start-gap: 5px;
}

/* CHROME */
header[data-testid="stHeader"]{ display:none !important }
div[data-testid="stToolbar"]{ display:none !important }
#MainMenu, footer{ visibility:hidden; height:0 !important }

html, body, .stApp, main, .stMain, .block-container, [data-testid="stAppViewContainer"]{
  height:100dvh !important; max-height:100dvh !important; overflow:hidden !important; overscroll-behavior:none;
}
.block-container{ padding:0 !important; min-height:0 !important }
.stApp{ background:var(--bg) !important; color:var(--text) !important }

/* HEADER */
.header{
  position:fixed; inset:0 0 auto 0; height:var(--header-height);
  display:flex; align-items:center; justify-content:space-between;
  padding:10px 16px; background:var(--panel-header); z-index:1000;
  border-bottom:1px solid var(--border);
}
.header-left{ display:flex; align-items:center; gap:10px; font-weight:600; color:var(--text) }
.header-left .title-sub{ font-weight:500; font-size:.85rem; color:var(--muted); margin-top:-4px }
.header-right{ display:flex; align-items:center; gap:12px; color:var(--text) }
.header .btn{
  appearance:none; background:transparent; color:var(--link) !important;
  border:1px solid var(--border); padding:8px 12px; border-radius:10px;
  font:inherit; cursor:pointer; text-decoration:none; display:inline-block;
}
.header .btn:hover{ color:var(--link-hover) !important; border-color:#3B4250 }
.user-info{ text-align:right; font-size:0.9rem; color:var(--text) }
.user-info .user-name{ font-weight:600 }
.user-info .user-email{ font-weight:400; color:var(--muted); font-size:0.8rem; text-decoration:none }
.user-circle{ width:28px; height:28px; border-radius:50%; background:#0ea5e9; color:#001018;
  display:grid; place-items:center; font-weight:800; }

/* SIDEBAR */
section[data-testid="stSidebar"]{
  position:fixed !important; top:var(--header-height) !important; left:0 !important;
  height:calc(100dvh - var(--header-height)) !important; width:var(--sidebar-w) !important;
  min-width:var(--sidebar-w) !important; margin:0 !important; padding:0 !important;
  background:var(--sidebar-bg) !important; border-right:1px solid rgba(255,255,255,0.06);
  z-index:900 !important; transform:none !important; visibility:visible !important;
  overflow:hidden !important; color:var(--text);
}
section[data-testid="stSidebar"] > div,
div[data-testid="stSidebarContent"],
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{ padding-top:0 !important; margin-top:0 !important; }

section[data-testid="stSidebar"] .sidebar-header{ margin-top: var(--sidebar-items-top-gap) !important; }
.sidebar-bar p, .sidebar-header p{ margin:0 !important; line-height:1.15 !important; }
.sidebar-bar{ margin-top: var(--sidebar-sub-top-gap) !important; }
.hist-row:first-of-type{ margin-top: var(--sidebar-list-start-gap) !important; }

div[data-testid="stAppViewContainer"]{ margin-left:var(--sidebar-w) !important }

.sidebar-header{ font-size:1.1rem; font-weight:700; letter-spacing:.02em; color:var(--text); margin:0 4px -2px 2px }
.sidebar-sub{ font-size:.88rem; color:var(--muted) }
.hist-empty{ color:var(--muted); font-size:.9rem; padding:8px 10px }
.hist-row{ padding:6px 6px; font-size:1.1rem; color:var(--text-dim) !important; line-height:1.35; border-radius:8px }
.hist-row + .hist-row{ margin-top:6px }
.hist-row:hover{ background:rgba(255,255,255,0.04) }

/* CONTEÚDO / CHAT */
.content{ max-width:var(--content-max-width); margin:var(--header-height) auto 0; padding:8px }
#chatCard, .chat-card{
  position:relative; z-index:50 !important; background:var(--panel-alt) !important;
  border:none !important; border-radius:12px 12px 0 0 !important; box-shadow:none !important; padding:20px;
  height: calc(100dvh - var(--header-height) - var(--input-bottom) - var(--input-h) - var(--extra-gap));
  overflow-y:auto; scroll-behavior:smooth;
  padding-bottom: calc(var(--input-bottom) + var(--input-h) + var(--extra-gap));
  scroll-padding-bottom: calc(var(--input-bottom) + var(--input-h) + var(--extra-gap));
  color:var(--text);
}
#chatCard *, .chat-card *{ position:relative; z-index:51 !important }
.chat-card a{ color:var(--link) !important; text-decoration:underline }
.chat-card a:hover{ color:var(--link-hover) !important }

.message-row{ display:flex !important; margin:12px 4px; scroll-margin-bottom:calc(var(--input-bottom) + var(--input-h) + var(--extra-gap) + 16px) }
.message-row.user{ justify-content:flex-end }
.message-row.assistant{ justify-content:flex-start }
.bubble{ max-width:88%; padding:14px 16px; border-radius:12px; font-size:15px; line-height:1.45;
  color:var(--text); word-wrap:break-word; border:1px solid transparent !important; box-shadow:none !important; }
.bubble.user{ background:var(--bubble-user); border-bottom-right-radius:6px }
.bubble.assistant{ background:var(--bubble-assistant); border-bottom-left-radius:6px }

/* CHAT INPUT */
[data-testid="stChatInput"]{
  position:fixed !important; left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2) !important;
  transform:translateX(-50%) !important; bottom:var(--input-bottom) !important;
  width:min(900px, 96vw) !important; z-index:5000 !important; background:transparent !important;
  border:none !important; box-shadow:none !important; padding:0 !important;
}
[data-testid="stChatInput"] *{ background:transparent !important; color:var(--text) !important; }
[data-testid="stChatInput"] > div{
  background:var(--input-bg-light) !important; border:1px solid var(--input-border) !important;
  border-radius:999px !important; box-shadow:0 10px 24px rgba(0,0,0,.35) !important;
  overflow:hidden; transition:border-color .12s ease, box-shadow .12s ease;
}
[data-testid="stChatInput"] textarea{
  width:100% !important; border:none !important; border-radius:999px !important;
  padding:18px 20px !important; font-size:16px !important; outline:none !important; height:auto !important;
  min-height:44px !important; max-height:220px !important; overflow-y:hidden !important; caret-color:#ffffff !important;
}
[data-testid="stChatInput"] textarea::placeholder{ color:var(--muted) !important }
[data-testid="stChatInput"] textarea:focus::placeholder{ color:transparent !important; opacity:0 !important }
[data-testid="stChatInput"] button{ margin-right:8px !important; border:none !important; background:transparent !important; color:var(--text-dim) !important; }
[data-testid="stChatInput"] svg{ fill:currentColor !important }

/* MATA A FAIXA BRANCA */
[data-testid="stBottomBlockContainer"],
[data-testid="stBottomBlockContainer"] > div,
[data-testid="stBottomBlockContainer"] [data-testid="stVerticalBlock"],
[data-testid="stBottomBlockContainer"] [class*="block-container"],
[data-testid="stBottomBlockContainer"]::before,
[data-testid="stBottomBlockContainer"]::after{
  background:transparent !important; box-shadow:none !important; border:none !important;
}
[data-testid="stBottomBlockContainer"]{ padding:0 !important; margin:0 !important; height:0 !important; min-height:0 !important }

/* EXTRAS */
[data-testid="stDecoration"], [data-testid="stStatusWidget"]{ display:none !important }
*::-webkit-scrollbar{ width:10px; height:10px }
*::-webkit-scrollbar-thumb{ background:#2C3340; border-radius:8px }
*::-webkit-scrollbar-track{ background:var(--panel-alt) }

.spinner{ width:16px; height:16px; border:2px solid rgba(37,99,235,.25); border-top-color:#2563eb; border-radius:50%;
  display:inline-block; animation:spin .8s linear infinite }
@keyframes spin{ to{ transform:rotate(360deg) } }
</style>
""", unsafe_allow_html=True)

# ====== HEADER (Sair) ======
user = st.session_state.get("user", {})
user_name = user.get("name", "Usuário")
user_email = user.get("email", "usuario@exemplo.com")
user_initial = (user_name[:1] or "U").upper()

logo_img_tag = (
    f'<img class="logo" src="data:image/png;base64,{logo_b64}" />'
    if logo_b64 else '<div style="width:44px;height:44px;border-radius:8px;background:#eef2ff;display:inline-block;"></div>'
)

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
    <a href="?logout=1" target="_self" class="btn">Sair</a>
    <div class="user-info">
      <span class="user-name">{escape(user_name)}</span><br>
      <span class="user-email">{escape(user_email)}</span>
    </div>
    <div class="user-circle">{escape(user_initial)}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ====== SIDEBAR ======
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
    msgs_html.append('<div style="color:#9ca3af; text-align:center; margin-top:20px;">&nbsp;</div>')

msgs_html.append('<div id="chatEnd" style="height:1px;"></div>')

st.markdown(
    f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>',
    unsafe_allow_html=True
)

# ====== JS (altura dinâmica do input + scroll seguro) ======
st.markdown("""
<script>
(function(){
  function setInputVars(){
    const wrap = document.querySelector('[data-testid="stChatInput"] > div');
    if(!wrap) return;
    const h = Math.ceil(wrap.getBoundingClientRect().height || 72);
    document.documentElement.style.setProperty('--input-h', h + 'px');
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
    if(end) end.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'end'});
  }

  const ro = new ResizeObserver(()=>{ setInputVars(); autoGrow(); scrollToEnd(false); });
  ro.observe(document.body);

  window.addEventListener('load', ()=>{ setInputVars(); autoGrow(); scrollToEnd(false); });
  window.addEventListener('resize', ()=>{ setInputVars(); autoGrow(); });
  document.addEventListener('input',(e)=>{
    if(e.target && e.target.matches('[data-testid="stChatInput"] textarea')){
      autoGrow(); setInputVars();
    }
  });

  const card = document.getElementById('chatCard');
  if(card){
    const mo = new MutationObserver(()=>{ setInputVars(); scrollToEnd(true); });
    mo.observe(card, {childList:true, subtree:false});
  }

  setTimeout(()=>{ setInputVars(); autoGrow(); scrollToEnd(false); }, 0);
  setTimeout(()=>{ setInputVars(); autoGrow(); scrollToEnd(true); }, 150);
})();
</script>
""", unsafe_allow_html=True)

# ====== INPUT ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")

# ====== FLUXO ======
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
    try:
        resposta = responder_pergunta(st.session_state.pending_question)
    except Exception as e:
        resposta = f"❌ Erro ao consultar o backend: {e}"

    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        pergunta_fix = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (pergunta_fix, resposta)

    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    do_rerun()
