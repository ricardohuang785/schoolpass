import sqlite3, hashlib, secrets, os, hmac, getpass, csv, datetime, re

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

ITERACOES = 600000
FORMATO_EMAIL = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

class DBManager:
    def __init__(self, db_path="schoolpass.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._criar_tabelas()
        self._seed()

    def _criar_tabelas(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS utilizadores (id INTEGER PRIMARY KEY, nome TEXT, email TEXT UNIQUE, senha TEXT, salt TEXT, iteracoes INTEGER DEFAULT 600000, papel TEXT, precisa_mudar_senha INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, local TEXT, cap INTEGER CHECK(cap > 0), cat TEXT, org_id INTEGER REFERENCES utilizadores(id), aval REAL DEFAULT 0, cancelado INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS inscricoes (id INTEGER PRIMARY KEY, u_id INTEGER REFERENCES utilizadores(id), e_id INTEGER REFERENCES eventos(id), cod TEXT UNIQUE, espera INTEGER DEFAULT 0, checkin INTEGER DEFAULT 0, data_checkin TEXT, cancelada INTEGER DEFAULT 0, UNIQUE(u_id, e_id));
        CREATE TABLE IF NOT EXISTS clubes (id INTEGER PRIMARY KEY, nome TEXT);
        CREATE TABLE IF NOT EXISTS membros (u_id INTEGER REFERENCES utilizadores(id), c_id INTEGER REFERENCES clubes(id), UNIQUE(u_id, c_id));
        CREATE TABLE IF NOT EXISTS avaliacoes (id INTEGER PRIMARY KEY, e_id INTEGER REFERENCES eventos(id), u_id INTEGER REFERENCES utilizadores(id), estrelas INTEGER CHECK(estrelas BETWEEN 1 AND 5), UNIQUE(e_id, u_id));
        CREATE TABLE IF NOT EXISTS notificacoes (id INTEGER PRIMARY KEY, u_id INTEGER REFERENCES utilizadores(id), txt TEXT, lida INTEGER DEFAULT 0);
        """)
        try: self.conn.execute("ALTER TABLE utilizadores ADD COLUMN precisa_mudar_senha INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        self.conn.commit()

    def _criar_hash(self, senha, salt, it=ITERACOES):
        return hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), it).hex()

    def _seed(self):
        if not self.conn.execute("SELECT * FROM utilizadores").fetchone():
            for n, e, s, p in [('Admin', 'admin@escola.pt', 'Admin123!', 'admin'), ('Prof', 'prof@escola.pt', 'Prof123!', 'professor')]:
                salt = secrets.token_hex(16); h = self._criar_hash(s, salt)
                self.conn.execute("INSERT INTO utilizadores (nome,email,senha,salt,iteracoes,papel,precisa_mudar_senha) VALUES (?,?,?,?,?,?,1)", (n, e, h, salt, ITERACOES, p))
            for c_n in ["Programação", "Gaming", "Música", "Desporto", "Arte", "Leitura"]:
                self.conn.execute("INSERT INTO clubes (nome) VALUES (?)", (c_n,))
            prof_id = self.conn.execute("SELECT id FROM utilizadores WHERE email='prof@escola.pt'").fetchone()[0]
            evs = [("Futsal", "Pav", 10, "desporto", prof_id), ("Palestra", "Aud", 100, "palestra", prof_id), ("Robótica", "Pav", 2, "competicao", prof_id)]
            self.conn.executemany("INSERT INTO eventos (titulo,local,cap,cat,org_id) VALUES (?,?,?,?,?)", evs)
            self.conn.commit()

    def registar(self, nome, email, senha):
        nome = nome.strip(); email = email.strip().lower()
        if not nome or not FORMATO_EMAIL.match(email): return "Dados inválidos."
        if len(senha) < 6: return "Senha curta (min 6)."
        salt = secrets.token_hex(16); h = self._criar_hash(senha, salt)
        try:
            self.conn.execute("INSERT INTO utilizadores (nome,email,senha,salt,iteracoes,papel) VALUES (?,?,?,?,?,'aluno')", (nome, email, h, salt, ITERACOES))
            self.conn.commit()
            return "OK"
        except sqlite3.IntegrityError: return "Email já existe."

    def auth(self, email, senha):
        r = self.conn.execute("SELECT * FROM utilizadores WHERE email=?", (email.strip().lower(),)).fetchone()
        if r:
            if hmac.compare_digest(self._criar_hash(senha, r['salt'], r['iteracoes']), r['senha']): return r
        else: self._criar_hash(senha, secrets.token_hex(16))
        return None

    def alterar_senha(self, uid, antiga, nova):
        u = self.conn.execute("SELECT * FROM utilizadores WHERE id=?", (uid,)).fetchone()
        if not self.auth(u['email'], antiga): return "Senha atual errada."
        if len(nova) < 6: return "Senha curta."
        salt = secrets.token_hex(16); h = self._criar_hash(nova, salt)
        self.conn.execute("UPDATE utilizadores SET senha=?, salt=?, iteracoes=?, precisa_mudar_senha=0 WHERE id=?", (h, salt, ITERACOES, uid))
        self.conn.commit(); return "OK"

    def obter_eventos(self, filtro=""):
        q = "SELECT e.*, u.nome AS organizador FROM eventos e JOIN utilizadores u ON e.org_id=u.id WHERE e.cancelado=0"
        if filtro: q += " AND (e.titulo LIKE ? OR e.cat LIKE ?)"
        return self.conn.execute(q, (f"%{filtro}%", f"%{filtro}%") if filtro else ()).fetchall()

    def criar_evento(self, titulo, local, cap, cat, org_id):
        if not titulo.strip() or not local.strip() or cap < 1: return "Dados inválidos."
        self.conn.execute("INSERT INTO eventos (titulo,local,cap,cat,org_id) VALUES (?,?,?,?,?)", (titulo.strip(), local.strip(), cap, cat, org_id))
        self.conn.commit(); return "OK"

    def editar_evento(self, eid, org_id, adm, novo_titulo, novo_local, nova_cap):
        ev = self.conn.execute("SELECT * FROM eventos WHERE id=?", (eid,)).fetchone()
        if not ev or (ev['org_id'] != org_id and not adm): return "Sem permissão."
        if nova_cap < 1: return "Capacidade inválida."
        self.conn.execute("UPDATE eventos SET titulo=?, local=?, cap=? WHERE id=?", (novo_titulo.strip(), novo_local.strip(), nova_cap, eid))
        self.conn.commit(); return "OK"

    def cancelar_evento(self, eid, org_id, adm):
        ev = self.conn.execute("SELECT * FROM eventos WHERE id=? AND cancelado=0", (eid,)).fetchone()
        if not ev or (ev['org_id'] != org_id and not adm): return "Sem permissão."
        if self.conn.execute("SELECT 1 FROM inscricoes WHERE e_id=? AND checkin=1", (eid,)).fetchone(): return "Já tem check-ins."
        with self.conn:
            self.conn.execute("UPDATE eventos SET cancelado=1 WHERE id=?", (eid,))
            for i in self.conn.execute("SELECT u_id FROM inscricoes WHERE e_id=? AND cancelada=0", (eid,)).fetchall():
                self.notificar(i['u_id'], f"⚠ O evento {ev['titulo']} foi cancelado.")
        return "OK"

    def autorizado(self, eid, oid, adm):
        ev = self.conn.execute("SELECT org_id FROM eventos WHERE id=?", (eid,)).fetchone()
        return ev and (adm or ev['org_id'] == oid)

    def obter_bilhetes(self, uid):
        return self.conn.execute("SELECT i.*, e.titulo FROM inscricoes i JOIN eventos e ON i.e_id=e.id WHERE i.u_id=? AND i.cancelada=0 AND e.cancelado=0", (uid,)).fetchall()

    def inscrever(self, uid, eid):
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            ev = self.conn.execute("SELECT * FROM eventos WHERE id=? AND cancelado=0", (eid,)).fetchone()
            if not ev: return "Evento fechado."
            if self.conn.execute("SELECT * FROM inscricoes WHERE u_id=? AND e_id=? AND cancelada=0", (uid, eid)).fetchone(): return "Já inscrito."
            ocup = self.conn.execute("SELECT COUNT(*) FROM inscricoes WHERE e_id=? AND espera=0 AND cancelada=0", (eid,)).fetchone()[0]
            esp = 1 if ocup >= ev['cap'] else 0
            cod = "SP-" + secrets.token_hex(3).upper()
            self.conn.execute("DELETE FROM inscricoes WHERE u_id=? AND e_id=? AND cancelada=1", (uid, eid))
            self.conn.execute("INSERT INTO inscricoes (u_id,e_id,cod,espera) VALUES (?,?,?,?)", (uid, eid, cod, esp))
            self.notificar(uid, f"Inscrição em {ev['titulo']}")
            self.notificar(ev['org_id'], f"Novo aluno: {ev['titulo']}")
            return f"✅ Inscrito! Código: {cod}" if not esp else "⏳ Lista de espera."

    def cancelar_inscricao(self, iid, uid):
        with self.conn:
            i = self.conn.execute("SELECT * FROM inscricoes WHERE id=? AND u_id=? AND cancelada=0", (iid, uid)).fetchone()
            if not i: return "Não encontrado."
            if i['checkin']: return "Já usado."
            self.conn.execute("UPDATE inscricoes SET cancelada=1 WHERE id=?", (iid,))
            if not i['espera']:
                prox = self.conn.execute("SELECT * FROM inscricoes WHERE e_id=? AND espera=1 AND cancelada=0 ORDER BY id LIMIT 1", (i['e_id'],)).fetchone()
                if prox:
                    self.conn.execute("UPDATE inscricoes SET espera=0 WHERE id=?", (prox['id'],))
                    self.notificar(prox['u_id'], "🎉 Vaga libertada! Já tens bilhete válido.")
            ev = self.conn.execute("SELECT titulo, org_id FROM eventos WHERE id=?", (i['e_id'],)).fetchone()
            self.notificar(ev['org_id'], f"Cancelamento em: {ev['titulo']}")
            return "✅ Cancelada."

    def checkin(self, cod, oid, adm=False):
        ins = self.conn.execute("SELECT i.*, u.nome, e.titulo, e.org_id, e.cancelado FROM inscricoes i JOIN utilizadores u ON i.u_id=u.id JOIN eventos e ON i.e_id=e.id WHERE i.cod=? AND i.cancelada=0", (cod,)).fetchone()
        if not ins or ins['cancelado']: return "❌ Inválido ou cancelado."
        if ins['espera'] or ins['checkin']: return "⚠️ Já usado ou em espera."
        if ins['org_id'] != oid and not adm: return "❌ Não é teu."
        agora = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
        self.conn.execute("UPDATE inscricoes SET checkin=1, data_checkin=? WHERE id=?", (agora, ins['id']))
        self.conn.commit()
        return f"✅ Autorizado!\nAluno: {ins['nome']}\nHora: {agora}"

    def obter_clubes(self, uid):
        return self.conn.execute("SELECT c.*, (SELECT 1 FROM membros m WHERE m.c_id=c.id AND m.u_id=?) as inscrito FROM clubes c", (uid,)).fetchall()

    def toggle_clube(self, uid, cid):
        try:
            if self.conn.execute("SELECT 1 FROM membros WHERE u_id=? AND c_id=?", (uid, cid)).fetchone():
                self.conn.execute("DELETE FROM membros WHERE u_id=? AND c_id=?", (uid, cid))
                self.conn.commit(); return "✅ Saíste do clube."
            self.conn.execute("INSERT INTO membros VALUES (?,?)", (uid, cid))
            self.conn.commit(); return "✅ Adicionado."
        except sqlite3.IntegrityError: return "⚠ Clube inexistente."

    def avaliar(self, uid, eid, estrelas):
        if not 1 <= estrelas <= 5: return "Nota inválida."
        if not self.conn.execute("SELECT 1 FROM inscricoes WHERE u_id=? AND e_id=? AND checkin=1", (uid, eid)).fetchone(): return "Não assististe."
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO avaliacoes (e_id,u_id,estrelas) VALUES (?,?,?)", (eid, uid, estrelas))
            self.conn.execute("UPDATE eventos SET aval=(SELECT AVG(estrelas) FROM avaliacoes WHERE e_id=?) WHERE id=?", (eid, eid))
        return "✅ Avaliado!"

    def obter_estatisticas(self, oid=None):
        q_ev = "WHERE org_id=?" if oid else ""
        q_ins = "WHERE e.org_id=?" if oid else ""
        p = (oid,) if oid else ()
        ne = self.conn.execute(f"SELECT COUNT(*) FROM eventos {q_ev} AND cancelado=0", p).fetchone()[0]
        ni = self.conn.execute(f"SELECT COUNT(*) FROM inscricoes i JOIN eventos e ON i.e_id=e.id {q_ins} AND i.cancelada=0 AND i.espera=0 AND e.cancelado=0", p).fetchone()[0]
        nt = self.conn.execute(f"SELECT COUNT(*) FROM inscricoes i JOIN eventos e ON i.e_id=e.id {q_ins} AND i.checkin=1 AND e.cancelado=0", p).fetchone()[0]
        return ne, ni, nt

    def obter_notificacoes(self, uid):
        res = self.conn.execute("SELECT txt FROM notificacoes WHERE u_id=? AND lida=0", (uid,)).fetchall()
        self.conn.execute("UPDATE notificacoes SET lida=1 WHERE u_id=?", (uid,))
        self.conn.commit(); return res

    def contar_notificacoes(self, uid):
        return self.conn.execute("SELECT COUNT(*) FROM notificacoes WHERE u_id=? AND lida=0", (uid,)).fetchone()[0]

    def notificar(self, uid, txt):
        self.conn.execute("INSERT INTO notificacoes (u_id, txt) VALUES (?,?)", (uid, txt))

# ═══════════════ INTERFACE ═══════════════
def pausa(): input("\n[Enter]")
def limpar(): os.system("cls" if os.name=="nt" else "clear")

def fazer_login(db):
    tentativas = 0
    while tentativas < 3:
        limpar(); print("=== SCHOOLPASS v16.0 ===")
        print("1. Entrar\n2. Registar Aluno\n0. Sair")
        op = input("Opção: ")
        if op == '0': return None
        if op == '2':
            n = input("Nome: "); e = input("Email: "); s = getpass.getpass("Senha: ")
            print(db.registar(n, e, s)); pausa()
            continue
        email = input("Email: ").strip(); senha = getpass.getpass("Senha: ")
        u = db.auth(email, senha)
        if u:
            if u['precisa_mudar_senha']:
                while True:
                    limpar(); print("⚠ Segurança: Tens de alterar a tua senha padrão.")
                    nova = getpass.getpass("Nova senha: ")
                    r = db.alterar_senha(u['id'], senha, nova)
                    if r == "OK": break
                    print("⚠", r); pausa()
                print("✅ Senha alterada."); pausa()
                u = db.auth(email, nova)
            return u
        tentativas += 1
        print(f"Erro. Tentativas restantes: {3 - tentativas}"); pausa()
    return None

def menu_perfil(db, u):
    limpar(); print("🔒 ALTERAR PALAVRA-PASSE")
    a = getpass.getpass("Senha atual: "); n = getpass.getpass("Nova senha: ")
    if n != getpass.getpass("Repetir nova senha: "): print("⚠ Não coincidem."); return pausa()
    print(db.alterar_senha(u['id'], a, n)); pausa()

def menu_notif(db, u):
    limpar(); print("🔔 NOTIFICAÇÕES:")
    for n in db.obter_notificacoes(u['id']): print("-", n['txt'])
    pausa()

def ecra_aluno(db, u):
    while True:
        limpar()
        nl = db.contar_notificacoes(u['id'])
        print(f"👤 Aluno: {u['nome']} {'(🔔 ' + str(nl) + ')' if nl else ''}")
        print("1.Eventos 2.Bilhetes 3.Clubes 4.Avaliar 5.Notificações 6.Perfil 0.Sair")
        op = input("Op: ")
        if op == '1':
            for ev in db.obter_eventos(): print(f"[{ev['id']}] {ev['titulo']} | ⭐{ev['aval']:.1f} | Org:{ev['organizador']}")
            try: eid = int(input("ID (0=voltar): "))
            except ValueError: continue
            if eid > 0: print(db.inscrever(u['id'], eid)); pausa()
        elif op == '2':
            for b in db.obter_bilhetes(u['id']):
                est = "⏳ Espera" if b['espera'] else ("✅ Usado" if b['checkin'] else "🎟️ Válido")
                print(f"[{b['id']}] {b['titulo']} | {b['cod']} | {est}")
                if not b['espera'] and not b['checkin']:
                    if HAS_QR:
                        qrcode.make(b['cod']).save(f"qrcode_{b['cod']}.png")
                        print(f"  📱 QR Code: 'qrcode_{b['cod']}.png'")
                    else: print("  ⚠ Instala a lib 'qrcode' para gerar o QR.")
            try: iid = int(input("\nID p/ cancelar (0=voltar): "))
            except ValueError: continue
            if iid > 0: print(db.cancelar_inscricao(iid, u['id'])); pausa()
        elif op == '3':
            for c in db.obter_clubes(u['id']): print(f"[{'✓' if c['inscrito'] else ' '}] [{c['id']}] {c['nome']}")
            try: cid = int(input("ID p/ entrar/sair: "))
            except ValueError: continue
            if cid > 0: print(db.toggle_clube(u['id'], cid)); pausa()
        elif op == '4':
            for ev in db.obter_eventos():
                if db.conn.execute("SELECT 1 FROM inscricoes WHERE u_id=? AND e_id=? AND checkin=1", (u['id'], ev['id'])).fetchone():
                    print(f"[{ev['id']}] {ev['titulo']}")
            try: eid = int(input("ID: ")); est = int(input("1-5: "))
            except ValueError: continue
            print(db.avaliar(u['id'], eid, est)); pausa()
        elif op == '5': menu_notif(db, u)
        elif op == '6': menu_perfil(db, u)
        elif op == '0': break

def ecra_prof(db, u):
    adm = (u['papel'] == 'admin')
    while True:
        limpar()
        nl = db.contar_notificacoes(u['id'])
        print(f"👨‍🏫 Prof: {u['nome']} {'(🔔 ' + str(nl) + ')' if nl else ''}")
        print("1.Criar 2.Editar 3.Checkin 4.Participantes 5.Estatísticas 6.CSV 7.Cancelar 8.Notificações 9.Perfil 0.Sair")
        op = input("Op: ")
        if op == '1':
            t = input("Nome: "); l = input("Local: ")
            try: c = int(input("Capacidade: "))
            except ValueError: continue
            print(db.criar_evento(t, l, c, input("Categoria: "), u['id'])); pausa()
        elif op == '2':
            try: eid = int(input("ID Evento a editar: "))
            except ValueError: continue
            print(db.editar_evento(eid, u['id'], adm, input("Novo Nome: "), input("Novo Local: "), int(input("Nova Capacidade: ")))); pausa()
        elif op == '3': print(db.checkin(input("Cód: ").strip().upper(), u['id'], adm)); pausa()
        elif op == '4':
            for ev in db.obter_eventos(): print(f"[{ev['id']}] {ev['titulo']}")
            try: eid = int(input("ID: "))
            except ValueError: continue
            if not db.autorizado(eid, u['id'], adm): print("⚠ Sem permissão."); pausa(); continue
            for p in db.conn.execute("SELECT u.nome,i.espera,i.checkin FROM inscricoes i JOIN utilizadores u ON i.u_id=u.id WHERE i.e_id=?", (eid,)):
                print(f"- {p['nome']} ({'Espera' if p['espera'] else 'Presente' if p['checkin'] else 'Inscrito'})")
            pausa()
        elif op == '5':
            ne, ni, nt = db.obter_estatisticas(None if adm else u['id'])
            print(f"Eventos:{ne} Insc:{ni} Entradas:{nt} Taxa:{(nt/ni*100) if ni else 0:.1f}%"); pausa()
        elif op == '6':
            try: eid = int(input("ID evento: "))
            except ValueError: continue
            if not db.autorizado(eid, u['id'], adm): print("⚠ Sem permissão."); pausa(); continue
            with open(f"evento_{eid}.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";"); w.writerow(["Nome", "Email", "Estado"])
                for p in db.conn.execute("SELECT u.nome,u.email,i.checkin,i.espera FROM inscricoes i JOIN utilizadores u ON i.u_id=u.id WHERE i.e_id=?", (eid,)):
                    w.writerow([p['nome'], p['email'], "Espera" if p['espera'] else ("Presente" if p['checkin'] else "Inscrito")])
            print("Exportado"); pausa()
        elif op == '7':
            for ev in db.obter_eventos(): print(f"[{ev['id']}] {ev['titulo']}")
            try: eid = int(input("ID p/ cancelar: "))
            except ValueError: continue
            print(db.cancelar_evento(eid, u['id'], adm)); pausa()
        elif op == '8': menu_notif(db, u)
        elif op == '9': menu_perfil(db, u)
        elif op == '0': break

if __name__ == "__main__":
    db = DBManager()
    try:
        while True:
            u = fazer_login(db)
            if not u: break
            if u['papel'] == 'aluno': ecra_aluno(db, u)
            else: ecra_prof(db, u)
    except KeyboardInterrupt: print("\nA sair...")
    finally: db.conn.close()