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

# ====== MARCAÇÃO ======
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

# ====== CSS ESTRUTURAL ======
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

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

# ====== INPUT ======
pergunta = st.chat_input("Comece perguntando algo, o assistente está pronto.")

# ====== FLUXO AJUSTADO ======

# Fase 1: usuário enviou pergunta → adiciona e reroda (mostra instantâneo)
if pergunta and pergunta.strip():
    q = pergunta.strip()

    # Debounce: evita repetição
    if st.session_state._last_input != q:
        st.session_state._last_input = q
        st.session_state.historico.append((q, ""))  # mostra a mensagem
        st.session_state.pending_index = len(st.session_state.historico) - 1
        st.session_state.pending_question = q
        st.session_state.awaiting_answer = True
        st.session_state.answering_started = False

        st.stop()  # mostra a mensagem primeiro (sem rerun ainda)

# Fase 2: se há pergunta pendente e ainda não começou a responder
if st.session_state.awaiting_answer and not st.session_state.answering_started:
    st.session_state.answering_started = True
    q = st.session_state.pending_question

    with st.spinner("O assistente está pensando..."):
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
