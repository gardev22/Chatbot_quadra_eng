# app.py - Frontend do Chatbot Quadra (Versão FINAL Corrigida)

import streamlit as st
import base64
import os
import re
import warnings
from html import escape

try:
    from openai_backend import responder_pergunta
except ImportError:
    def responder_pergunta(pergunta):
        return "Erro: O módulo 'openai_backend' ou a função 'responder_pergunta' não foi encontrado."

warnings.filterwarnings("ignore", message=".*torch.classes.*")

LOGO_PATH = "data/logo_quadra.png"
st.set_page_config(page_title="Chatbot Quadra", page_icon=LOGO_PATH, layout="wide", initial_sidebar_state="expanded")

def do_rerun():
    if hasattr(st, "rerun"): st.rerun()
    else: st.experimental_rerun()

def _clear_query_params():
    try: st.query_params.clear()
    except Exception: st.experimental_set_query_params()

def _get_query_params():
    try: return dict(st.query_params)
    except Exception: return dict(st.experimental_get_query_params())

qp = _get_query_params()
if "logout" in qp:
    st.session_state.update({
        "authenticated": False, "user_name": "Usuário", "user_email": "nao_autenticado@quadra.com.vc",
        "awaiting_answer": False, "answering_started": False, "pending_index": None,
        "pending_question": None, "historico": []
    })
    _clear_query_params(); do_rerun()

def carregar_imagem_base64(path):
    if not os.path.exists(path): return None
    try:
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    except Exception: return None

logo_b64 = carregar_imagem_base64(LOGO_PATH)
logo_img_tag = f'<img class="logo" src="data:image/png;base64,{logo_b64}" />' if logo_b64 else '<span style="font-size: 2rem; color: #1C3364; font-weight: 900;">Q</span>'

def extract_name_from_email(email):
    if not email or "@" not in email: return "Usuário"
    local = email.split("@")[0]
    parts = re.sub(r'[\._]', ' ', local).split()
    return " ".join(p.capitalize() for p in parts)

if "historico" not in st.session_state: st.session_state.historico = []
st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("user_name", "Usuário")
st.session_state.setdefault("user_email", "nao_autenticado@quadra.com.vc")
st.session_state.setdefault("awaiting_answer", False)
st.session_state.setdefault("answering_started", False)
st.session_state.setdefault("pending_index", None)
st.session_state.setdefault("pending_question", None)

