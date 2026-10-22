"""Private tenant portal. Run behind HTTPS with gunicorn server:app."""
import os, json, sqlite3, secrets, hashlib, time, re, hmac, logging, base64
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from pathlib import Path

ROOT = Path(__file__).parent
DB = os.environ.get('PORTAL_DB', '/data/portal.sqlite3')
ORIGIN = os.environ.get('PORTAL_ORIGIN', '')
import storage
import tenant_summary, portal_rules

def connect():
    return storage.connect(DB)

def phone(value):
    s = re.sub(r'[\s()\-]', '', str(value or ''))
    if s.startswith('00972'): s = '+' + s[2:]
    if re.fullmatch(r'05\d{8}', s): s = '+972' + s[1:]
    if re.fullmatch(r'9725\d{8}', s): s = '+' + s
    if not re.fullmatch(r'\+9725\d{8}', s): raise ValueError('מספר נייד ישראלי אינו תקין')
    return s

def email(value):
    value = str(value or '').strip().lower()
    if len(value)>254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError('כתובת המייל אינה תקינה')
    return value

def allowed(c, p):
    return c.execute('SELECT 1 FROM email_memberships WHERE email=? AND active=1 LIMIT 1', (p,)).fetchone() is not None

def email_configured():
    return bool(os.environ.get('BREVO_API_KEY') and os.environ.get('EMAIL_FROM') and len(os.environ.get('OTP_SECRET',''))>=32)

def otp_digest(address, nonce, code):
    return hmac.new(os.environ['OTP_SECRET'].encode(), (address+'\n'+nonce+'\n'+code).encode(), hashlib.sha256).hexdigest()

def limit(c, key, maximum, seconds):
    now = int(time.time())
    with c.transaction(lock='rate:'+key):
        row = c.execute('SELECT count(*) AS total FROM attempts WHERE key=? AND at>?', (key,now-seconds)).fetchone()
        if row['total'] >= maximum: return False
        c.execute('INSERT INTO attempts VALUES(?,?)',(key,now))
        c.execute('DELETE FROM attempts WHERE at<?',(now-86400,))
    return True

