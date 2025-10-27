# app.py - Frontend do Chatbot Quadra (Versão FINAL: Card Centralizado e Chat Escuro)

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
    # Fallback caso o arquivo openai_backend.py não exista
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado. Verifique se o arquivo existe e o nome da função está correto."

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
    """Função para forçar um rerun (compatível com versões mais recentes e antigas)."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ====== UTILITÁRIOS ======
def carregar_imagem_base64(path):
    """Carrega uma imagem e retorna sua representação em base64."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

logo_b64 = carregar_imagem_base64(LOGO_PATH)

# Logo para o header do chat (após o login)
if logo_b64:
    logo_img_tag = f'<img class="logo" src="data:image/png;base64,{logo_b64}" />'
    logo_login_tag_card = f'<img class="custom-login-logo" src="data:image/png;base64,{logo_b64}" alt="Logo Quadra Engenharia" />'
else:
    logo_img_tag = '<span style="font-size: 2rem; color: #007bff; font-weight: 900;">Q</span>'
    logo_login_tag_card = '<div class="custom-login-logo" style="background:transparent; border-radius: 8px; margin: auto;"></div>'


def extract_name_from_email(email):
    """Extrai um nome (capitalizado) de um email."""
    if not email or "@" not in email:
        return "Usuário"
    local_part = email.split("@")[0]
    name_parts = re.sub(r'[\._]', ' ', local_part).split()
    return " ".join(p.capitalize() for p in name_parts)

# ====== ESTADO (Início da Sessão) ======
st.session_state.setdefault("historico", [])
st.session_state.setdefault("authenticated", False) 
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)


# ====== AUTENTICAÇÃO (CARD BRANCO CENTRALIZADO) ======

