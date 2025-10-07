# bibliotecas

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
    return _url_re.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', safe)

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

# ====== CSS ======
st.markdown(
    """
<style>
/* ===== RESET ===== */
*{box-sizing:border-box}
html,body{margin:0;padding:0}
img{max-width:100%;height:auto;display:inline-block}
img.logo{height:44px!important;width:auto!important}

/* ===== VARS ===== */
:root{
  --content-max-width: min(96vw, 1400px);
  --header-height: 72px;
  --card-height: calc(100dvh - var(--header-height));
  --quadra-blue: #cfe3ff;

  /* chatgpt-like input */
  --input-max: 900px;
  --input-bottom: 40px;
  --input-shadow: 0 10px 24px rgba(14,47,120,.10);

  /* layout */
  --side-blue: #f4f9ff;
  --sidebar-w: 300px;     /* LARGURA DO SIDEBAR */
}

/* ===== Esconde UI nativa ===== */
header[data-testid="stHeader"]{display:none!important}
div[data-testid="stToolbar"]{display:none!important}
#MainMenu,footer{visibility:hidden;height:0!important}
html,body,.stApp,main,.stMain,.block-container,[data-testid="stAppViewContainer"]{
  height:100dvh!important;max-height:100dvh!important;overflow:hidden!important;overscroll-behavior:none
}
.block-container{padding:0!important;min-height:0!important}

/* laterais AZUL SÓLIDO */
.stApp{ background: var(--side-blue) !important; }

/* ===== Sidebar ===== */
section[data-testid="stSidebar"]{
  background:#ffffff !important;
  border-right:1px solid rgba(59,130,246,.10);
  visibility: visible !important;
  transform: none !important;
  min-width: var(--sidebar-w) !important;
  width: var(--sidebar-w) !important;
}
section[data-testid="stSidebar"] > div{
  height:100dvh !important;
  overflow-y:auto !important;
  padding:14px 10px 18px 10px !important;
}
div[data-testid="stSidebarCollapseButton"]{ display:none !important; }
div[data-testid="stAppViewContainer"]{ margin-left: var(--sidebar-w) !important; }

.sidebar-header{
  font-size:0.95rem;
  font-weight:700;
  letter-spacing:.02em;
  color:#1f2937;
  margin:6px 6px 8px 6px;
}
.sidebar-row{
  display:flex;align-items:center;justify-content:space-between;
  margin:-2px 6px 12px 6px;
}
.sidebar-sub{
  font-size:.78rem;color:#6b7280;
}
.trash-btn > button{
  width:36px;height:32px;padding:0 !important;
  border-radius:8px !important;
  border:1px solid rgba(37,99,235,0.12) !important;
  background:#fff !important;
  box-shadow:0 3px 10px rgba(15,23,42,.04) !important;
}

/* Botões de histórico */
.hist-btn > button{
  justify-content:flex-start !important;
  white-space:nowrap !important;
  overflow:hidden !important;
  text-overflow:ellipsis !important;
  border-radius:10px !important;
  border:1px solid rgba(37,99,235,0.12) !important;
  background:#f8fafc !important;
  box-shadow:0 3px 10px rgba(15,23,42,.04) !important;
  margin: 6px 4px;
}
.hist-empty{ color:#9ca3af;font-size:.9rem;padding:8px 10px; }

/* ===== Header fixo ===== */
.header{
  position:fixed;inset:0 0 auto 0;height:var(--header-height);
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px;background:#fff;z-index:1000;
  border-bottom:1px solid rgba(59,130,246,.08);box-shadow:0 6px 18px rgba(14,47,120,.04)
}
.header-left{display:flex;align-items:center;gap:10px;font-weight:600}
.header-left .title-sub{font-weight:500;font-size:.85rem;color:#6b7280;margin-top:-4px}
.header-right{display:flex;align-items:center;gap:12px}

/* ===== Content ===== */
.content{
  max-width:var(--content-max-width);
  margin:var(--header-height) auto 0;
  padding:0 8px;
}

/* ===== Card do chat (scroll só aqui) ===== */
.chat-card{
  position:relative;
  background:linear-gradient(135deg,#fff,#fbfdff);
  border-radius:12px 12px 0 0;
  border:1px solid var(--quadra-blue);
  border-bottom:none;
  box-shadow:0 14px 36px rgba(14,47,120,.04);
  padding:20px;
  height:var(--card-height);
  overflow-y:auto;scroll-behavior:smooth;
  padding-bottom: 140px;
  scroll-padding-bottom: 140px;
}

/* ===== Mensagens ===== */
.message-row{display:flex;margin:10px 4px}
.message-row.user{justify-content:flex-end}
.message-row.assistant{justify-content:flex-start}
.bubble{
  max-width:88%;padding:12px 14px;border-radius:12px;
  font-size:15px;line-height:1.35;box-shadow:0 6px 14px rgba(15,23,42,.03);
  word-wrap:break-word
}
.bubble.user{
  background:linear-gradient(180deg,#fff,#eef2ff);
  border:1px solid rgba(59,130,246,.14);border-bottom-right-radius:6px
}
.bubble.assistant{
  background:#f8fafc;border:1px solid rgba(15,23,42,.06);border-bottom-left-radius:6px
}

/* ===== ChatGPT-like: input flutuante ===== */
[data-testid="stChatInput"]{
  position: fixed !important;
  /* centraliza no espaço útil (área sem o sidebar) */
  left: calc(50% + var(--sidebar-w) / 2) !important;
  transform: translateX(-50%) !important;
  bottom: var(--input-bottom) !important;
  width: min(var(--input-max), 96vw) !important;
  z-index: 1200;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
}
[data-testid="stChatInput"] > div{
  width: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  background: #ffffff !important;
  border: 1.5px solid #2f64d0 !important;
  border-radius: 999px !important;
  box-shadow: var(--input-shadow) !important;
  overflow: hidden;
}

/* AUTO-GROW */
[data-testid="stChatInput"] textarea{
  width: 100% !important;
  background: transparent !important;
  border: none !important;
  border-radius: 999px !important;
  padding: 12px 16px !important;
  font-size: 16px !important;
  box-shadow: none !important;
  outline: none !important;
  height: auto !important;
  min-height: 44px !important;
  max-height: 220px !important;
  overflow-y: hidden !important;
}
[data-testid="stChatInput"] button{ margin-right: 8px !important; }

/* ===== SKIRT (rodapé sólido) ===== */
.bottom-gradient-fix{
  position: fixed; left: 0; right: 0; bottom: 0;
  height: 72px; background: var(--side-blue) !important;
  z-index: 10 !important; pointer-events: none;
}
@supports (padding-bottom: env(safe-area-inset-bottom)) {
  .bottom-gradient-fix{ height: calc(72px + env(safe-area-inset-bottom)); }
}

/* input sempre na frente do skirt */
[data-testid="stChatInput"]{ z-index: 5000 !important; }
[data-testid="stChatInput"] > div{ position: relative !important; z-index: 5001 !important; }
</style>
""",
    unsafe_allow_html=True,
)

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

    # Linha: "Perguntas desta sessão" + ícone de lixeira à direita
    col_l, col_r = st.columns([1, 0.2])
    with col_l:
      st.markdown('<div class="sidebar-sub">Perguntas desta sessão</div>', unsafe_allow_html=True)
    with col_r:
      # botão ícone (lixeira)
      trash_clicked = st.button("🗑️", key="trash", help="Limpar histórico", use_container_width=True)
      if trash_clicked:
          st.session_state.historico = []
          do_rerun()
    st.markdown('<div class="sidebar-row"></div>', unsafe_allow_html=True)

    if not st.session_state.historico:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for i, (pergunta_hist, _resp) in enumerate(reversed(st.session_state.historico)):
            idx_real = len(st.session_state.historico) - 1 - i
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80:
                titulo = titulo[:80] + "…"
            # botão full-width para reenviar
            if st.button(titulo or "(vazio)", key=f"hist_{idx_real}", use_container_width=True):
                reenviar_pergunta(st.session_state.historico[idx_real][0])
            st.markdown('<div class="hist-btn"></div>', unsafe_allow_html=True)

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
st.markdown(
    """
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
  function autoGrow(){
    const ta = document.querySelector('[data-testid="stChatInput"] textarea');
    if (!ta) return;
    const MAX = 220;
    ta.style.height = 'auto';
    const desired = Math.min(ta.scrollHeight, MAX);
    ta.style.height = desired + 'px';
    ta.style.overflowY = (ta.scrollHeight > MAX) ? 'auto' : 'hidden';
  }
  const ro = new ResizeObserver(() => { ajustaEspaco(); });
  ro.observe(document.body);
  window.addEventListener('load',  () => { autoGrow(); ajustaEspaco(); });
  window.addEventListener('resize',() => { autoGrow(); ajustaEspaco(); });
  document.addEventListener('input', (e) => {
    if (e.target && e.target.matches('[data-testid="stChatInput"] textarea')) {
      autoGrow(); ajustaEspaco();
    }
  });
  setTimeout(() => { autoGrow(); ajustaEspaco(); }, 0);
  setTimeout(() => { autoGrow(); ajustaEspaco(); }, 150);
})();
</script>
""",
    unsafe_allow_html=True,
)

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