def render_login_screen():
    st.markdown("""
    <style>
    :root{ --login-max:520px; --lift:90px; }
    .stApp{
      background: radial-gradient(1100px 620px at 50% 35%, #264E9A 0%, #16356B 50%, #0B1730 100%)!important;
      min-height:100vh!important; overflow:hidden!important;
    }
    header[data-testid="stHeader"], div[data-testid="stToolbar"], #MainMenu, footer{ display:none!important; }
    [data-testid="stAppViewContainer"]>.main{ height:100vh!important; }
    .block-container{ height:100%; display:flex; align-items:center; justify-content:center; padding:0!important; margin:0!important; }
    div[data-testid="column"]:has(#login_card_anchor)>div{ background:transparent!important; box-shadow:none!important; border-radius:0; padding:0; text-align:center; }
    .login-stack{ width:min(92vw, var(--login-max)); margin:0 auto; text-align:center; transform:translateY(calc(var(--lift) * -1)); }
    .login-logo{ width:88px; height:88px; object-fit:contain; display:block; margin:0 auto 14px; filter:drop-shadow(0 6px 16px rgba(0,0,0,.35)); }
    .login-title{ display:block; text-align:center; font-size:1.5rem; font-weight:800; color:#F5F7FF; margin:6px 0 6px; text-shadow:0 1px 2px rgba(0,0,0,.35); }
    .login-sub{ text-align:center; font-size:1rem; color:#C9D7FF; margin:0 0 16px; }

    .login-stack [data-testid="stTextInput"]{ width:100%; margin:0 auto; }
    .login-stack [data-testid="stTextInput"]>label{ display:none!important; }
    .login-stack [data-testid="stTextInput"] input{
      width:100%; height:48px; font-size:1rem; border-radius:10px;
      border:1px solid rgba(255,255,255,.2)!important; background:#fff!important; color:#111827!important;
      box-shadow:0 6px 20px rgba(6,16,35,.30);
    }

    /* ===== PILHA DOS CONTROLES ===== */
    .login-actions-stack{
      width:100%; display:flex; flex-direction:column; align-items:center; justify-content:center;
      gap:12px; margin-top:22px;   /* empurra pra posição do X */
    }
    /* centraliza REAL o st.button (o wrapper do Streamlit ocupa 100% de largura) */
    .login-actions-stack .stButton{ width:100%; display:flex; justify-content:center; }
    .login-actions-stack .stButton>button{
      padding:0 18px; height:48px; border:none; border-radius:10px; font-weight:700; font-size:1rem;
      background:#2E5CB5!important; color:#fff!important; box-shadow:0 8px 22px rgba(11,45,110,.45);
    }
    .login-actions-stack .stButton>button:hover{ filter:brightness(1.06); }

    /* link de cadastro centralizado e mais abaixo */
    .cadastro-link-wrap{ width:100%; display:flex; justify-content:center; margin-top:28px; }
    .cadastro-link{ color:rgba(255,255,255,.72)!important; font-weight:600; font-size:.96rem; text-decoration:none; }
    .cadastro-link:hover{ color:#fff!important; text-decoration:underline; }

    @media (max-width:480px){
      :root{ --lift:28px; }
      .login-logo{ width:76px; height:76px; }
      .login-title{ font-size:1.4rem; }
    }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        st.markdown('<div id="login_card_anchor"></div>', unsafe_allow_html=True)
        st.markdown('<div class="login-stack">', unsafe_allow_html=True)

        if logo_b64:
            st.markdown(f'<img class="login-logo" alt="Logo Quadra" src="data:image/png;base64,{logo_b64}"/>', unsafe_allow_html=True)
        st.markdown('<span class="login-title">Quadra Engenharia</span>', unsafe_allow_html=True)
        st.markdown('<div class="login-sub">Entre com seu e-mail para começar a conversar com nosso assistente</div>', unsafe_allow_html=True)

        email = st.text_input("E-mail", placeholder="seu.nome@quadra.com.vc", label_visibility="collapsed")

        # Botão ENTRAR exatamente debaixo do input (centralizado)
        st.markdown('<div class="login-actions-stack">', unsafe_allow_html=True)
        clicou = st.button("Entrar", type="primary")
        st.markdown('</div>', unsafe_allow_html=True)

        # Link "Cadastrar usuário" (centralizado e mais abaixo)
        st.markdown('<div class="cadastro-link-wrap"><span class="cadastro-link">Cadastrar usuário</span></div>', unsafe_allow_html=True)

        if clicou:
            email_norm = (email or "").strip().lower()
            if "@" not in email_norm:
                st.error("Por favor, insira um e-mail válido.")
            elif not email_norm.endswith("@quadra.com.vc"):
                st.error("Acesso restrito. Use seu e-mail **@quadra.com.vc**.")
            else:
                st.session_state.authenticated = True
                st.session_state.user_email = email_norm
                st.session_state.user_name = extract_name_from_email(email_norm)
                do_rerun()

        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

if not st.session_state.authenticated:
    render_login_screen()

def formatar_markdown_basico(text: str) -> str:
    if not text: return ""
    text = re.sub(r'(https?://[^\s<>"\]]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>")
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>")
    return text.replace("\n", "<br>")

def linkify(text: str) -> str: return formatar_markdown_basico(text or "")

# ===== CSS/HEADER/SIDEBAR/CHAT iguais ao anterior =====
st.markdown(f"""
<style>
/* (trecho do chat mantido sem alterações) */
</style>
""", unsafe_allow_html=True)

primeira_letra = st.session_state.user_name[0].upper() if st.session_state.user_name else 'U'
st.markdown(f"""
<div class="header">
    <div class="header-left">
        {logo_img_tag}
        <div>Chatbot Quadra<div class="title-sub">Assistente Inteligente</div></div>
    </div>
    <div class="header-right">
        <a href="?logout=1" target="_self"
          style="text-decoration:none;background:transparent;border:1px solid rgba(255,255,255,0.14);
          color:#e5e7eb;font-weight:600;padding:8px 12px;border-radius:10px;display:inline-block;cursor:pointer;">
   Sair
        </a>
        <div style="text-align:right;font-size:0.9rem;color:#E5E7EB;">
            <span style="font-weight:600;">{st.session_state.user_name}</span><br>
            <span style="font-weight:400;color:#9AA4B2;font-size:0.8rem;">{st.session_state.user_email}</span>
        </div>
        <div style="width:32px;height:32px;border-radius:50%;background:#007bff;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:1rem;">{primeira_letra}</div>
    </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="sidebar-header">Histórico</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-bar"><div class="sidebar-sub">Perguntas desta sessão</div></div>', unsafe_allow_html=True)
    if not st.session_state.historico:
        st.markdown('<div class="hist-empty">Sem perguntas ainda.</div>', unsafe_allow_html=True)
    else:
        for pergunta_hist, _ in st.session_state.historico:
            titulo = (pergunta_hist.strip().replace("\n"," "))
            if len(titulo)>80: titulo = titulo[:80] + "…"
            st.markdown(f'<div class="hist-row">{escape(titulo)}</div>', unsafe_allow_html=True)

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
st.markdown(f'<div class="content"><div id="chatCard" class="chat-card">{"".join(msgs_html)}</div></div>', unsafe_allow_html=True)

st.markdown("""
<script>
(function(){
  function ajustaEspaco(){
    const input=document.querySelector('[data-testid="stChatInput"]');
    const card=document.getElementById('chatCard');
    if(!input||!card) return;
    const gap=parseInt(getComputedStyle(document.documentElement).getPropertyValue('--chat-safe-gap').trim()||'24',10);
    const rect=input.getBoundingClientRect();
    const altura=(window.innerHeight-rect.top)+gap;
    card.style.paddingBottom=altura+'px';
    card.style.scrollPaddingBottom=altura+'px';
  }
  function autoGrow(){
    const ta=document.querySelector('[data-testid="stChatInput"] textarea');
    if(!ta) return;
    const MAX=220;
    ta.style.height='auto';
    const desired=Math.min(ta.scrollHeight,MAX);
    ta.style.height=desired+'px';
    ta.style.overflowY=(ta.scrollHeight>MAX)?'auto':'hidden';
  }
  function scrollToEnd(smooth=true){
    const end=document.getElementById('chatEnd'); if(!end) return;
    end.scrollIntoView({behavior:smooth?'smooth':'auto',block:'end'});
  }
  const ro=new ResizeObserver(()=>{ajustaEspaco();}); ro.observe(document.body);
  window.addEventListener('load',()=>{autoGrow();ajustaEspaco();scrollToEnd(false);});
  window.addEventListener('resize',()=>{autoGrow();ajustaEspaco();});
  document.addEventListener('input',(e)=>{ if(e.target&&e.target.matches('[data-testid="stChatInput"] textarea')){autoGrow();ajustaEspaco();}});
  setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(false);},0);
  setTimeout(()=>{autoGrow();ajustaEspaco();scrollToEnd(true);},150);
  const card=document.getElementById('chatCard');
  if(card){ const mo=new MutationObserver(()=>{ajustaEspaco();scrollToEnd(true);}); mo.observe(card,{childList:true,subtree:false});}
})();
</script>
""", unsafe_allow_html=True)

pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")
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
    resposta = responder_pergunta(st.session_state.pending_question)
    idx = st.session_state.pending_index
    if idx is not None and 0 <= idx < len(st.session_state.historico):
        pergunta_fix = st.session_state.historico[idx][0]
        st.session_state.historico[idx] = (pergunta_fix, resposta)
    st.session_state.awaiting_answer = False
    st.session_state.answering_started = False
    st.session_state.pending_index = None
    st.session_state.pending_question = None
    do_rerun()
