# app.py - Frontend do Chatbot Quadra (Versão FINAL: Card Centralizado com Input de E-mail)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape

# Importa a função de resposta do backend (Mantenha seu arquivo openai_backend.py)
try:
    from openai_backend import responder_pergunta 
except ImportError:
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado. Verifique se o arquivo existe."

warnings.filterwarnings("ignore", message=".*torch.classes.*")

# ====== CONFIG DA PÁGINA ======
# NOTA: Certifique-se de que o arquivo 'data/logo_quadra.png' exista.
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
else:
    logo_img_tag = '<span style="font-size: 2rem; color: #1C3364; font-weight: 900;">Q</span>'

# Logo para uso dentro do card de login
logo_login_tag_card = (
    f'<img class="custom-login-logo" src="data:image/png;base64,{logo_b64}" alt="Logo Quadra Engenharia" />'
    if logo_b64
    else '<div class="custom-login-logo" style="background:#eef2ff; border-radius: 8px; margin: auto;"></div>'
)


def extract_name_from_email(email):
    """Extrai um nome (capitalizado) de um email."""
    if not email or "@" not in email:
        return "Usuário"
    local_part = email.split("@")[0]
    name_parts = re.sub(r'[\._]', ' ', local_part).split()
    return " ".join(p.capitalize() for p in name_parts)

# ====== ESTADO (Início da Sessão) - Mantenha este bloco no topo, antes das funções ======
if "historico" not in st.session_state:
    st.session_state.historico = []

st.session_state.setdefault("authenticated", False) 
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")

st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)


# ====== AUTENTICAÇÃO (Método Streamlit Nativo + CSS para Centralização Exata) ======