def render_login_screen():
    """Renderiza a tela de login customizada com card branco centralizado e input de e-mail/botão."""
    
    # 1. CSS para o fundo, centralização e o CARD BRANCO
    st.markdown(f"""
    <style>
    /* VARIÁVEIS DE TEMA (Para o layout de login, usa-se a cor escura de fundo) */
    :root {{
        --quadra-blue-dark: #1C3364;
        --quadra-blue-light: #007bff;
    }}
    /* Força o fundo azul/escuro para TODA a tela na fase de login */
    .stApp {{
        background: radial-gradient(circle at center, var(--quadra-blue-dark) 0%, #000000 100%) !important;
        height: 100vh; width: 100vw; overflow: hidden;
    }}
    /* Esconde elementos padrão */
    header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer, section[data-testid="stSidebar"] {{ 
        display: none !important; visibility: hidden !important; height: 0 !important; 
    }}

    /* Centraliza o CONTEÚDO PRINCIPAL (o card) */
    .stApp > div:first-child > div:nth-child(2) > div:first-child {{
        height: 100vh; 
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 0 !important; 
        width: 100%;
        max-width: 100%;
        margin: 0 !important;
    }}
    .block-container {{
        padding: 0 !important;
        max-width: 100% !important;
        min-height: 0 !important;
        display: flex;
        justify-content: center;
        align-items: center;
    }}
    
    /* Container do CARD BRANCO */
    .login-card-wrapper {{
        background: #ffffff; 
        border-radius: 12px; 
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2); 
        padding: 40px; 
        max-width: 400px; 
        width: 100%;
        text-align: center;
        color: #333; 
        box-sizing: border-box;
    }}
    
    /* Estilos dos elementos internos no card */
    .custom-login-logo {{ 
        width: 50px; height: 50px; 
        margin: 0px auto 15px auto; 
        border-radius: 8px;
    }}
    .custom-login-title {{ 
        font-size: 1.5rem; font-weight: 700; margin-bottom: 5px; color: #1f2937; 
    }}
    .custom-login-subtitle {{ 
        font-size: 0.95rem; margin-bottom: 25px; color: #6b7280; line-height: 1.4; 
    }}
    .login-email-prompt {{ 
        font-size: 0.85rem; 
        margin-bottom: 8px; 
        color: #4b5563; 
        text-align: left; 
        width: 100%;
        padding-left: 2px;
    }}
    
    /* Estiliza o st.text_input (E-mail) */
    .login-card-wrapper [data-testid="stTextInput"] {{ 
        margin: 0 0 15px 0 !important; 
    }}
    .login-card-wrapper [data-testid="stTextInput"] > label {{ display: none !important; }}
    .login-card-wrapper [data-testid="stTextInput"] input {{ 
        text-align: left; 
        height: 48px;
        font-size: 1rem;
        border-radius: 6px; 
        border: 1px solid #d1d5db; 
        padding: 0 12px;
        color: #1f2937; 
        background-color: #f9fafb !important; 
        width: 100%;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
    }}
    /* Remove o texto de submissão (Ex: "Press enter...") */
    .login-card-wrapper [data-testid="stFormSubmitButton"] + div {{
        display: none !important;
    }}
    
    /* Botão "Entrar" (Botão principal azul) */
    .login-card-wrapper .stButton > button {{
        width: 100%; 
        height: 45px; 
        font-weight: 600;
        background-color: var(--quadra-blue-light);
        color: white; 
        border: none; 
        border-radius: 6px; 
        font-size: 1rem;
        transition: background-color 0.15s;
    }}
    .login-card-wrapper .stButton > button:hover {{ 
        background-color: #0056b3; 
    }}
    </style>
    """, unsafe_allow_html=True)
    
    # 2. Renderizar o conteúdo centralizado
    
    col1, col2, col3 = st.columns([1, 4, 1]) 

    with col2:
        # Abre o div do CARD BRANCO
        st.markdown('<div class="login-card-wrapper">', unsafe_allow_html=True)
        
        # Conteúdo Estático do Card
        st.markdown(logo_login_tag_card, unsafe_allow_html=True) 
        st.markdown('<div class="custom-login-title">Quadra Engenharia</div>', unsafe_allow_html=True)
        st.markdown('<div class="custom-login-subtitle">Faça login para acessar nosso assistente virtual</div>', unsafe_allow_html=True)
        
        # O formulário Streamlit com o input e o botão
        with st.form("login_form", clear_on_submit=False):
            
            # Texto do prompt do email
            st.markdown('<div class="login-email-prompt">Entre com seu e-mail para começar a conversar com nosso assistente</div>', unsafe_allow_html=True)
            
            # Input de Email
            email = st.text_input(
                "E-mail", 
                placeholder="seu.email@quadra.com.vc", 
                label_visibility="collapsed",
                value=st.session_state.get("last_email_input", "")
            )
            st.session_state["last_email_input"] = email 

            # O botão de submissão do formulário
            submitted = st.form_submit_button("Entrar") 
            
            if submitted:
                email_check = email.strip().lower()
                
                if not email_check or "@" not in email_check:
                    st.error("Por favor, insira um e-mail válido.")
                elif "@quadra.com.vc" not in email_check:
                    st.error("Acesso restrito. Use seu e-mail **@quadra.com.vc**.")
                else:
                    st.session_state.authenticated = True
                    st.session_state.user_email = email_check
                    st.session_state.user_name = extract_name_from_email(email_check)
                    
                    if "last_email_input" in st.session_state:
                        del st.session_state["last_email_input"]
                        
                    do_rerun()
        
        # O DISCALIMER FOI REMOVIDO DA RENDERIZAÇÃO AQUI.
        
        st.markdown('</div>', unsafe_allow_html=True) # Fim do login-card-wrapper
        
    st.stop() # Interrompe a execução do chat até o login


# =================================================================
#                         FLUXO PRINCIPAL
# =================================================================

# 1. VERIFICAÇÃO DE AUTENTICAÇÃO
if not st.session_state.authenticated:
    render_login_screen()

# A partir daqui, o usuário está autenticado. O visual de chat será aplicado.

# ====== MARCAÇÃO (Formatação de Texto) ======
def linkify(text: str) -> str:
    """Formata links, negrito e itálico, substituindo \n por <br>."""
    if not text: return ""
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = text.replace("\n", "<br>")
    return text

