import streamlit as st
import base64, os, re, warnings
from html import escape
from openai_backend import responder_pergunta

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG ======
LOGO_PATH = "data/logo_quadra.png"
st.set_page_config(page_title="Chatbot Quadra", page_icon=LOGO_PATH, layout="wide", initial_sidebar_state="expanded")

def do_rerun():
    if hasattr(st, "rerun"): st.rerun()
    else: st.experimental_rerun()

def carregar_imagem_base64(path):
    if not os.path.exists(path): return None
    with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
logo_b64 = carregar_imagem_base64(LOGO_PATH)

# ====== ESTADO ======
st.session_state.setdefault("historico", [])
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

# ====== MARCAÇÃO ======
def formatar_markdown_basico(text: str) -> str:
    if not text: return ""
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    return text.replace("\n", "<br>")

def linkify(text: str) -> str: return formatar_markdown_basico(text or "")

# ====== CSS ======
st.markdown("""
<style>
:root{
  --content-max-width:min(96vw,1400px);
  --header-height:72px;
  --chat-safe-gap:300px;
  --card-height:calc(100dvh - var(--header-height) - 24px);
  --input-max:900px; --input-bottom:60px;
  --bg:#0F1115; --panel:#0B0D10; --panel-header:#14171C; --panel-alt:#1C1F26; --border:#242833;
  --text:#E5E7EB; --text-dim:#C9D1D9; --muted:#9AA4B2;
  --link:#B9C0CA; --link-hover:#FFFFFF;
  --bubble-user:#222833; --bubble-assistant:#232833;
  --input-bg:#1E222B; --input-border:#323949;
  --sidebar-w:270px; --brand:#3b82f6;
}
*{box-sizing:border-box} html,body,.stApp,.block-container,[data-testid="stAppViewContainer"]{height:100dvh;overflow:hidden}
.block-container{padding:0} header[data-testid="stHeader"],div[data-testid="stToolbar"],#MainMenu,footer{display:none}
.stApp{background:var(--bg);color:var(--text)}
/* Header */
.header{position:fixed;inset:0 0 auto 0;height:var(--header-height);display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--panel-header);z-index:1000;border-bottom:1px solid var(--border)}
img.logo{height:44px}
/* Sidebar */
section[data-testid="stSidebar"]{position:fixed;top:var(--header-height);left:0;height:calc(100dvh - var(--header-height));width:var(--sidebar-w);min-width:var(--sidebar-w);background:var(--panel);border-right:1px solid var(--border);z-index:900;overflow:hidden;color:var(--text)}
section[data-testid="stSidebar"]>div{height:100%;overflow-y:auto;padding:0 12px 12px}
div[data-testid="stSidebarCollapseButton"]{display:none} div[data-testid="stAppViewContainer"]{margin-left:var(--sidebar-w)}
.sidebar-header{font-size:1.1rem;font-weight:700;margin:0 4px -2px 2px}
.sidebar-sub{font-size:.88rem;color:var(--muted)}
.hist-row{padding:6px 6px;font-size:1.1rem;color:var(--text-dim);border-radius:8px}
.hist-row+.hist-row{margin-top:6px}.hist-row:hover{background:#161a20}
/* Chat area */
.content{max-width:var(--content-max-width);margin:var(--header-height) auto 0;padding:8px}
#chatCard{position:relative;background:var(--panel-alt);border-radius:12px 12px 0 0;padding:20px;height:var(--card-height);overflow-y:auto;padding-bottom:var(--chat-safe-gap);scroll-padding-bottom:var(--chat-safe-gap)}
.message-row{display:flex;margin:12px 4px}
.message-row.user{justify-content:flex-end}.message-row.assistant{justify-content:flex-start}
.bubble{max-width:88%;padding:14px 16px;border-radius:12px;font-size:15px;line-height:1.45;color:var(--text)}
.bubble.user{background:var(--bubble-user);border-bottom-right-radius:6px}
.bubble.assistant{background:var(--bubble-assistant);border-bottom-left-radius:6px}
#chatCard a{color:var(--link);text-decoration:underline} #chatCard a:hover{color:var(--link-hover)}
/* ===== Focus branco no chatinput + cursor branco ===== */
[data-testid="stChatInput"]{position:fixed;left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2);transform:translateX(-50%);bottom:var(--input-bottom);width:min(var(--input-max),96vw);z-index:5000;background:transparent}
[data-testid="stChatInput"] > div{
  background:var(--input-bg); border:1px solid var(--input-border); border-radius:999px; box-shadow:0 10px 24px rgba(0,0,0,.35); overflow:hidden; transition:border-color .15s ease, box-shadow .15s ease;
}
[data-testid="stChatInput"]:focus-within > div{
  border-color:#ffffff !important; /* AQUI: linha/borda branca ao focar */
  box-shadow:0 0 0 1px rgba(255,255,255,.35) inset, 0 10px 24px rgba(0,0,0,.35) !important;
}
[data-testid="stChatInput"] textarea{width:100%;border:none;border-radius:999px;padding:18px 20px;font-size:16px;outline:none;min-height:44px;max-height:220px;overflow-y:hidden;caret-color:#ffffff !important; /* cursor branco */ color:var(--text)}
[data-testid="stChatInput"] textarea::placeholder{color:var(--muted)}
[data-testid="stChatInput"] button{margin-right:8px;border:none;background:transparent;color:var(--text-dim)}
[data-testid="stChatInput"] svg{fill:currentColor}
/* Remover faixa branca padrão Streamlit */
[data-testid="stBottomBlockContainer"]{height:0 !important;min-height:0 !important;padding:0 !important;margin:0 !important;background:transparent !important;box-shadow:none !important;border:none !important}
/* ===== Spinner (bolinha azul) ===== */
.spinner{width:18px;height:18px;border:3px solid rgba(59,130,246,.25);border-top-color:var(--brand);border-radius:50%;display:inline-block;animation:spin .9s linear infinite;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner-wrap{display:flex;align-items:center;gap:10px;color:#cbd5e1;font-size:14px}
*::-webkit-scrollbar{width:10px;height:10px} *::-webkit-scrollbar-thumb{background:#2C3340;border-radius:8px} *::-webkit-scrollbar-track{background:#0F1115}
</style>
""", unsafe_allow_html=True)