def photo_bytes(photo):
    if not isinstance(photo,str) or len(photo)>4000000:
        raise ValueError('Invalid image')
    match = re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)', photo)
    if not match: raise ValueError('Invalid image')
    raw = base64.b64decode(match[2],validate=True)
    if not ((match[1]=='image/jpeg' and raw.startswith(b'\xff\xd8\xff')) or
            (match[1]=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or
            (match[1]=='image/webp' and raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')):
        raise ValueError('Invalid image')
    return raw, match[1]

def delivery_event(event, http_status=None, reason=None):
    # Fixed categories only: never log recipient, OTP, API key or raw provider text.
    logging.getLogger('portal.delivery').warning(json.dumps({
        'event':event, 'http_status':http_status, 'reason':reason}))

def provider_reason(error):
    try:
        body = json.loads(error.read(8192))
        code = body.get('code')
        message = str(body.get('message','')).lower()
        if 'ip' in message and any(v in message for v in ('unrecogn', 'authoriz', 'whitelist', 'allowlist')):
            return 'provider_ip_restriction'
        if 'sender' in message: return 'provider_sender_rejected'
        if 'activat' in message or 'suspend' in message: return 'provider_account_restricted'
        if code in ('unauthorized','permission_denied','invalid_parameter','missing_parameter','not_enough_credits','account_under_validation','too_many_requests'):
            return code
    except Exception:
        pass
    return 'provider_rejected'

def send_email(address, code):
    payload = {'sender':{'name':'בניין חרוב','email':email(os.environ['EMAIL_FROM'])},
               'to':[{'email':address}], 'subject':'קוד כניסה לפורטל בניין חרוב',
               'textContent':f'קוד הכניסה שלך: {code}\nהקוד תקף ל-10 דקות ולשימוש אחד. אין להעביר אותו לאחרים.\nאם לא ביקשת קוד כניסה, אפשר להתעלם מההודעה.'}
    req = Request('https://api.brevo.com/v3/smtp/email',data=json.dumps(payload).encode(),
                  headers={'api-key':os.environ['BREVO_API_KEY'],'Content-Type':'application/json','Accept':'application/json'})
    try:
        with urlopen(req,timeout=12) as response:
            if response.status != 201:
                delivery_event('email_delivery_failed', response.status, 'unexpected_provider_status')
                raise RuntimeError('Email delivery failed')
        delivery_event('email_provider_accepted', 201)
    except HTTPError as error:
        delivery_event('email_delivery_failed', error.code, provider_reason(error))
        raise RuntimeError('Email delivery failed') from None
    except (URLError, TimeoutError, OSError):
        delivery_event('email_delivery_failed', reason='provider_connection_failed')
        raise RuntimeError('Email delivery failed') from None

def is_admin(c,address):
    return c.execute('SELECT 1 FROM administrators WHERE email=? AND active=1',(address,)).fetchone() is not None

def resident_notices(c,address,apt):
    return [dict(r) for r in c.execute("SELECT id,kind,title,body,updated FROM notices WHERE active=1 AND (apt IS NULL OR apt=?) AND (audience='all' OR audience IN (SELECT role FROM email_memberships WHERE email=? AND apt=? AND active=1)) ORDER BY updated DESC,id",(apt,address,apt)).fetchall()]

def app(env, start):
    status, headers = '200 OK', []
    def respond(body, code='200 OK', kind='application/json; charset=utf-8', extra=()):
        raw = body if isinstance(body,bytes) else body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
        start(code,[('Content-Type',kind),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('X-Frame-Options','SAMEORIGIN'),('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"),*extra])
        return [raw]
    path, method = env.get('PATH_INFO','/'), env.get('REQUEST_METHOD','GET')
    if method == 'GET' and path in ('/','/admin','/app.js','/admin.js','/style.css'):
        name = {'/':'index.html','/admin':'admin.html','/app.js':'app.js','/admin.js':'admin.js','/style.css':'style.css'}[path]
        kind = {'/':'text/html','/admin':'text/html','/app.js':'application/javascript','/admin.js':'application/javascript','/style.css':'text/css'}[path]
        return respond((ROOT/'static'/name).read_text(),kind=kind+'; charset=utf-8')
    if path == '/building-photo' and method=='GET':
        db = None
        try:
            db = connect()
            row = db.execute('SELECT photo FROM presentation WHERE id=1').fetchone()
            if not row: return respond({'error':'לא נמצאה תמונה'},'404 Not Found')
            raw, kind = photo_bytes(row['photo'])
            return respond(raw,kind=kind)
        except Exception:
            return respond({'error':'התמונה אינה זמינה'},'404 Not Found')
        finally:
            if db: db.close()
    if path == '/health': return respond({'ok': True})
    if path == '/api/status' and method == 'GET':
        db = None
        try:
            db = connect()
            ready = db.execute('SELECT 1 FROM apartments LIMIT 1').fetchone() is not None
            grants = db.execute('SELECT 1 FROM email_memberships WHERE active=1 LIMIT 1').fetchone() is not None
            return respond({'database':'connected','data_ready':ready,'email_access_ready':grants,'email_configured':email_configured(),'version':'residence-v4'})
        except Exception:
            return respond({'database':'unavailable','data_ready':False,'email_configured':False,'version':'residence-v4'}, '503 Service Unavailable')
        finally:
            if db: db.close()
    if not path.startswith('/api/'): return respond({'error':'לא נמצא'},'404 Not Found')
    if method not in ('GET','POST'): return respond({'error':'פעולה לא מורשית'},'405 Method Not Allowed')
    if method == 'POST' and (not ORIGIN or env.get('HTTP_ORIGIN') != ORIGIN):
        return respond({'error':'בקשה לא מורשית'},'403 Forbidden')
    try:
        n = int(env.get('CONTENT_LENGTH') or 0)
        if n < 0 or n > 20000: raise ValueError()
        body = json.loads(env['wsgi.input'].read(n) or b'{}') if method=='POST' else {}
        if not isinstance(body,dict): raise ValueError()
    except (ValueError,TypeError): return respond({'error':'בקשה לא תקינה'},'400 Bad Request')
    c = None
    try:
        c = connect()
        if path in ('/api/send-code','/api/verify-code') and method=='POST':
            try: p = email(body.get('email'))
            except ValueError: return respond({'error':'יש להזין כתובת מייל תקינה'},'400 Bad Request')
            if not email_configured(): raise RuntimeError('Email is not configured')
            if path == '/api/send-code':
                if not limit(c,'email-day',200,86400) or not limit(c,'email-send-global',50,3600) or not limit(c,'email-send:'+p,1,60) or not limit(c,'email-hour:'+p,5,3600):
                    return respond({'error':'נא להמתין לפני ניסיון נוסף'},'429 Too Many Requests')
                if allowed(c,p):
                    code = f'{secrets.randbelow(1000000):06d}'
                    nonce = secrets.token_urlsafe(24)
                    with c.transaction(lock='email-otp:'+p):
                        c.execute('DELETE FROM email_challenges WHERE expires<?',(int(time.time()),))
                        c.execute('INSERT INTO email_challenges VALUES(?,?,?,?,0) ON CONFLICT(email) DO UPDATE SET digest=excluded.digest,nonce=excluded.nonce,expires=excluded.expires,ready=0',
                                  (p,otp_digest(p,nonce,code),nonce,int(time.time())+600))
                    try:
                        send_email(p,code)
                        c.execute('UPDATE email_challenges SET ready=1 WHERE email=? AND nonce=?',(p,nonce));c.commit()
                    except Exception:
                        c.execute('DELETE FROM email_challenges WHERE email=? AND nonce=?',(p,nonce));c.commit()
                        # Same public response prevents account enumeration on delivery errors.
                else:
                    delivery_event('email_request_skipped', reason='no_active_membership')
                return respond({'message':'אם המייל מורשה, נשלח אליו קוד כניסה. בדקו גם בתיקיית הספאם.'})
            if not limit(c,'email-verify-global',1000,600) or not limit(c,'email-verify:'+p,5,600):
                return respond({'error':'יותר מדי ניסיונות; יש להמתין'},'429 Too Many Requests')
            code = str(body.get('code',''))
            token = secrets.token_urlsafe(32)
            with c.transaction(lock='email-otp:'+p):
                challenge = c.execute('SELECT * FROM email_challenges WHERE email=? AND ready=1 AND expires>?',(p,int(time.time()))).fetchone()
                valid = bool(re.fullmatch(r'[0-9]{6}',code) and challenge and allowed(c,p) and hmac.compare_digest(challenge['digest'],otp_digest(p,challenge['nonce'],code)))
                if valid:
                    c.execute('DELETE FROM email_challenges WHERE email=?',(p,))
                    c.execute('DELETE FROM email_sessions WHERE expires<?',(int(time.time()),))
                    c.execute('INSERT INTO email_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),p,int(time.time())+3600))
            if not valid: return respond({'error':'הקוד או פרטי הגישה אינם תקינים'},'401 Unauthorized')
            return respond({'ok':True},extra=[('Set-Cookie',f'__Host-session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600')])
        cookies = SimpleCookie()
        try: cookies.load(env.get('HTTP_COOKIE',''))
        except Exception: return respond({'error':'יש להתחבר'},'401 Unauthorized')
        token = cookies.get('__Host-session')
        digest = hashlib.sha256((token.value if token else '').encode()).hexdigest()
        session = c.execute('SELECT email FROM email_sessions WHERE digest=? AND expires>?',(digest,int(time.time()))).fetchone()
        if not session or not allowed(c,session['email']): return respond({'error':'יש להתחבר מחדש'},'401 Unauthorized')
        p = session['email']
        if path == '/api/logout' and method=='POST':
            c.execute('DELETE FROM email_sessions WHERE digest=?',(digest,)); c.commit()
            return respond({'ok':True},extra=[('Set-Cookie','__Host-session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0')])
        if path.startswith('/api/admin/'):
            if not is_admin(c,p):return respond({'error':'גישה לוועד בלבד'},'403 Forbidden')
            if path=='/api/admin/context' and method=='GET':
                rows=c.execute('SELECT apt,payload FROM apartments ORDER BY apt').fetchall()
                return respond({'apartments':[{'apt':r['apt'],'owners':json.loads(r['payload']).get('owners',[]),'tenants':json.loads(r['payload']).get('tenants',[])} for r in rows]})
            if path=='/api/admin/notices' and method=='GET':
                return respond({'notices':[dict(r) for r in c.execute('SELECT * FROM notices ORDER BY updated DESC,id').fetchall()]})
            if path=='/api/admin/notices' and method=='POST':
                if not limit(c,'admin-change:'+p,200,3600):return respond({'error':'נא להמתין לפני ניסיון נוסף'},'429 Too Many Requests')
                try:values=portal_rules.notice_input(body,c)
                except (ValueError,TypeError):return respond({'error':'יש להשלים כותרת, תוכן וקהל יעד תקינים'},'400 Bad Request')
                ident=body.get('id');stamp=int(time.time())
                if ident:
                    if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{32}',ident):return respond({'error':'מזהה לא תקין'},'400 Bad Request')
                    version=body.get('version')
                    if type(version) is not int or version<1:return respond({'error':'גרסה לא תקינה'},'400 Bad Request')
                    with c.transaction(lock='notice:'+ident):
                        old=c.execute('SELECT version FROM notices WHERE id=?',(ident,)).fetchone()
                        if not old or old['version']!=version:return respond({'error':'ההודעה השתנתה. רעננו לפני שמירה'},'409 Conflict')
                        c.execute('UPDATE notices SET apt=?,audience=?,kind=?,title=?,body=?,active=?,updated=?,version=version+1 WHERE id=?',(*values,stamp,ident))
                else:
                    ident=secrets.token_hex(16)
                    c.execute('INSERT INTO notices VALUES(?,?,?,?,?,?,?,?,1)',(ident,*values,stamp));c.commit()
                return respond({'ok':True,'id':ident})
            return respond({'error':'לא נמצא'},'404 Not Found')
        if path == '/api/apartments' and method=='GET':
            rows = c.execute('SELECT a.apt,a.payload,group_concat(m.role) AS roles FROM apartments a JOIN email_memberships m ON a.apt=m.apt WHERE m.email=? AND m.active=1 GROUP BY a.apt ORDER BY a.apt',(p,)).fetchall()
            return respond({'apartments':[{'apt':r['apt'],'roles':r['roles'].split(','),'data':portal_rules.resident_payload(r['payload']),'notices':resident_notices(c,p,r['apt'])} for r in rows]})
        if path == '/api/summary' and method=='GET':
            row = c.execute('SELECT html FROM summary WHERE id=1').fetchone()
            html = tenant_summary.render(row['html']) if row else '<p dir="rtl">טרם הועלה סיכום</p>'
            return respond(html,kind='text/html; charset=utf-8')
        return respond({'error':'לא נמצא'},'404 Not Found')
    except Exception:
        # No codes, phones, tokens or provider response bodies in logs.
        return respond({'error':'השירות אינו זמין כרגע. נא לפנות לוועד'},'503 Service Unavailable')
    finally:
        if c: c.close()