# ====== CSS (Chat Customizado - Tema Escuro) ======

st.markdown("""
<style>
/* VARIÁVEIS DE TEMA GERAL */
:root {
    --bg-color: #1a1a1a;
    --card-bg-color: #242424;
    --text-color: #f0f0f0;
    --muted-color: #9ca3af;
    --primary-color: #007bff;
    --secondary-color: #333333;
    --assistant-bubble-bg: #2d2d2d;
    --user-bubble-bg: #1C3364;
    --user-bubble-text: #ffffff;
    --chat-safe-gap: 24px;
}
/* FORÇA O BACKGROUND ESCURO DO CHAT */
.stApp {
    background: var(--bg-color) !important;
}
/* RESET DA CENTRALIZAÇÃO APÓS LOGIN */
.stApp > div:first-child > div:nth-child(2) > div:first-child {
    height: 100% !important; 
    display: block !important; 
    justify-content: initial !important;
    align-items: initial !important;
    padding: 0 !important; 
    max-width: 100% !important;
    margin: 0 !important;
}

/* HEADER (TOPO) */
.header {
    background-color: var(--card-bg-color);
    padding: 10px 20px;
    border-bottom: 1px solid #333333;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 100;
    color: var(--text-color);
    box-shadow: 0 2px 5px rgba(0,0,0,0.2);
}
.header-left {
    display: flex;
    align-items: center;
    font-size: 1.1rem;
    font-weight: 600;
}
.header-left .logo {
    width: 32px;
    height: 32px;
    margin-right: 10px;
    border-radius: 4px;
}
.title-sub {
    font-size: 0.8rem;
    font-weight: 400;
    color: var(--muted-color);
    margin-top: -3px;
}
.header-right {
    display: flex;
    align-items: center;
    gap: 15px;
}
.user-circle {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background-color: var(--primary-color);
    color: white;
    font-size: 1.2rem;
    font-weight: 700;
    display: flex;
    justify-content: center;
    align-items: center;
    margin-left: 10px;
}

/* SIDEBAR (Histórico) */
section[data-testid="stSidebar"] {
    background-color: var(--card-bg-color);
    border-right: 1px solid #333333;
    padding-top: 70px; /* Espaço para o header fixo */
}
.sidebar-header {
    font-size: 1.1rem;
    font-weight: 600;
    padding: 10px 20px 0;
    color: var(--text-color);
}
.sidebar-sub {
    font-size: 0.9rem;
    font-weight: 400;
    color: var(--muted-color);
    padding: 10px 20px;
}
.hist-empty {
    font-size: 0.9rem;
    color: var(--muted-color);
    padding: 10px 20px;
}
.hist-row {
    padding: 8px 20px;
    font-size: 0.9rem;
    cursor: pointer;
    color: var(--text-color);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.hist-row:hover {
    background-color: var(--secondary-color);
}

/* CHAT AREA E CONTAINER PRINCIPAL */
div[data-testid="stVerticalBlock"] > div:first-child {
    padding-top: 70px !important; /* Espaço para o header fixo */
    padding-bottom: 0 !important;
}
.content {
    min-height: calc(100vh - 70px); /* Altura da tela menos o header */
    width: 100%;
    margin: auto;
    padding-left: 20px;
    padding-right: 20px;
    box-sizing: border-box;
}
.chat-card {
    max-width: 900px; /* Largura máxima da área de conversação */
    margin: 0 auto;
    padding-top: 20px;
    box-sizing: border-box;
}
/* Estilo das mensagens */
.message-row {
    display: flex;
    width: 100%;
    margin-bottom: 20px;
}
.message-row.user {
    justify-content: flex-end;
}
.message-row.assistant {
    justify-content: flex-start;
}
.bubble {
    padding: 15px 20px;
    border-radius: 12px;
    max-width: 80%;
    font-size: 0.95rem;
    line-height: 1.6;
    word-wrap: break-word;
    white-space: normal;
}
.bubble.user {
    background-color: var(--user-bubble-bg);
    color: var(--user-bubble-text);
    border-bottom-right-radius: 4px;
}
.bubble.assistant {
    background-color: var(--assistant-bubble-bg);
    color: var(--text-color);
    border-bottom-left-radius: 4px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

/* FORMATOS INTERNOS DO BUBBLE */
.bubble a {
    color: var(--primary-color);
    text-decoration: underline;
}
.bubble b {
    font-weight: 700;
}
.bubble i {
    font-style: italic;
}

/* SPINNER DE RESPOSTA */
.spinner {
    display: inline-block;
    width: 10px;
    height: 10px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-radius: 50%;
    border-top-color: #fff;
    animation: spin 1s ease-in-out infinite;
    -webkit-animation: spin 1s ease-in-out infinite;
    margin: 0 5px;
}
@keyframes spin {
    to { -webkit-transform: rotate(360deg); }
}
@-webkit-keyframes spin {
    to { -webkit-transform: rotate(360deg); }
}

/* INPUT DE CHAT (Para o st.chat_input) */
div[data-testid="stChatInput"] {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100%;
    background: var(--bg-color);
    border-top: 1px solid #333333;
    padding: 10px 0;
    z-index: 90;
    margin-top: 0;
    box-sizing: border-box;
}
div[data-testid="stChatInput"] > div > div {
    max-width: 900px;
    margin: 0 auto;
    padding: 0 20px;
}
div[data-testid="stChatInput"] textarea {
    background-color: var(--card-bg-color);
    color: var(--text-color);
    border: 1px solid #444;
    border-radius: 8px;
    padding: 12px 15px;
}
</style>
""", unsafe_allow_html=True)