# ====== HEADER ======
logo_tag = (f'<img class="logo" src="data:image/png;base64,{logo_b64}" />'
            if logo_b64 else '<div style="width:44px;height:44px;border-radius:8px;background:#eef2ff"></div>')
st.markdown(f"""
<div class="header">
  <div class="header-left">{logo_tag}
    <div>Chatbot Quadra<div class="title-sub" style="font-size:.85rem;color:#9aa4b2">Assistente Inteligente</div></div>
  </div>
  <div class="header-right" style="display:flex;align-items:center;gap:12px;color:#e5e7eb">
    <div style="text-align:right;font-size:0.9rem;">Usuário Demo<br><span style="font-weight:400;color:#94a3b8;font-size:0.8rem;">usuario@exemplo.com</span></div>
    <div class="user-circle" style="width:36px;height:36px;border-radius:50%;background:#1f2937;display:flex;align-items:center;justify-content:center">U</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ====== SIDEBAR ======
with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-sub">Perguntas desta sessão</div>', unsafe_allow_html=True)
    if not st.session_state.historico:
        st.markdown('<div style="color:#9aa4b2;padding:8px 10px">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for pergunta_hist, _ in st.session_state.historico:
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80: titulo = titulo[:80] + "…"
            st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

# ====== RENDER MENSAGENS ======
msgs = []
for pergunta, resposta in st.session_state.historico:
    msgs.append(f'<div class="message-row user"><div class="bubble user">{linkify(pergunta)}</div></div>')
    if resposta:
        msgs.append(f'<div class="message-row assistant"><div class="bubble assistant">{linkify(resposta)}</div></div>')

# (NOVIDADE) Spinner como última “mensagem do assistente” enquanto processa
if st.session_state.awaiting_answer and st.session_state.answering_started:
    msgs.append(
        '<div class="message-row assistant"><div class="bubble assistant">'
        '<span class="spinner"></span><span style="margin-left:10px">Gerando resposta…</span>'
        '</div></div>'
    )

if not msgs:
    msgs.append('<div style="color:#9ca3af;text-align:center;margin-top:20px;">.</div>')
msgs.append('<div id="chatEnd" style="height:1px;"></div>')
st.markdown(f'<div class="content"><div id="chatCard">{"".join(msgs)}</div></div>', unsafe_allow_html=True)

# ====== JS (placeholder some no foco, autogrow, scroll) ======
st.markdown("""
<script>
(function(){
  function autoGrow(){
    const ta = document.querySelector('[data-testid="stChatInput"] textarea');
    if(!ta) return;
    const MAX = 220;
    ta.style.height = 'auto';
    const desired = Math.min(ta.scrollHeight, MAX);
    ta.style.height = desired + 'px';
    ta.style.overflowY = (ta.scrollHeight > MAX) ? 'auto' : 'hidden';
  }
  function ajustaEspaco(){
    const input = document.querySelector('[data-testid="stChatInput"]');
    const card = document.getElementById('chatCard');
    if(!input || !card) return;
    const rect = input.getBoundingClientRect();
    const gap = 300;
    const alturaEfetiva = (window.innerHeight - rect.top) + gap;
    card.style.paddingBottom = alturaEfetiva + 'px';
    card.style.scrollPaddingBottom = alturaEfetiva + 'px';
  }
  function scrollToEnd(smooth=true){
    const end = document.getElementById('chatEnd');
    if(end) end.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'end'});
  }

  // Placeholder: some ao focar, volta se vazio no blur
  const ta = document.querySelector('[data-testid="stChatInput"] textarea');
  if(ta){
    const originalPh = ta.getAttribute('placeholder') || '';
    ta.addEventListener('focus', ()=>{ ta.setAttribute('data-ph', originalPh); ta.setAttribute('placeholder',''); });
    ta.addEventListener('blur', ()=>{ if(!ta.value.trim()) ta.setAttribute('placeholder', ta.getAttribute('data-ph') || originalPh); });
  }

  const ro = new ResizeObserver(()=>{ajustaEspaco();});
  ro.observe(document.body);
  window.addEventListener('load',()=>{autoGrow();ajustaEspaco();scrollToEnd(false);});
  window.addEventListener('resize',()=>{autoGrow();ajustaEspaco();});
  document.addEventListener('input',(e)=>{ if(e.target && e.target.matches('[data-testid="stChatInput"] textarea')){ autoGrow();ajustaEspaco(); }});
  setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);

  const card = document.getElementById('chatCard');
  if(card){
    const mo = new MutationObserver(()=>{ ajustaEspaco(); scrollToEnd(true); });
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
