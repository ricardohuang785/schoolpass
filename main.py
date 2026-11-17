import sqlite3, hashlib, secrets, os, hmac, csv, datetime, re

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

ITERACOES = 600000
FORMATO_EMAIL = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

class DBManager:
    def __init__(self, db_path="schoolpass.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
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

    def notificar(self, uid, txt):
        self.conn.execute("INSERT INTO notificacoes (u_id, txt) VALUES (?, ?)", (uid, txt))

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
            if hmac.compare_digest(self._criar_hash(senha, r['salt'], r['iteracoes']), r['senha']): return dict(r)
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
        return [dict(r) for r in self.conn.execute(q, (f"%{filtro}%", f"%{filtro}%") if filtro else ()).fetchall()]

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
        return [dict(r) for r in self.conn.execute("SELECT i.*, e.titulo FROM inscricoes i JOIN eventos e ON i.e_id=e.id WHERE i.u_id=? AND i.cancelada=0 AND e.cancelado=0", (uid,)).fetchall()]

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
            ins = self.conn.execute("SELECT * FROM inscricoes WHERE id=? AND u_id=? AND cancelada=0", (iid, uid)).fetchone()
            if not ins: return "Inscrição não encontrada."
            self.conn.execute("UPDATE inscricoes SET cancelada=1 WHERE id=?", (iid,))
            if ins['espera'] == 0:
                prox = self.conn.execute("SELECT * FROM inscricoes WHERE e_id=? AND espera=1 AND cancelada=0 ORDER BY id ASC LIMIT 1", (ins['e_id'],)).fetchone()
                if prox:
                    self.conn.execute("UPDATE inscricoes SET espera=0 WHERE id=?", (prox['id'],))
                    self.notificar(prox['u_id'], "🎉 Saiu da lista de espera! Inscrição confirmada.")
            return "Inscrição cancelada."