# ====== HEADER HTML (Cabeçalho superior) ======
primeira_letra = st.session_state.user_name[0].upper() if st.session_state.user_name else 'U'
if st.session_state.authenticated:
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
            <a href="#" style="text-decoration:none;color:#9ca3af;font-weight:600;border:1px solid rgba(156,163,175,0.2);padding:8px 12px;border-radius:10px;display:inline-block;font-size:0.85rem;">⚙ Configurações</a>
            <div style="text-align:right;font-size:0.9rem;color:var(--text-color);">
                <span style="font-weight:600;">{st.session_state.user_name}</span><br>
                <span style="font-weight:400;color:var(--muted-color);font-size:0.8rem;">{st.session_state.user_email}</span>
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
            # Lista o histórico do chat
            for pergunta_hist, _resp in st.session_state.historico:
                titulo = pergunta_hist.strip().replace("\n", " ")
                if len(titulo) > 80:
                    titulo = titulo[:80] + "…"
                st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

    # ====== RENDER MENSAGENS (Chat Principal) ======
    msgs_html = []
    for pergunta, resposta in st.session_state.historico:
        p_html = linkify(pergunta)
        # Mensagem do Usuário
        msgs_html.append(f'<div class="message-row user"><div class="bubble user">{p_html}</div></div>')
        
        # Mensagem do Assistente
        if resposta:
            r_html = linkify(resposta)
            msgs_html.append(f'<div class="message-row assistant"><div class="bubble assistant">{r_html}</div></div>')

    # Spinner de loading
    if st.session_state.awaiting_answer and st.session_state.answering_started:
        msgs_html.append('<div class="message-row assistant"><div class="bubble assistant"><span class="spinner"></span></div></div>')

    if not msgs_html:
        msgs_html.append('<div style="color:#9ca3af; text-align:center; margin-top:20px;">Comece perguntando algo, o assistente está pronto.</div>')

    # Marcador para o scroll
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
            /* Calcula o espaço que o input ocupa na tela, mais uma margem de segurança */
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
        
        // Timeout para garantir que o layout se ajuste após o render
        setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
        setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
        
        // Observa mutações para rolar a cada nova mensagem
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
            st.session_state.historico[idx] = (pergunta_fix, resposta)

        # Reseta o estado
        st.session_state.awaiting_answer = False
        st.session_state.answering_started = False
        st.session_state.pending_index = None
        st.session_state.pending_question = None
        
        do_rerun()