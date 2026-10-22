"""Private tenant portal. Run behind HTTPS with gunicorn server:app."""
import os, json, sqlite3, secrets, hashlib, time, re, base64
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from pathlib import Path

ROOT = Path(__file__).parent
DB = os.environ.get('PORTAL_DB', '/data/portal.sqlite3')
ORIGIN = os.environ.get('PORTAL_ORIGIN', '')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS apartments(apt INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(phone TEXT NOT NULL, apt INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','tenant')), active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(phone,apt,role));
CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, phone TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_time ON attempts(key,at);
CREATE TABLE IF NOT EXISTS summary(id INTEGER PRIMARY KEY CHECK(id=1), html TEXT NOT NULL);
'''

def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c

def phone(value):
    s = re.sub(r'[\s()\-]', '', str(value or ''))
    if s.startswith('00972'): s = '+' + s[2:]
    if re.fullmatch(r'05\d{8}', s): s = '+972' + s[1:]
    if re.fullmatch(r'9725\d{8}', s): s = '+' + s
    if not re.fullmatch(r'\+9725\d{8}', s): raise ValueError('מספר נייד ישראלי אינו תקין')
    return s

def allowed(c, p):
    return c.execute('SELECT 1 FROM memberships WHERE phone=? AND active=1 LIMIT 1', (p,)).fetchone() is not None

def limit(c, key, maximum, seconds):
    now = int(time.time())
    # Serialize limit check and reservation across workers.
    c.execute('BEGIN IMMEDIATE')
    count = c.execute('SELECT count(*) FROM attempts WHERE key=? AND at>?', (key,now-seconds)).fetchone()[0]
    if count >= maximum:
        c.rollback(); return False
    c.execute('INSERT INTO attempts VALUES(?,?)',(key,now))
    c.execute('DELETE FROM attempts WHERE at<?',(now-86400,))
    c.commit(); return True

def twilio(action, fields):
    sid, token, service = [os.environ.get(k,'') for k in ('TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','TWILIO_VERIFY_SERVICE_SID')]
    if not (re.fullmatch(r'AC[0-9a-fA-F]{32}',sid) and token and re.fullmatch(r'VA[0-9a-fA-F]{32}',service)):
        raise RuntimeError('SMS אינו מחובר עדיין')
    req = Request(f'https://verify.twilio.com/v2/Services/{service}/{action}',data=urlencode(fields).encode(),headers={'Authorization':'Basic '+base64.b64encode(f'{sid}:{token}'.encode()).decode()})
    try:
        with urlopen(req,timeout=12) as response: return json.load(response)
    except HTTPError:
        return {'status':'failed'}

def app(env, start):
    status, headers = '200 OK', []
    def respond(body, code='200 OK', kind='application/json; charset=utf-8', extra=()):
        raw = body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
        start(code,[('Content-Type',kind),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('X-Frame-Options','SAMEORIGIN'),('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"),*extra])
        return [raw]
    path, method = env.get('PATH_INFO','/'), env.get('REQUEST_METHOD','GET')
    if method == 'GET' and path in ('/','/app.js','/style.css'):
        name = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
        kind = {'/':'text/html','/app.js':'application/javascript','/style.css':'text/css'}[path]
        return respond((ROOT/'static'/name).read_text(),kind=kind+'; charset=utf-8')
    if path == '/health': return respond({'ok': True})
    if not path.startswith('/api/'): return respond({'error':'לא נמצא'},'404 Not Found')
    if method not in ('GET','POST'): return respond({'error':'פעולה לא מורשית'},'405 Method Not Allowed')
    if method == 'POST' and (not ORIGIN or env.get('HTTP_ORIGIN') != ORIGIN):
        return respond({'error':'בקשה לא מורשית'},'403 Forbidden')
    try:
        n = int(env.get('CONTENT_LENGTH') or 0)
        if n < 0 or n > 2048: raise ValueError()
        body = json.loads(env['wsgi.input'].read(n) or b'{}') if method=='POST' else {}
        if not isinstance(body,dict): raise ValueError()
    except (ValueError,TypeError): return respond({'error':'בקשה לא תקינה'},'400 Bad Request')
    c = connect()
    try:
        if path in ('/api/send-code','/api/verify-code') and method=='POST':
            try: p = phone(body.get('phone'))
            except ValueError: return respond({'error':'יש להזין מספר נייד תקין'},'400 Bad Request')
            if path == '/api/send-code':
                if not limit(c,'send-global',100,3600) or not limit(c,'send:'+p,1,60) or not limit(c,'hour:'+p,5,3600):
                    return respond({'error':'נא להמתין לפני ניסיון נוסף'},'429 Too Many Requests')
                # Never send an SMS to a phone outside the allowlist.
                if allowed(c,p):
                    result = twilio('Verifications',{'To':p,'Channel':'sms'})
                    if result.get('status') != 'pending': raise RuntimeError()
                return respond({'message':'אם המספר מורשה, נשלח אליו קוד כניסה'})
            if not limit(c,'verify-global',1000,600) or not limit(c,'verify:'+p,5,600):
                return respond({'error':'יותר מדי ניסיונות; יש להמתין'},'429 Too Many Requests')
            code = str(body.get('code',''))
            if not re.fullmatch(r'\d{4,10}',code) or not allowed(c,p):
                return respond({'error':'הקוד או פרטי הגישה אינם תקינים'},'401 Unauthorized')
            result = twilio('VerificationCheck',{'To':p,'Code':code})
            if result.get('status') != 'approved' or not allowed(c,p):
                return respond({'error':'הקוד או פרטי הגישה אינם תקינים'},'401 Unauthorized')
            token = secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),p,int(time.time())+3600)); c.commit()
            return respond({'ok':True},extra=[('Set-Cookie',f'__Host-session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600')])
        cookies = SimpleCookie()
        try: cookies.load(env.get('HTTP_COOKIE',''))
        except Exception: return respond({'error':'יש להתחבר'},'401 Unauthorized')
        token = cookies.get('__Host-session')
        digest = hashlib.sha256((token.value if token else '').encode()).hexdigest()
        session = c.execute('SELECT phone FROM sessions WHERE digest=? AND expires>?',(digest,int(time.time()))).fetchone()
        if not session or not allowed(c,session['phone']): return respond({'error':'יש להתחבר מחדש'},'401 Unauthorized')
        p = session['phone']
        if path == '/api/logout' and method=='POST':
            c.execute('DELETE FROM sessions WHERE digest=?',(digest,)); c.commit()
            return respond({'ok':True},extra=[('Set-Cookie','__Host-session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0')])
        if path == '/api/apartments' and method=='GET':
            rows = c.execute('SELECT a.apt,a.payload,group_concat(m.role) AS roles FROM apartments a JOIN memberships m ON a.apt=m.apt WHERE m.phone=? AND m.active=1 GROUP BY a.apt ORDER BY a.apt',(p,)).fetchall()
            return respond({'apartments':[{'apt':r['apt'],'roles':r['roles'].split(','),'data':json.loads(r['payload'])} for r in rows]})
        if path == '/api/summary' and method=='GET':
            row = c.execute('SELECT html FROM summary WHERE id=1').fetchone()
            return respond(row['html'] if row else '<p dir="rtl">טרם הועלה סיכום</p>',kind='text/html; charset=utf-8')
        return respond({'error':'לא נמצא'},'404 Not Found')
    except Exception:
        # No codes, phones, tokens or provider response bodies in logs.
        return respond({'error':'השירות אינו זמין כרגע. נא לפנות לוועד'},'503 Service Unavailable')
    finally: c.close()
