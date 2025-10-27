# app.py - Frontend do Chatbot Quadra (Corrigido)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape
# Certifique-se de que o openai_backend.py está no mesmo diretório
from openai_backend import responder_pergunta 

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG DA PÁGINA ======
# Assumindo que o path 'data/logo_quadra.png' está correto
LOGO_PATH = "data/logo_quadra.png" 
st.set_page_config(
    page_title="Chatbot Quadra",
    page_icon=LOGO_PATH,
    layout="wide",
    # MANTIDO: O CSS está configurado para "sequestrar" a sidebar e torná-la fixa
    initial_sidebar_state="expanded", 
)

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== LOGO (para cabeçalho) ======
def carregar_imagem_base64(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

logo_b64 = carregar_imagem_base64(LOGO_PATH)

# ====== ESTADO (Início da Sessão) ======
if "historico" not in st.session_state:
    st.session_state.historico = []

st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

# ====== MARCAÇÃO (Formatação de Texto) ======
def formatar_markdown_basico(text: str) -> str:
    if not text:
        return ""
    # 1. Links (transforma URLs em links clicáveis, respeitando a quebra de linha)
    text = re.sub(
        r'(https?://[^\s<>"\]]+)',
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    # 2. Negrito (**)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # 3. Itálico (*)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    # 4. Quebras de Linha
    text = text.replace("\n", "<br>")
    return text

def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

# Função de Reenvio (para cliques no histórico)
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

# ====== CSS (BLOCO COMPLETO) ======
# ATENÇÃO: É este bloco que estava quebrado e causava os problemas visuais.
st.markdown("""
<style>
/* ========= RESET / BASE ========= */
* { box-sizing: border-box }
html, body { margin: 0; padding: 0 }
img { max-width: 100%; height: auto; display: inline-block }
img.logo { height: 44px !important; width: auto !important }

/* ========= VARS (Customização) ========= */
:root{
    --content-max-width: min(96vw, 1400px);
    --header-height: 68px;
    --chat-safe-gap: 300px; /* espaço de segurança no final do chat */
    --card-height: calc(100dvh - var(--header-height) - 24px);
    --input-max: 900px;
    --input-bottom: 60px;

    /* Paleta escura */
    --bg:#0F1115;
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

    /* Ajustes finos da Sidebar */
    --sidebar-items-top-gap: -45px;
    --sidebar-sub-top-gap: -30px; 
    --sidebar-list-start-gap: 3px; 
}

/* ========= STREAMLIT CHROME (Remoção de elementos padrão) ========= */
header[data-testid="stHeader"]{ display:none !important }
div[data-testid="stToolbar"]{ display:none !important }
#MainMenu, footer{ visibility:hidden; height:0 !important }

html, body, .stApp, main, .stMain, .block-container, [data-testid="stAppViewContainer"]{
    height:100dvh !important;
    max-height:100dvh !important;
    overflow:hidden !important;
    overscroll-behavior:none;
}
.block-container{ padding:0 !important; min-height:0 !important }
.stApp{ background:var(--bg) !important; color:var(--text) !important }

/* ========= HEADER FIXO (Topo) ========= */
.header{
    position:fixed; inset:0 0 auto 0; height:var(--header-height);
    display:flex; align-items:center; justify-content:space-between;
    padding:10px 16px; background:var(--panel-header); z-index:1000;
    border-bottom:1px solid var(--border);
}
.header-left{ display:flex; align-items:center; gap:10px; font-weight:600; color:var(--text) }
.header-left .title-sub{ font-weight:500; font-size:.85rem; color:var(--muted); margin-top:-4px }
.header-right{ display:flex; align-items:center; gap:12px; color:var(--text) }
/* Estiliza o botão "Configurações" */
.header a{
    color:var(--link) !important; text-decoration:none;
    border:1px solid var(--border); padding:8px 12px; border-radius:10px; display:inline-block;
}
.header a:hover{ color:var(--link-hover) !important; border-color:#3B4250 }

/* ========= SIDEBAR (Customização e Fixação) ========= */
section[data-testid="stSidebar"]{
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
}
/* Limpa margens internas do Streamlit */
section[data-testid="stSidebar"] > div{ padding-top:0 !important; margin-top:0 !important; }
div[data-testid="stSidebarContent"]{ padding-top:0 !important; margin-top:0 !important; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{ padding-top:0 !important; margin-top:0 !important; }

/* Aplica os ajustes finos de espaçamento definidos em :root */
section[data-testid="stSidebar"] .sidebar-header{
    margin-top: var(--sidebar-items-top-gap) !important;
}
.sidebar-bar p,
.sidebar-header p{
    margin: 0 !important;
    line-height: 1.15 !important;
}
.sidebar-bar{
    margin-top: var(--sidebar-sub-top-gap) !important;
}
.hist-row:first-of-type{
    margin-top: var(--sidebar-list-start-gap) !important;
}

/* Afasta o conteúdo principal da sidebar */
div[data-testid="stAppViewContainer"]{ margin-left:var(--sidebar-w) !important }

.sidebar-header{ font-size:1.1rem; font-weight:700; letter-spacing:.02em; color:var(--text); margin:0 4px -2px 2px }
.sidebar-sub{ font-size:.88rem; color:var(--muted) }
.hist-empty{ color:var(--muted); font-size:.9rem; padding:8px 10px }
.hist-row{ padding:6px 6px; font-size:1.1rem; color:var(--text-dim) !important; line-height:1.35; border-radius:8px }
.hist-row + .hist-row{ margin-top:6px }
.hist-row:hover{ background:#161a20 }

/* ========= CONTEÚDO / CHAT (Mensagens) ========= */
.content{ max-width:var(--content-max-width); margin:var(--header-height) auto 0; padding:8px }
#chatCard, .chat-card{
    position:relative;
    z-index:50 !important;
    background:var(--panel-alt) !important;
    border:none !important; border-radius:12px 12px 0 0 !important; box-shadow:none !important;
    padding:20px;
    height:var(--card-height);
    overflow-y:auto; scroll-behavior:smooth;
    padding-bottom:var(--chat-safe-gap); scroll-padding-bottom:var(--chat-safe-gap);
    color:var(--text);
}
#chatCard *, .chat-card *{ position:relative; z-index:51 !important }

.message-row{ display:flex !important; margin:12px 4px; scroll-margin-bottom:calc(var(--chat-safe-gap) + 16px) }
.message-row.user{ justify-content:flex-end }
.message-row.assistant{ justify-content:flex-start }
.bubble{
    max-width:88%; padding:14px 16px; border-radius:12px; font-size:15px; line-height:1.45;
    color:var(--text); word-wrap:break-word; border:1px solid transparent !important; box-shadow:none !important;
}
.bubble.user{ background:var(--bubble-user); border-bottom-right-radius:6px }
.bubble.assistant{ background:var(--bubble-assistant); border-bottom-left-radius:6px }
.chat-card a{ color:var(--link); text-decoration:underline } .chat-card a:hover{ color:var(--link-hover) }

/* ========= CHAT INPUT (Fixação e Estilização) ========= */
[data-testid="stChatInput"]{
    position:fixed !important;
    /* Centraliza o input na área de conteúdo */
    left:calc(var(--sidebar-w) + (100vw - var(--sidebar-w))/2) !important; 
    transform:translateX(-50%) !important;
    bottom:var(--input-bottom) !important;
    width:min(var(--input-max), 96vw) !important;
    z-index:5000 !important;
    background:transparent !important;
    border:none !important;
    box-shadow:none !important;
    padding:0 !important;
}
[data-testid="stChatInput"] *{
    background:transparent !important;
    color:var(--text) !important;
}
[data-testid="stChatInput"] > div{
    background:var(--input-bg) !important;
    border:1px solid var(--input-border) !important;
    border-radius:999px !important;
    box-shadow:0 10px 24px rgba(0,0,0,.35) !important;
    overflow:hidden;
    transition:border-color .12s ease, box-shadow .12s ease;
}
[data-testid="stChatInput"] textarea{
    width:100% !important;
    border:none !important; border-radius:999px !important;
    padding:18px 20px !important; font-size:16px !important;
    outline:none !important; height:auto !important;
    min-height:44px !important; max-height:220px !important;
    overflow-y:hidden !important;
    caret-color:#ffffff !important;
}
[data-testid="stChatInput"] textarea::placeholder{ color:var(--muted) !important }
[data-testid="stChatInput"] textarea:focus::placeholder{ color:transparent !important; opacity:0 !important }
[data-testid="stChatInput"] button{
    margin-right:8px !important; border:none !important; background:transparent !important; color:var(--text-dim) !important;
}
[data-testid="stChatInput"] svg{ fill:currentColor !important }

/* ========= MATA DEFINITIVAMENTE A FAIXA BRANCA (bottom block) ========= */
[data-testid="stBottomBlockContainer"],
[data-testid="stBottomBlockContainer"] > div,
[data-testid="stBottomBlockContainer"] [data-testid="stVerticalBlock"],
[data-testid="stBottomBlockContainer"] [class*="block-container"],
[data-testid="stBottomBlockContainer"]::before,
[data-testid="stBottomBlockContainer"]::after{
    background:transparent !important;
    box-shadow:none !important;
    border:none !important;
}
[data-testid="stBottomBlockContainer"]{
    padding:0 !important;
    margin:0 !important;
    height:0 !important;
    min-height:0 !important;
}

/* ========= EXTRAS ========= */
/* Remove widgets de status/decoração do Streamlit */
[data-testid="stDecoration"], [data-testid="stStatusWidget"]{ display:none !important }

/* Estilo da Scrollbar */
*::-webkit-scrollbar{ width:10px; height:10px }
*::-webkit-scrollbar-thumb{ background:#2C3340; border-radius:8px }
*::-webkit-scrollbar-track{ background:#0F1115 }

/* Bolinha de 'loading' */
.spinner{
    width:16px; height:16px;
    border:2px solid rgba(37,99,235,.25);
    border-top-color:#2563eb;
    border-radius:50%;
    display:inline-block;
    animation:spin .8s linear infinite;
}
@keyframes spin{ to{ transform:rotate(360deg) } }
</style>
""", unsafe_allow_html=True)

# ====== HEADER HTML (Cabeçalho superior) ======
# Esta é a sua área de "autenticação/usuário"
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
        <a href="#" style="text-decoration:none;color:#2563eb;font-weight:600;border:1px solid rgba(37,99,235,0.12);padding:8px 12px;border-radius:10px;display:inline-block;">⚙ Configurações</a>
        <div style="text-align:right;font-size:0.9rem;color:var(--text);">
            <span style="font-weight:600;">Usuário Demo</span><br>
            <span style="font-weight:400;color:var(--muted);font-size:0.8rem;">usuario@exemplo.com</span>
        </div>
        <div class="user-circle">U</div>
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
        for idx, (pergunta_hist, _resp) in enumerate(st.session_state.historico):
            titulo = pergunta_hist.strip().replace("\n", " ")
            if len(titulo) > 80:
                titulo = titulo[:80] + "…"
            
            # Use um botão ou HTML para recriar o item do histórico
            # Para evitar recarga indesejada em grandes históricos, usaremos apenas a visualização.
            st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

# ====== RENDER MENSAGENS (Chat Principal) ======
msgs_html = []
for pergunta, resposta in st.session_state.historico:
    p_html = linkify(pergunta)
    msgs_html.append(f'<div class="message-row user"><div class="bubble user">{p_html}</div></div>')
    if resposta:
        r_html = linkify(resposta)
        msgs_html.append(f'<div class="message-row assistant"><div class="bubble assistant">{r_html}</div></div>')

# Mostra o spinner de "loading" enquanto a resposta está sendo gerada
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
        // Calcula o espaço do chat para que a entrada de texto não fique por cima
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

    // Monitora a mudança de tamanho do corpo para ajustar o espaçamento
    const ro = new ResizeObserver(()=>{ajustaEspaco();});
    ro.observe(document.body);
    
    // Executa no carregamento e em redimensionamento
    window.addEventListener('load',()=>{ autoGrow(); ajustaEspaco(); scrollToEnd(false); });
    window.addEventListener('resize',()=>{autoGrow();ajustaEspaco();});
    
    // Executa ao digitar (para autoGrow)
    document.addEventListener('input',(e)=>{
        if(e.target&&e.target.matches('[data-testid="stChatInput"] textarea')){
            autoGrow();ajustaEspaco();
        }
    });
    
    // Garante o scroll e ajustes iniciais
    setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
    setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
    
    // Observa o chat card para scrolar sempre que uma nova mensagem for adicionada
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

# ====== FLUXO PRINCIPAL (Gerenciamento de Estado) ======

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
        st.session_state.historico[idx] = (pergunta_fix, resposta) # Atualiza o histórico com a resposta

    # Reseta o estado
    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    
    # Rerun final para atualizar a tela com a resposta
    do_rerun()