import streamlit as st
from main import DBManager

st.set_page_config(page_title="SchoolPass", page_icon="🎟️", layout="wide")

@st.cache_resource
def get_db():
    return DBManager()

db = get_db()

if "user" not in st.session_state:
    st.session_state.user = None

# --- ECRÃ DE LOGIN / REGISTO ---
if not st.session_state.user:
    st.title("🎟️ SchoolPass")
    st.subheader("Gestão de Eventos Escolares")

    tab_login, tab_reg = st.tabs(["Entrar", "Criar Conta (Aluno)"])

    with tab_login:
        with st.form("form_login"):
            email = st.text_input("Email", placeholder="ex: prof@escola.pt")
            senha = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                u = db.auth(email, senha)
                if u:
                    st.session_state.user = u
                    st.rerun()
                else:
                    st.error("Email ou senha incorretos.")

    with tab_reg:
        with st.form("form_reg"):
            nome = st.text_input("Nome Completo")
            email_r = st.text_input("Email Escolar")
            senha_r = st.text_input("Senha (mínimo 6 caracteres)", type="password")
            if st.form_submit_button("Registar", use_container_width=True):
                res = db.registar(nome, email_r, senha_r)
                if res == "OK":
                    st.success("Conta criada! Já pode entrar no separador 'Entrar'.")
                else:
                    st.error(res)

# --- APLICAÇÃO PRINCIPAL ---
else:
    user = st.session_state.user
    is_staff = user["papel"] in ("admin", "professor")

    col_tit, col_user = st.columns([4, 1])
    with col_tit:
        st.title("🎟️ SchoolPass")
    with col_user:
        st.write(f"👤 **{user['nome']}** ({user['papel']})")
        if st.button("Sair", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    nomes_tabs = ["Eventos", "Os Meus Bilhetes"]
    if is_staff:
        nomes_tabs.append("Criar Evento")
    tabs = st.tabs(nomes_tabs)

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
