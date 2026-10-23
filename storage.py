"""Private persistence: Neon/Postgres in production; SQLite for local development."""
import os, re, sqlite3, threading
from contextlib import contextmanager

TABLES = ('apartments', 'memberships', 'sessions', 'attempts', 'summary', 'email_memberships', 'email_sessions', 'email_challenges', 'presentation', 'notices', 'administrators', 'resident_viewers', 'notice_notifications', 'committee_account', 'dashboard_sessions', 'notice_archives', 'notice_attachments', 'usage_events', 'monitoring_state')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS monitoring_state(id INTEGER PRIMARY KEY CHECK(id=1),started BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,email TEXT NOT NULL,event TEXT NOT NULL,page TEXT NOT NULL,apt INTEGER,at BIGINT NOT NULL,session_key TEXT NOT NULL,platform TEXT NOT NULL,browser TEXT NOT NULL,schema_version INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS usage_time ON usage_events(at);
CREATE INDEX IF NOT EXISTS usage_session_page ON usage_events(session_key,page,at);

CREATE TABLE IF NOT EXISTS notice_attachments(id TEXT PRIMARY KEY,notice_id TEXT,filename TEXT NOT NULL,mime TEXT NOT NULL,data TEXT NOT NULL,size INTEGER NOT NULL,created BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS dashboard_sessions(digest TEXT PRIMARY KEY,email TEXT NOT NULL,parent_digest TEXT NOT NULL,expires BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS notice_archives(notice_id TEXT PRIMARY KEY,deleted BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS committee_account(id INTEGER PRIMARY KEY CHECK(id=1),email TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS notice_notifications(notice_id TEXT NOT NULL,version INTEGER NOT NULL,state TEXT NOT NULL,recipients INTEGER NOT NULL DEFAULT 0,updated BIGINT NOT NULL,PRIMARY KEY(notice_id,version));
CREATE TABLE IF NOT EXISTS resident_viewers(email TEXT PRIMARY KEY,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS administrators(email TEXT PRIMARY KEY,active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,apt INTEGER,audience TEXT NOT NULL CHECK(audience IN ('all','owner','tenant')),kind TEXT NOT NULL CHECK(kind IN ('note','message')),title TEXT NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,updated BIGINT NOT NULL,version INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS presentation(id INTEGER PRIMARY KEY CHECK(id=1), photo TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS email_memberships(email TEXT NOT NULL, apt INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','tenant')), active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(email,apt,role));
CREATE TABLE IF NOT EXISTS email_sessions(digest TEXT PRIMARY KEY, email TEXT NOT NULL, expires BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS email_challenges(email TEXT PRIMARY KEY, digest TEXT NOT NULL, nonce TEXT NOT NULL, expires BIGINT NOT NULL, ready INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS apartments(apt INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(phone TEXT NOT NULL, apt INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','tenant')), active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(phone,apt,role));
CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, phone TEXT NOT NULL, expires BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, at BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_time ON attempts(key,at);
CREATE TABLE IF NOT EXISTS summary(id INTEGER PRIMARY KEY CHECK(id=1), html TEXT NOT NULL);
'''
_init_lock = threading.Lock()
_ready_urls = set()

class Database:
    def __init__(self, connection, postgres=False):
        self.connection = connection
        self.postgres = postgres

    def sql(self, statement):
        if not self.postgres: return statement
        statement = statement.replace('?', '%s').replace('group_concat(m.role)', "string_agg(m.role, ',')")
        # Table identifiers are fixed application-owned names, never user inputs.
        return re.sub(r'(?<![.\w])('+'|'.join(TABLES)+r')\b', r'portal.\1', statement)

    def execute(self, statement, values=()):
        return self.connection.execute(self.sql(statement), values)

    def executemany(self, statement, values):
        cursor = self.connection.cursor()
        try: cursor.executemany(self.sql(statement), values)
        finally: cursor.close()

    @contextmanager
    def transaction(self, lock=None):
        if self.postgres:
            with self.connection.transaction():
                if lock is not None:
                    number = int.from_bytes(__import__('hashlib').sha256(lock.encode()).digest()[:8], 'big', signed=True)
                    self.connection.execute('SELECT pg_advisory_xact_lock(%s)', (number,))
                yield self
        else:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()

    def __enter__(self):
        self._transaction = self.transaction()
        self._transaction.__enter__()
        return self

    def __exit__(self, *args):
        return self._transaction.__exit__(*args)


def connect(local_path):
    url = os.environ.get('DATABASE_URL', '').strip()
    if url:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.conninfo import conninfo_to_dict
        details = conninfo_to_dict(url)
        if details.get('host','').endswith('.neon.tech'):
            details.update(sslmode='verify-full', sslrootcert='/etc/ssl/certs/ca-certificates.crt', channel_binding='require')
        else:
            # Only explicit local test connections may run without TLS.
            if os.environ.get('PORTAL_TEST_DATABASE') != '1':
                details.update(sslmode='verify-full', sslrootcert='/etc/ssl/certs/ca-certificates.crt')
        db = Database(psycopg.connect(**details, row_factory=dict_row, autocommit=True, connect_timeout=15, prepare_threshold=None), True)
        try:
            with _init_lock:
                if url not in _ready_urls:
                    with db.transaction(lock='haruv-schema-v1'):
                        db.connection.execute('CREATE SCHEMA IF NOT EXISTS portal')
                        for statement in SCHEMA.split(';'):
                            if statement.strip(): db.execute(statement)
                    _ready_urls.add(url)
            return db
        except BaseException:
            db.close()
            raise
    if os.environ.get('RENDER'):
        raise RuntimeError('DATABASE_URL must be configured on Render; local storage is disabled')
    c = sqlite3.connect(local_path, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return Database(c)
