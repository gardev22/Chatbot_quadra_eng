# app.py

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

# ====== LOGO (cabeçalho) ======
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
st.session_state.setdefault("_last_input", None)  # debounce anti-duplicata

# ====== MARCAÇÃO (markdown simples -> HTML seguro) ======
def formatar_markdown_basico(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r'(https?://[^\s<>"\]]+)',
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
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

# ====== CSS ======
st.markdown("""
<style>
/* ==== RESET ==== */
*{box-sizing:border-box}
html,body{margin:0;padding:0}
img{max-width:100%;height:auto;display:inline-block}
img.logo{height:44px!important;width:auto!important}

/* ==== VARS ==== */
:root{
  --content-max-width:min(96vw,1400px);
  --header-height:72px;
  --skirt-h:0px;
  --chat-safe-gap:300px;
  --card-height:calc(100dvh - var(--header-height) - 24px);
  --input-max:900px;
  --input-bottom:60px;
  --sidebar-w:270px;

  --bg:#1C1F26;
  --panel:#0B0D10;
  --panel-header:#14171C;
  --border:#242833;

  --text:#E5E7EB; --text-dim:#C9D1D9; --muted:#9AA4B2;
  --link:#B9C0CA; --link-hover:#FFFFFF;

  --bubble-user:#242932;
  --bubble-assistant:#242b35;

  --input-bg:#202633;
  --input-border:#323949;
}

/* ==== FUNDO UNIFICADO ==== */
html,body,#root,.stApp,main,.stMain,.block-container,
[data-testid="stAppViewContainer"],[data-testid="stBottomBlockContainer"],
[data-testid="stDecoration"],[data-testid="stStatusWidget"],
[data-testid="StyledFullScreenContainer"]{
  background:var(--bg)!important; color:var(--text)!important;
  height:100dvh!important; max-height:100dvh!important; overflow:hidden!important;
}
body::before{content:"";position:fixed;inset:0;background:var(--bg);z-index:-2;pointer-events:none}

/* ==== Chrome do Streamlit ==== */
header[data-testid="stHeader"]{display:none!important}
div[data-testid="stToolbar"]{display:none!important}
#MainMenu,footer{visibility:hidden;height:0!important}
.block-container{padding:0!important;min-height:0!important}

/* ==== HEADER ==== */
.header{
  position:fixed; inset:0 0 auto 0; height:var(--header-height);
  display:flex; align-items:center; justify-content:space-between;
  padding:10px 16px; background:var(--panel-header); z-index:1000;
  border-bottom:1px solid var(--border);
}
.header-left{display:flex;align-items:center;gap:10px;font-weight:600;color:var(--text)}
.header-left .title-sub{font-weight:500;font-size:.85rem;color:var(--muted);margin-top:-4px}
.header-right{display:flex;align-items:center;gap:12px;color:var(--text)!important}
.header-right div{color:var(--text)!important}
.header-right span{color:var(--muted)!important}
.header a{
  color:var(--link)!important; text-decoration:none!important;
  border:1px solid var(--border)!important; padding:8px 12px; border-radius:10px; display:inline-block;
}
.header a:hover{color:var(--link-hover)!important; border-color:#3B4250!important}

/* ==== SIDEBAR ==== */
section[data-testid="stSidebar"]{
  position:fixed!important; top:var(--header-height)!important; left:0!important;
  height:calc(100dvh - var(--header-height))!important;
  width:var(--sidebar-w)!important; min-width:var(--sidebar-w)!important;
  margin:0!important; padding:0!important; background:var(--panel)!important;
  border-right:1px solid var(--border); z-index:900!important; transform:none!important;
  visibility:visible!important; overflow:hidden!important; color:var(--text);
}
section[data-testid="stSidebar"] *{ background:transparent!important; color:var(--text)!important }
section[data-testid="stSidebar"]>div{ height:100%!important; overflow-y:auto!important; padding:0 12px 12px 12px!important }
div[data-testid="stSidebarCollapseButton"]{display:none!important}
div[data-testid="stAppViewContainer"]{ margin-left:var(--sidebar-w)!important }

/* ==== CONTENT ==== */
.content{ max-width:var(--content-max-width); margin:var(--header-height) auto 0; padding:8px }

/* ==== CHAT CARD ==== */
#chatCard,.chat-card{
  position:relative; z-index:50 !important;            /* sobe o chat acima de tudo */
  background:var(--bg)!important;
  border:none!important; border-radius:0!important; box-shadow:none!important;
  padding:20px; height:var(--card-height); overflow-y:auto; scroll-behavior:smooth;
  padding-bottom:var(--chat-safe-gap); scroll-padding-bottom:var(--chat-safe-gap);
  color:var(--text);
}

/* ==== MENSAGENS ==== */
.message-row{display:flex;margin:12px 4px; scroll-margin-bottom:calc(var(--chat-safe-gap) + 16px)}
.message-row.user{justify-content:flex-end}
.message-row.assistant{justify-content:flex-start}
.bubble{
  max-width:88%; padding:14px 16px; border-radius:12px; font-size:15px; line-height:1.45;
  color:var(--text); word-wrap:break-word; border:1px solid transparent!important; box-shadow:none!important;
}
.bubble.user{background:var(--bubble-user)!important; border-bottom-right-radius:6px}
.bubble.assistant{background:var(--bubble-assistant)!important; border-bottom-left-radius:6px}
.bubble, .bubble *{ color:#E5E7EB !important; }
.bubble a{ color:#B9C0CA !important; text-decoration:underline; }
.bubble a:hover{ color:#FFFFFF !important; }

/* ==== INPUT ==== */
[data-testid="stChatInput"]{
  position:fixed!important;
  left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2)!important;
  transform:translateX(-50%)!important;
  bottom:var(--input-bottom)!important;
  width:min(var(--input-max),96vw)!important;
  z-index:5000; background:transparent!important; border:none!important; box-shadow:none!important; padding:0!important;
}
[data-testid="stChatInput"] *{ background:transparent!important; color:var(--text)!important }
[data-testid="stChatInput"]>div{
  background:var(--input-bg)!important; border:1px solid var(--input-border)!important;
  border-radius:999px!important; box-shadow:0 10px 24px rgba(0,0,0,.35)!important; overflow:hidden;
}
[data-testid="stChatInput"] textarea{
  width:100%!important; border:none!important; border-radius:999px!important;
  padding:18px 20px!important; font-size:16px!important; outline:none!important;
  height:auto!important; min-height:44px!important; max-height:220px!important; overflow-y:hidden!important;
  color:var(--text)!important; caret-color:#ffffff!important;
}
[data-testid="stChatInput"] textarea::placeholder{ color:var(--muted)!important }
[data-testid="stChatInput"] button{ margin-right:8px!important; border:none!important; color:var(--text-dim)!important }
[data-testid="stChatInput"] svg{ fill:currentColor!important }

/* ==== OUTROS ==== */
.bottom-gradient-fix{ display:none!important }
.sidebar-header{font-size:1.1rem;font-weight:700;letter-spacing:.02em;color:var(--text);margin:0 4px -2px 2px}
.sidebar-bar{display:flex;align-items:center;justify-content:space-between;margin:0 4px 6px 2px;height:28px}
.sidebar-sub{font-size:.88rem;color:var(--muted)}
.hist-empty{color:var(--muted);font-size:.9rem;padding:8px 10px}
div[data-testid="stSidebarContent"]{padding-top:15!important}
div[data-testid="stSidebarContent"] > *:first-child{margin-top:0!important}
.sidebar-header{margin-top:-30px!important}
.sidebar-bar{margin-top:-24px!important}
.hist-row{ padding:6px 6px; font-size:1.1rem; color:var(--text-dim)!important; line-height:1.35; border-radius:8px }
.hist-row + .hist-row{margin-top:6px}
.hist-row:hover{background:#171b21}

/* ==== SCROLLBARS ==== */
*::-webkit-scrollbar{width:10px;height:10px}
*::-webkit-scrollbar-thumb{background:#2C3340;border-radius:8px}
*::-webkit-scrollbar-track{background:#1C1F26}

/* ==== ANTI-OVERLAY (mata decorações que podem cobrir o chat) ==== */
[data-testid="stStatusWidget"],
[data-testid="stDecoration"],
[data-testid="StyledFullScreenContainer"]{
  display:none !important;
}
</style>
""", unsafe_allow_html=True)

# ====== HEADER HTML ======
logo_img_tag = (
    f'<img class="logo" src="data:image/png;base64,{logo_b64}" />'
    if logo_b64
    else '<div style="width:44px;height:44px;border-radius:8px;background:#eef2ff;display:inline-block;"></div>'
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
    <a href="#" style="text-decoration:none;color:#B9C0CA;font-weight:600;border:1px solid #242833;padding:8px 12px;border-radius:10px;display:inline-block;">⚙ Configurações</a>
    <div style="text-align:right;font-size:0.9rem;color:#E5E7EB;">
      Usuário Demo<br><span style="font-weight:400;color:#9AA4B2;font-size:0.8rem;">usuario@exemplo.com</span>
    </div>
    <div class="user-circle">U</div>
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

if not msgs_html:
    msgs_html.append('<div style="color:#9aa4b2;text-align:center;margin-top:20px;">.</div>')

# âncora para auto-scroll
msgs_html.append('<div id="chatEnd" style="height:1px;"></div>')

st.markdown(f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>', unsafe_allow_html=True)

# ====== JS: ajusta espaço do input e auto-scroll ======
st.markdown("""
<script>
(function(){
  function ajustaEspaco(){
    const input = document.querySelector('[data-testid="stChatInput"]');
    const card  = document.getElementById('chatCard');
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
  window.addEventListener('load',()=>{autoGrow();ajustaEspaco();scrollToEnd(false);});
  window.addEventListener('resize',()=>{autoGrow();ajustaEspaco();});
  document.addEventListener('input',(e)=>{
    if(e.target&&e.target.matches('[data-testid="stChatInput"] textarea')){autoGrow();ajustaEspaco();}
  });
  setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
  setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
  const card = document.getElementById('chatCard');
  if(card){
    const mo = new MutationObserver(()=>{ajustaEspaco();scrollToEnd(true);});
    mo.observe(card, {childList:true, subtree:false});
  }
})();
</script>
""", unsafe_allow_html=True)

# ====== INPUT ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")


# ====== FLUXO (3 fases com debounce corrigido) ======

# Fase 1: usuário enviou a pergunta
if pergunta and pergunta.strip():
    q = pergunta.strip()

    # Debounce: evita reprocessar o mesmo texto
    if st.session_state._last_input != q:
        st.session_state._last_input = q
        st.session_state.historico.append((q, ""))  # mostra mensagem imediatamente
        st.session_state.pending_index = len(st.session_state.historico) - 1
        st.session_state.pending_question = q
        st.session_state.awaiting_answer = True
        st.session_state.answering_started = False  # ainda não começou a responder

# Fase 2: processa resposta apenas se há pergunta pendente
if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started = True  # marca como em andamento
    q = st.session_state.pending_question

    try:
        resposta = responder_pergunta(q)
    except Exception as e:
        resposta = f"❌ Erro ao consultar o backend: {e}"

    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        st.session_state.historico[idx] = (st.session_state.historico[idx][0], resposta)

    # limpa estados
    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    st.session_state._last_input = None

    st.experimental_rerun()
