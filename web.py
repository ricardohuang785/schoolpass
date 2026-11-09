import streamlit as st
from main import DBManager

# Inicializa a tua classe do main.py
db = DBManager()

st.title("SchoolPass")
st.write("Bem-vindo ao portal do SchoolPass!")

# Exemplo: listar eventos
st.header("Eventos")
eventos = db.obter_eventos() 

for ev in eventos:
    st.write(f"### {ev['titulo']}")
    st.write(f"Local: {ev['local']}")
