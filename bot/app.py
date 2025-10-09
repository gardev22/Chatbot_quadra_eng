# app.py

import streamlit as st
import base64
import os
import re
import warnings
from html import escape
from openai_backend import responder_pergunta

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG DA PÁGINA (favicon + título da aba) ======
LOGO_PATH = "data/logo_quadra.png"  # mesmo logo do cabeçalho
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,             # troca o favicon pelo logo da Quadra
    layout="wide",
    initial_sidebar_state="expanded",
)

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== LOGO (para exibir no cabeçalho) ======
def carregar_imagem_base64(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_b64 = carregar_imagem_base64(LOGO_PATH)

# ====== ESTADO ======
if "historico" not in st.session_state:
    st.session_state.historico = []
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
st.markdown("""
<style>
*{box-sizing:border-box} html,body{margin:0;padding:0} img{max-width:100%;height:auto;display:inline-block}
img.logo{height:44px!important;width:auto!important}

:root{
  --content-max-width:min(96vw,1400px);
  --header-height:72px;
  --skirt-h:72px;
  --chat-safe-gap: 300px;
  --card-height:calc(100dvh - var(--header-height) - 24px);
  --quadra-blue:#cfe3ff;
  --input-max:900px;
  --input-bottom:60px;
  --input-shadow:0 10px 24px rgba(14,47,120,.10);
  --side-blue:#f4f9ff;
  --skirt-bg:#ffffff;
  --sidebar-w:300px;
}

header[data-testid="stHeader"]{display:none!important}
div[data-testid="stToolbar"]{display:none!important}
#MainMenu,footer{visibility:hidden;height:0!important}
html,body,.stApp,main,.stMain,.block-container,[data-testid="stAppViewContainer"]{
  height:100dvh!important;max-height:100dvh!important;overflow:hidden!important;overscroll-behavior:none
}
.block-container{padding:0!important;min-height:0!important}
.stApp{background: var(--side-blue) !important}

.header{position:fixed;inset:0 0 auto 0;height:var(--header-height);
display:flex;align-items:center;justify-content:space-between;
padding:10px 16px;background:#fff;z-index:1000;
border-bottom:1px solid rgba(59,130,246,.08);box-shadow:0 6px 18px rgba(14,47,120,.04)}

.header-left{display:flex;align-items:center;gap:10px;font-weight:600}
.header-left .title-sub{font-weight:500;font-size:.85rem;color:#6b7280;margin-top:-4px}
.header-right{display:flex;align-items:center;gap:12px}

section[data-testid="stSidebar"]{
  position: fixed !important; top: var(--header-height) !important; left:0 !important;
  height: calc(100dvh - var(--header-height) - var(--skirt-h)) !important;
  width: var(--sidebar-w) !important; min-width: var(--sidebar-w) !important;
  margin:0!important; padding:0!important; background:#fff!important;
  border-right:1px solid rgba(59,130,246,.10); z-index:900 !important; transform:none !important;
  visibility: visible !important; overflow:hidden !important;
}

section[data-testid="stSidebar"] > div{
  height:100% !important;
  overflow-y:auto !important;
  padding-top: -10px !important;
  padding-right: 12px !important;
  padding-bottom: 12px !important;
  padding-left: 12px !important;
  margin:0 !important;
}

div[data-testid="stSidebarCollapseButton"]{ display: none !important; }
div[data-testid="stAppViewContainer"]{ margin-left: var(--sidebar-w) !important; }

.content{
  max-width:var(--content-max-width);
  margin:var(--header-height) auto 0;
  padding:8px;
}

.chat-card{
  position:relative;
  background:linear-gradient(135deg,#fff,#fbfdff);
  border-radius:12px 12px 0 0;
  border:1px solid var(--quadra-blue);
  border-bottom:none;
  box-shadow:0 14px 36px rgba(14,47,120,.04);
  padding:20px;
  height:var(--card-height);
  overflow-y:auto;
  scroll-behavior:smooth;
  padding-bottom: var(--chat-safe-gap);
  scroll-padding-bottom: var(--chat-safe-gap);
}

.message-row{display:flex;margin:12px 4px; scroll-margin-bottom: calc(var(--chat-safe-gap) + 16px); }
.message-row.user{justify-content:flex-end}
.message-row.assistant{justify-content:flex-start}
.bubble{max-width:88%;padding:14px 16px;border-radius:12px;font-size:15px;line-height:1.45;box-shadow:0 6px 14px rgba(15,23,42,.03);word-wrap:break-word}
.bubble.user{background:linear-gradient(180deg,#fff,#eef2ff);border:1px solid rgba(59,130,246,0.14);border-bottom-right-radius:6px}
.bubble.assistant{background:#f8fafc;border:1px solid rgba(15,23,42,.06);border-bottom-left-radius:6px}

[data-testid="stChatInput"]{
  position: fixed !important;
  left: calc( var(--sidebar-w) + (100vw - var(--sidebar-w)) / 2 ) !important;
  transform: translateX(-50%) !important;
  bottom: var(--input-bottom) !important;
  width: min(var(--input-max), 96vw) !important;
  z-index: 5000;
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
[data-testid="stChatInput"] textarea{
  width: 100% !important;
  background: transparent !important;
  border: none !important;
  border-radius: 999px !important;
  padding: 18px 20px !important;
  font-size: 16px !important;
  box-shadow: none !important;
  outline: none !important;
  height: auto !important;
  min-height: 44px !important;
  max-height: 220px !important;
  overflow-y: hidden !important;
}
[data-testid="stChatInput"] button{ margin-right: 8px !important; }

.bottom-gradient-fix{
  border-top: 1.5px solid #e5e7eb;
  position: fixed; left: 0; right: 0; bottom: 0;
  height: var(--skirt-h); background: var(--skirt-bg) !important;
  z-index: 10 !important; pointer-events: none;
}

.sidebar-header{ font-size:1.1rem;font-weight:700;letter-spacing:.02em;color:#1f2937; margin:0 4px -2px 2px; }
.sidebar-bar{ display:flex; align-items:center; justify-content:space-between; margin:0 4px 6px 2px; height:28px; }
.sidebar-sub{ font-size:.88rem; color:#6b7280; }

.trash-wrap{display:flex;align-items:center;justify-content:flex-end;height:28px;margin-left:6px;}
.trash-wrap button{background: transparent !important;border: none !important;box-shadow: none !important;width: 28px !important;height: 28px !important;font-size: 18px !important;line-height: 1 !important;cursor: pointer !important;display: flex !important;align-items: center !important;justify-content: center !important;margin:0 !important;padding:0 !important;}

.hist-empty{ color:#9ca3af;font-size:.9rem;padding:8px 10px; }

div[data-testid="stSidebarContent"]{ padding-top: 15 !important; }
div[data-testid="stSidebarContent"] > *:first-child{ margin-top: 0 !important; }

.sidebar-header{ margin-top: -30px !important; }
.sidebar-bar{ margin-top: -24px !important; }

.hist-row{
  padding: 6px 6px;
  font-size: 1.1rem;
  color: #4b5563 !important;
  line-height: 1.35;
}
.hist-row + .hist-row{ margin-top: 6px; }
</style>
""", unsafe_allow_html=True)

# ====== HEADER HTML ======
logo_img_tag = f'<img class="logo" src="data:image/png;base64,{logo_b64}" />' if logo_b64 else '<div style="width:44px;height:44px;border-radius:8px;background:#eef2ff;display:inline-block;"></div>'

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
    <div style="text-align:right;font-size:0.9rem;color:#111827;">
      Usuário Demo<br><span style="font-weight:400;color:#6b7280;font-size:0.8rem;">usuario@exemplo.com</span>
    </div>
    <div class="user-circle">U</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ====== SIDEBAR ======
with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)

    # Barra superior com título + lixeira
    st.markdown("""
    <div class="sidebar-bar" style="display:flex;align-items:center;justify-content:space-between;">
        <div class="sidebar-sub">Perguntas desta sessão</div>
        <div class="trash-wrap">
            <button onclick="document.dispatchEvent(new CustomEvent('trash_clicked'))">🗑️</button>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Histórico simples
    st.markdown('<div style="max-height:calc(100% - 50px); overflow-y:auto; margin-top:2px;">', unsafe_allow_html=True)
    if not st.session_state.historico:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for pergunta_hist, _resp in st.session_state.historico:
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80:
                titulo = titulo[:80] + "…"
            st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# JS para capturar clique da lixeira
st.markdown("""
<script>
document.addEventListener('trash_clicked', () => {
    fetch('/_stcore/trash', {method:'POST'}).then(()=>location.reload());
});
</script>
""", unsafe_allow_html=True)

# Python para resetar histórico quando a lixeira é clicada
if st.query_params.get("trash"):
    st.session_state.historico = []
    do_rerun()

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

# âncora para auto-scroll
msgs_html.append('<div id="chatEnd" style="height:1px;"></div>')

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
    if(!input||!card) return;
    const rect = input.getBoundingClientRect();
    const gapVar = getComputedStyle(document.documentElement)
      .getPropertyValue('--chat-safe-gap').trim();
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

  window.addEventListener('load',()=>{
    autoGrow();
    ajustaEspaco();
    scrollToEnd(false);
  });
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
    const mo = new MutationObserver(()=>{
      ajustaEspaco();
      scrollToEnd(true);
    });
    mo.observe(card, {childList:true, subtree:false});
  }
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
