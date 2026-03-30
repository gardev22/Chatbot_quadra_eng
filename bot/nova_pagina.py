import streamlit as st
from openai_backend import auditar_base_conhecimento

st.set_page_config(page_title="Auditoria da Base", layout="wide")

st.title("Auditoria da Base de Conhecimento")

if "audit_result" not in st.session_state:
    st.session_state.audit_result = ""

col1, col2 = st.columns(2)

with col1:
    if st.button("Atualizar auditoria"):
        st.session_state.audit_result = auditar_base_conhecimento()

with col2:
    if st.button("Limpar"):
        st.session_state.audit_result = ""

st.text_area(
    "Resultado",
    value=st.session_state.audit_result,
    height=600
)