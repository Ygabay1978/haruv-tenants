"""First-party, authenticated usage metrics. No IPs, codes, tokens or message contents."""
import hashlib,json,time,secrets,logging
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
PAGES={'apartment':'הדירה שלי','payments':'תשלומים','building_summary':'תמונת מצב הבניין','gym':'חדר כושר','gym_booking':'קביעת תור לחדר כושר','pal':'PAL','attachments':'מסמכים ותמונות'}
TZ=ZoneInfo('Asia/Jerusalem')
RETENTION=90*86400

def device(env):
    ua=env.get('HTTP_USER_AGENT','').lower()
    platform='Android' if 'android' in ua else 'iPhone / iPad' if any(s in ua for s in ('iphone','ipad','ipod')) else 'Windows' if 'windows' in ua else 'Mac' if 'macintosh' in ua else 'Linux' if 'linux' in ua else 'לא זוהה'
    browser='Edge' if 'edg/' in ua else 'Firefox' if 'firefox' in ua or 'fxios' in ua else 'Chrome' if 'chrome' in ua or 'crios' in ua else 'Safari' if 'safari' in ua else 'לא זוהה'
    return platform,browser

def session_key(digest):return hashlib.sha256(('usage:'+digest).encode()).hexdigest()[:32] if digest else ''

def begin(c):
    stamp=int(time.time())
    c.execute('INSERT INTO monitoring_state VALUES(1,?) ON CONFLICT(id) DO NOTHING',(stamp,))
    return stamp

def record(c,address,event,page='',apt=None,digest='',env=None):
    # Metrics are best-effort and must never prevent login or document access.
    try:
        platform,browser=device(env or {});stamp=int(time.time())
        with c.transaction():
            begin(c)
            c.execute('DELETE FROM usage_events WHERE at<?',(stamp-RETENTION,))
            c.execute('INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?)',(secrets.token_hex(16),address,event,page,apt,stamp,session_key(digest),platform,browser,1))
        return True
    except Exception:
        logging.getLogger('portal').warning('usage_metric_write_failed')
        return False

def report(c,days,include_committee=False):
    now=int(time.time());begin(c);c.commit()
    today=datetime.fromtimestamp(now,TZ).date();start=int(datetime.combine(today-timedelta(days=days-1),datetime.min.time(),TZ).timestamp())
    committee=c.execute('SELECT email FROM committee_account WHERE id=1').fetchone();committee=committee['email'] if committee else ''
    rows=[dict(r) for r in c.execute('SELECT email,event,page,apt,at,session_key,platform,browser FROM usage_events WHERE at>=? AND at<=? ORDER BY at',(max(start,now-RETENTION),now)).fetchall()]
    activity=[r for r in rows if r['event'] in ('login','logout','view','active','download') and (include_committee or r['email']!=committee)]
    grouped=defaultdict(list)
    for r in activity:grouped[r['email']].append(r)
    memberships=[dict(r) for r in c.execute('SELECT email,apt,role,active FROM email_memberships').fetchall()]
    grants=defaultdict(list)
    for r in memberships:grants[r['email']].append(r)
    payloads={r['apt']:json.loads(r['payload']) for r in c.execute('SELECT apt,payload FROM apartments').fetchall()}
    def identity(address):
        names=[]
        for g in grants[address]:
            payload=payloads.get(g['apt'],{})
            for contact in payload.get('ownerContacts',[])+payload.get('tenantContacts',[]):
                if str(contact.get('email','')).strip().lower()==address and contact.get('name'):names.append(contact['name'])
        return ' / '.join(dict.fromkeys(names)) or address
    active_addresses={g['email'] for g in memberships if g['active'] and (include_committee or g['email']!=committee)}
    users=[]
    for address in active_addresses|set(grouped):
        events=grouped[address];last=events[-1] if events else None
        users.append({'email':address,'name':identity(address),'apartments':sorted({g['apt'] for g in grants[address] if g['active']}),'roles':sorted({g['role'] for g in grants[address] if g['active']}),'committee':address==committee,'active':address in active_addresses,'logins':sum(r['event']=='login' for r in events),'views':sum(r['event']=='view' for r in events),'downloads':sum(r['event']=='download' for r in events),'last_login':max((r['at'] for r in events if r['event']=='login'),default=None),'last_seen':last['at'] if last else None,'platform':last['platform'] if last else '', 'browser':last['browser'] if last else ''})
    users.sort(key=lambda u:(-(u['last_seen'] or 0),u['email']))
    views=[r for r in activity if r['event']=='view'];engaged=[r for r in activity if r['event']!='logout']
    pages=[{'page':key,'label':label,'views':sum(r['page']==key for r in views),'users':len({r['email'] for r in views if r['page']==key})} for key,label in PAGES.items()];pages.sort(key=lambda p:-p['views'])
    daily=[];by_day=defaultdict(list)
    for r in engaged:by_day[datetime.fromtimestamp(r['at'],TZ).date()].append(r)
    for i in range(days):
        date=today-timedelta(days=days-i-1);events=by_day[date]
        daily.append({'date':date.isoformat(),'logins':sum(r['event']=='login' for r in events),'views':sum(r['event']=='view' for r in events),'users':len({r['email'] for r in events})})
    hours=Counter(datetime.fromtimestamp(r['at'],TZ).hour for r in views)
    devices=Counter(r['platform'] for r in activity if r['event']=='login')
    jobs=[dict(r) for r in c.execute('SELECT state,recipients,updated FROM notice_notifications WHERE updated>=? AND updated<=?',(start,now)).fetchall()]
    mail={'otp_accepted':sum(r['event']=='otp_accepted' for r in rows),'otp_failed':sum(r['event']=='otp_failed' for r in rows),'notice_accepted':sum(j['recipients'] for j in jobs if j['state']=='accepted'),'notice_failed':sum(j['recipients'] for j in jobs if j['state']=='failed'),'notice_unknown':sum(j['recipients'] for j in jobs if j['state'] in ('unknown','sending')),'notice_pending':sum(j['recipients'] for j in jobs if j['state']=='pending')}
    mail['accepted']=mail['otp_accepted']+mail['notice_accepted'];mail['failed']=mail['otp_failed']+mail['notice_failed']
    recent=[dict(r,name=identity(r['email'])) for r in reversed(activity) if r['event']!='active'][:200]
    for r in recent:r.pop('session_key',None)
    started=c.execute('SELECT started FROM monitoring_state WHERE id=1').fetchone()['started']
    return {'days':days,'timezone':'Asia/Jerusalem','generated':now,'started':started,'retention_days':90,'include_committee':include_committee,'summary':{'registered':len(active_addresses),'active_users':len({r['email'] for r in engaged}),'logins':sum(r['event']=='login' for r in activity),'sessions':len({r['session_key'] for r in engaged if r['session_key']}),'views':len(views),'downloads':sum(r['event']=='download' for r in activity),'active_minutes':sum(r['event']=='active' for r in activity)},'mail':mail,'pages':pages,'daily':daily,'hours':[{'hour':h,'views':hours[h]} for h in range(24)],'devices':[{'name':name,'logins':count} for name,count in devices.most_common()],'users':users,'recent':recent}