def render_login_screen():
    """Renderiza a tela de login customizada com input de email e botão azul, centralizado no fundo escuro."""
    
    # Variável da logo para uso (Recuperada do escopo global/superior)
    try:
        global logo_b64
        logo_login_tag_card = (
            f'<img class="custom-login-logo" src="data:image/png;base64,{logo_b64}" alt="Logo Quadra" />'
            if logo_b64
            else '<div class="custom-login-logo" style="background:#eef2ff; border-radius: 8px; margin: auto;"></div>'
        )
    except NameError:
        logo_login_tag_card = '<img class="custom-login-logo" src="" alt="Logo Quadra" style="width:50px; height:50px; margin:0 auto 10px auto; border-radius:8px; background:#fff;">'
    
    # 1. CSS para o fundo, centralização e os elementos de login
    st.markdown(f"""
    <style>
    /* Força o fundo azul/escuro para TODA a tela na fase de login */
    .stApp {{
        background: radial-gradient(circle at center, #1C3364 0%, #000000 100%) !important;
        height: 100vh; width: 100vw; overflow: hidden;
    }}
    /* Esconde elementos padrão */
    header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer, section[data-testid="stSidebar"] {{ 
        display: none !important; visibility: hidden !important; height: 0 !important; 
    }}

    /* Centraliza o CONTEÚDO PRINCIPAL na vertical e horizontal */
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

    /* Garante que o block-container interno não tenha padding e centralize */
    .block-container {{
        padding: 0 !important;
        max-width: 100% !important;
        min-height: 0 !important;
        display: flex;
        justify-content: center;
        align-items: center;
    }}
    
    /* Container para o conteúdo do login (para limitar a largura e centralizar) */
    .custom-login-container {{
        max-width: 400px; /* Largura do conteúdo principal */
        text-align: center; 
        color: #fff; /* Texto branco no fundo escuro */
        width: 100%; 
        box-sizing: border-box;
        margin: auto; 
    }}
    
    /* Estilos dos elementos internos */
    .custom-login-logo {{ 
        width: 50px; height: 50px; 
        margin: 0px auto 10px auto; 
        border-radius: 8px;
    }}
    .custom-login-title {{ 
        font-size: 1.5rem; font-weight: 700; margin-bottom: 5px; color: #fff; 
    }}
    .custom-login-subtitle {{ 
        font-size: 0.95rem; margin-bottom: 30px; color: #a0a0a0; line-height: 1.4; 
    }}
    .login-email-prompt {{ 
        font-size: 0.85rem; 
        margin-bottom: 10px; 
        color: #a0a0a0; 
        text-align: left; /* Alinha o texto do prompt à esquerda */
        width: 100%;
        padding-left: 2px; /* Pequeno ajuste */
    }}
    .custom-login-disclaimer {{ 
        font-size: 0.75rem; margin-top: 25px; color: #666; line-height: 1.4; 
    }}
    
    /* Estiliza o st.form nativo para ser discreto */
    .stForm {{ 
        padding: 0 !important; 
        margin: 0 !important; 
    }}
    
    /* Estiliza o st.text_input (E-mail) */
    .custom-login-container [data-testid="stTextInput"] {{ 
        margin: 0 0 10px 0 !important; 
    }}
    .custom-login-container [data-testid="stTextInput"] > label {{ display: none !important; }}
    .custom-login-container [data-testid="stTextInput"] input {{ 
        /* Para replicar o visual de campo de texto das imagens (fundo branco, largura total) */
        text-align: left; /* Alinha o texto do input à esquerda */
        height: 48px;
        font-size: 1rem;
        border-radius: 4px;
        border: 1px solid #ddd;
        padding: 0 10px;
        color: #333; /* Texto escuro no input */
        background-color: white !important;
        width: 100%;
        max-width: 400px;
        margin: 0 auto;
    }}
    
    /* Botão "Entrar no Chatbot" (Botão principal azul) */
    .custom-login-container .stButton > button {{
        width: 100%; /* Largura total do container */
        height: 40px; /* Altura um pouco menor */
        font-weight: 600;
        background-color: #007bff; /* Azul primário (ou mude para #1C3364 se preferir o azul escuro da Quadra) */
        color: white; 
        border: none; 
        border-radius: 4px; 
        margin-top: 5px; 
        font-size: 0.95rem;
        transition: background-color 0.15s;
    }}
    .custom-login-container .stButton > button:hover {{ 
        background-color: #0056b3; 
    }}
    
    /* Garante que o input e o botão fiquem alinhados */
    .stForm > div:last-child {{
        display: flex;
        flex-direction: column;
        align-items: center;
    }}

    </style>
    """, unsafe_allow_html=True)
    
    # 2. Renderizar o conteúdo centralizado
    
    # Usamos colunas para ajudar a centralizar, mas o CSS é o que faz o trabalho pesado
    col1, col2, col3 = st.columns([1, 4, 1]) 

    with col2:
        # Injeta o div do container de login
        st.markdown('<div class="custom-login-container">', unsafe_allow_html=True)
        
        # Conteúdo Estático do Card
        # Logo (no topo)
        st.markdown(logo_login_tag_card, unsafe_allow_html=True) 
        # Título
        st.markdown('<div class="custom-login-title">Quadra Engenharia</div>', unsafe_allow_html=True)
        # Subtítulo
        st.markdown('<div class="custom-login-subtitle">Faça login para acessar nosso assistente virtual</div>', unsafe_allow_html=True)
        
        # O formulário Streamlit com o input e o botão
        with st.form("login_form", clear_on_submit=False):
            
            # Texto do prompt do email (Alinhado à esquerda dentro do container)
            st.markdown('<div class="login-email-prompt">Entre com seu e-mail para começar a conversar com nosso assistente</div>', unsafe_allow_html=True)
            
            # Input de Email
            email = st.text_input(
                "E-mail", 
                placeholder="seu.nome@quadra.com.vc", 
                label_visibility="collapsed",
                value=st.session_state.get("last_email_input", "")
            )
            st.session_state["last_email_input"] = email # Salva o último input

            # O botão de submissão do formulário
            submitted = st.form_submit_button("Entrar no Chatbot") 
            
            if submitted:
                email_check = email.strip().lower()
                
                if not email_check or "@" not in email_check:
                    st.error("Por favor, insira um e-mail válido.")
                elif "@quadra.com.vc" not in email_check:
                    st.error("Acesso restrito. Use seu e-mail **@quadra.com.vc**.")
                else:
                    # Login bem-sucedido
                    st.session_state.authenticated = True
                    st.session_state.user_email = email_check
                    
                    # Certifique-se de que a função extract_name_from_email está definida
                    # no seu código
                    st.session_state.user_name = extract_name_from_email(email_check)
                    
                    if "last_email_input" in st.session_state:
                        del st.session_state["last_email_input"]
                        
                    do_rerun()
        
        # Disclaimer
        st.markdown('<div class="custom-login-disclaimer">Ao fazer login, você concorda com nossos Termos de Serviço e Política de Privacidade.</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True) # Fim do custom-login-container
        
    st.stop() # Interrompe a execução do chat até o login


# =================================================================
#                         FLUXO PRINCIPAL
# =================================================================

# 1. VERIFICAÇÃO DE AUTENTICAÇÃO
if not st.session_state.authenticated:
    render_login_screen()

# ... (MANTENHA O RESTANTE DO SEU CÓDIGO DO CHAT INALTERADO) ...

# A partir daqui, o usuário está autenticado. O visual de chat será aplicado.

# ====== MARCAÇÃO (Formatação de Texto) ======
def formatar_markdown_basico(text: str) -> str:
    if not text: return ""
    # Esta função é mantida para formatar as mensagens de chat
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = text.replace("\n", "<br>")
    return text

def linkify(text: str) -> str:
    return formatar_markdown_basico(text or "")

# ====== CSS (Chat Customizado - Tema Escuro) ======
# NOTA: O CSS do CHAT foi removido para brevidade, mas deve ser mantido no arquivo.
# O bloco de CSS do CHAT no seu código anterior está correto.

st.markdown("""
<style>
/* ... (Seu CSS completo para o CHAT deve vir aqui - o do seu código anterior) ... */

/* FORÇANDO O RESET PÓS-LOGIN (para que o Streamlit volte ao layout normal de chat) */
.stApp > div:first-child > div:nth-child(2) > div:first-child {
    height: 100% !important; /* Volta para a altura normal */
    display: block !important; /* Desabilita o Flexbox de centralização */
    justify-content: initial !important;
    align-items: initial !important;
    padding: 0 !important; 
    max-width: 100% !important;
    margin: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# ====== O restante do código de HEADER, SIDEBAR, CHAT, INPUT e FLUXO PRINCIPAL é mantido inalterado ======

# ... [O restante do código do HEADER (st.markdown com logo_img_tag), SIDEBAR (with st.sidebar), 
# RENDER MENSAGENS, JS e FLUXO PRINCIPAL deve continuar aqui, como no seu código anterior.] ...

# Apenas para o código ser executável:

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
            <a href="#" style="text-decoration:none;color:#2563eb;font-weight:600;border:1px solid rgba(37,99,235,0.12);padding:8px 12px;border-radius:10px;display:inline-block;">⚙ Configurações</a>
            <div style="text-align:right;font-size:0.9rem;color:var(--text);">
                <span style="font-weight:600;">{st.session_state.user_name}</span><br>
                <span style="font-weight:400;color:var(--muted);font-size:0.8rem;">{st.session_state.user_email}</span>
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
            for pergunta_hist, _resp in st.session_state.historico:
                titulo = pergunta_hist.strip().replace("\n", " ")
                if len(titulo) > 80:
                    titulo = titulo[:80] + "…"
                st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

    # ====== RENDER MENSAGENS (Chat Principal) ======
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
        
        setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
        setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
        
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