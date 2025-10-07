# app.py

import streamlit as st
import base64
import os
import re
import warnings
from html import escape
from openai_backend import responder_pergunta  # seu backend

warnings.filterwarnings("ignore", message=".*torch.classes.*")

st.set_page_config(page_title="Chatbot Quadra", layout="wide", initial_sidebar_state="expanded")

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== LOGO ======
LOGO_PATH = "data/logo_quadra.png"
def carregar_imagem_base64(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_b64 = carregar_imagem_base64(LOGO_PATH)
if logo_b64:
    st.markdown(f'<link rel="icon" href="data:image/png;base64,{logo_b64}" />', unsafe_allow_html=True)

# ====== ESTADO ======
if "historico" not in st.session_state:
    st.session_state.historico = []   # [(pergunta, resposta)]
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

# ====== UTILS ======
_url_re = re.compile(r'(https?://[^\s<>"\]]+)', re.IGNORECASE)
def linkify(text: str) -> str:
    safe = escape(text).replace("\n", "<br>")
    return _url_re.sub(r'<a href="\\1" target="_blank" rel="noopener noreferrer">\\1</a>', safe)

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

# ====== CSS (somente correções) ======
st.markdown("""
<style>
:root {
  --header-height: 72px;
  --sidebar-w: 300px;
  --input-bottom: 90px; /* campo do chat mais alto */
}

/* Remove header padrão */
header[data-testid="stHeader"] { display: none !important; }

/* Sidebar (histórico visível) */
section[data-testid="stSidebar"] {
  position: fixed !important;
  top: var(--header-height) !important;
  left: 0 !important;
  height: calc(100dvh - var(--header-height)) !important;
  width: var(--sidebar-w) !important;
  min-width: var(--sidebar-w) !important;
  margin: 0 !important;
  padding: 8px 10px !important;
  background: #fff !important;
  border-right: 1px solid rgba(59,130,246,.10);
  z-index: 900 !important;
  overflow-y: auto !important;
  visibility: visible !important;
}

/* Empurra conteúdo principal */
div[data-testid="stAppViewContainer"] {
  margin-left: var(--sidebar-w) !important;
}

/* Input do chat */
div[data-testid="stChatInput"] {
  position: fixed !important;
  bottom: var(--input-bottom) !important;
  left: calc(var(--sidebar-w) + 40px) !important;
  right: 40px !important;
  z-index: 999 !important;
  background: white !important;
  box-shadow: 0px -2px 8px rgba(0,0,0,0.05);
  border-radius: 10px;
  padding: 8px 16px;
}

/* Ajusta altura do chat-card para evitar sobreposição */
#chatCard {
  padding-bottom: 160px !important;
  scroll-padding-bottom: 160px !important;
}
</style>
""", unsafe_allow_html=True)

# ====== HEADER HTML ======
logo_img_tag = f'<img class="logo" src="data:image/png;base64,{logo_b64}" />' if logo_b64 else \
               '<div style="width:44px;height:44px;border-radius:8px;background:#eef2ff;display:inline-block;"></div>'

st.markdown(
    f"""
<div class="header">
  <div class="header-left">
    {logo_img_tag}
    <div>
      Quadra Engenharia
      <div class="title-sub">Assistente Inteligente</div>
    </div>
  </div>
  <div class="header-right">
    <a href="#" style="text-decoration:none;color:#2563eb;font-weight:600;border:1px solid rgba(37,99,235,0.12);padding:8px 12px;border-radius:10px;display:inline-block;">⚙ Configurações</a>
    <div style="text-align:right;font-size:0.9rem;color:#111827;">
      Usuário Demo<br><span style="font-weight:400;color:#6b7280;font-size:0.8rem;">usuario@exemplo.com</span>
    </div>
    <div class="user-circle">U</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ====== SIDEBAR: Histórico ======
with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)
    col_l, col_r = st.columns([1, 0.2])
    with col_l:
        st.markdown('<div class="sidebar-bar"><div class="sidebar-sub">Perguntas desta sessão</div></div>', unsafe_allow_html=True)
    with col_r:
        st.markdown('<div class="trash-wrap">', unsafe_allow_html=True)
        trash_clicked = st.button("🗑️", key="trash", help="Limpar histórico")
        st.markdown('</div>', unsafe_allow_html=True)
        if trash_clicked:
            st.session_state.historico = []
            do_rerun()

    if not st.session_state.historico:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for i, (pergunta_hist, _resp) in enumerate(reversed(st.session_state.historico)):
            idx_real = len(st.session_state.historico) - 1 - i
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80:
                titulo = titulo[:80] + "…"
            st.markdown('<div class="hist-item">', unsafe_allow_html=True)
            if st.button(titulo or "(vazio)", key=f"hist_{idx_real}", use_container_width=True, type="secondary"):
                reenviar_pergunta(st.session_state.historico[idx_real][0])
            st.markdown('</div>', unsafe_allow_html=True)

# ====== RENDER MENSAGENS ======
msgs_html = []
for pergunta, resposta in st.session_state.historico:
    p_html = linkify(pergunta)
    msgs_html.append(f'<div class="message-row user"><div class="bubble user">{p_html}</div></div>')
    if resposta:
        r_html = linkify(resposta)
        msgs_html.append(f'<div class="message-row assistant"><div class="bubble assistant">{r_html}</div></div>')

if not msgs_html:
    msgs_html.append('<div style="color:#9ca3af; text-align:center; margin-top:20px;">.</div>')

st.markdown(f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>', unsafe_allow_html=True)

# ====== SKIRT ======
st.markdown('<div class="bottom-gradient-fix"></div>', unsafe_allow_html=True)

# ====== JS ======
st.markdown("""
<script>
(function(){
  function ajustaEspaco(){
    const input = document.querySelector('[data-testid="stChatInput"]');
    const card  = document.getElementById('chatCard');
    if (!input || !card) return;
    const rect = input.getBoundingClientRect();
    const alturaEfetiva = (window.innerHeight - rect.top) + 12;
    card.style.paddingBottom = alturaEfetiva + 'px';
    card.style.scrollPaddingBottom = alturaEfetiva + 'px';
  }
  const ro = new ResizeObserver(() => { ajustaEspaco(); });
  ro.observe(document.body);
  window.addEventListener('load',  ajustaEspaco);
  window.addEventListener('resize',ajustaEspaco);
  setTimeout(ajustaEspaco, 150);
})();
</script>
""", unsafe_allow_html=True)

# ====== INPUT FIXO ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")

# ====== FLUXO EM 3 ETAPAS ======
if pergunta and pergunta.strip():
    q = pergunta.strip()
    st.session_state.historico.append((q, "")) 
    st.session_state.pending_index = len(st.session_state.historico) - 1
    st.session_state.pending_question = q
    st.session_state.awaiting_answer = True
    st.session_state.answering_started = False
    do_rerun()

if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started = True
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
