import streamlit as st
import main as db

st.set_page_config(page_title="SchoolPass", layout="wide")
st.title("SchoolPass")

user = {"id": 1}
is_staff = True

tabs = st.tabs(["Eventos", "Os Meus Bilhetes", "Criar Evento"])
    
# --- ABA 1: EVENTOS ---
with tabs[0]:
        filtro = st.text_input("🔍 Pesquisar por título ou categoria", placeholder="Ex: Futsal, palestra...")
        eventos = db.obter_eventos(filtro)

        if not eventos:
            st.info("Nenhum evento encontrado.")
        else:
            for ev in eventos:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.subheader(f"{ev['titulo']}")
                        st.write(f"📍 **Local:** {ev['local']} | 🏷️ **Categoria:** {ev['cat']} | 👥 **Lotação:** {ev['cap']} | 👤 **Org:** {ev['organizador']}")
                    with col2:
                        st.write("")
                        if st.button("Inscrever", key=f"insc_{ev['id']}", use_container_width=True):
                            msg = db.inscrever(user["id"], ev["id"])
                            if "✅" in msg or "⏳" in msg:
                                st.success(msg)
                            else:
                                st.warning(msg)

    
# --- ABA 2: OS MEUS BILHETES ---
with tabs[1]:
        st.header("Os Meus Bilhetes")
        bilhetes = db.obter_bilhetes(user["id"])

        if not bilhetes:
            st.info("Ainda não tem inscrições ativas.")
        else:
            for b in bilhetes:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        estado = "⏳ Lista de Espera" if b["espera"] else "✅ Confirmado"
                        st.subheader(b["titulo"])
                        st.write(f"**Código:** `{b['cod']}` | **Estado:** {estado}")
                    with c2:
                        if st.button("Cancelar", key=f"canc_{b['id']}", use_container_width=True):
                            res = db.cancelar_inscricao(b["id"], user["id"])
                            st.info(res)
                            st.rerun()

    # --- ABA 3: GERIR EVENTOS (PROFESSOR / ADMIN) ---
if is_staff:
        with tabs[2]:
            st.header("Criar Novo Evento")
            with st.form("novo_evento"):
                titulo = st.text_input("Título do Evento")
                local = st.text_input("Local")
                cap = st.number_input("Capacidade Máxima", min_value=1, value=20)
                cat = st.selectbox("Categoria", ["desporto", "palestra", "competicao", "cultura", "outro"])
                if st.form_submit_button("Criar Evento"):
                    res = db.criar_evento(titulo, local, cap, cat, user["id"])
                    if res == "OK":
                        st.success("Evento criado com sucesso!")
                        st.rerun()
                    else:
                        st.error(res)
