"""Durable notification attempts with exact apartment/role recipient scoping."""
import time,uuid

class Rejected(Exception): pass
class Uncertain(Exception): pass

def recipients(c,notice):
    query='SELECT DISTINCT email FROM email_memberships WHERE active=1'
    args=[]
    if notice['apt'] is not None:query+=' AND apt=?';args.append(notice['apt'])
    if notice['audience']!='all':query+=' AND role=?';args.append(notice['audience'])
    return sorted({r['email'].strip().lower() for r in c.execute(query,args).fetchall()})

def queue(c,ident,version):
    c.execute("INSERT INTO notice_notifications(notice_id,version,state,recipients,updated) VALUES(?,?,'pending',0,?) ON CONFLICT(notice_id,version) DO NOTHING",(ident,version,int(time.time())))

def latest(c,ident):
    r=c.execute('SELECT version,state,recipients,updated FROM notice_notifications WHERE notice_id=? ORDER BY version DESC LIMIT 1',(ident,)).fetchone()
    if not r:return None
    result=dict(r)
    if result['state']=='sending' and result['updated']<int(time.time())-60:result['state']='unknown'
    return result

def deliver(c,ident,version,sender):
    with c.transaction(lock='notice-mail:'+ident+':'+str(version)):
        job=c.execute('SELECT * FROM notice_notifications WHERE notice_id=? AND version=?',(ident,version)).fetchone()
        if not job:return {'state':'not_queued','recipients':0}
        if job['state'] not in ('pending','failed'):return {'state':job['state'],'recipients':job['recipients']}
        notice=c.execute('SELECT * FROM notices WHERE id=?',(ident,)).fetchone()
        email_only=c.execute('SELECT 1 FROM notice_email_only WHERE notice_id=? AND version=?',(ident,version)).fetchone() is not None
        archived=c.execute('SELECT 1 FROM notice_archives WHERE notice_id=?',(ident,)).fetchone() is not None
        expiry=c.execute('SELECT expires_at FROM notice_expirations WHERE notice_id=?',(ident,)).fetchone()
        if not notice or archived or (expiry and expiry['expires_at']<=int(time.time()) and not email_only) or (not notice['active'] and not email_only) or notice['version']!=version:
            c.execute("UPDATE notice_notifications SET state='cancelled',updated=? WHERE notice_id=? AND version=?",(int(time.time()),ident,version))
            return {'state':'cancelled','recipients':0}
        addresses=recipients(c,notice)
        state='sending' if addresses else 'empty'
        c.execute('UPDATE notice_notifications SET state=?,recipients=?,updated=? WHERE notice_id=? AND version=?',(state,len(addresses),int(time.time()),ident,version))
    if not addresses:return {'state':'empty','recipients':0}
    # Same content/recipient batch always gets the same provider idempotency UUID.
    key=str(uuid.uuid5(uuid.NAMESPACE_URL,'haruv:'+ident+':'+str(version)+':'+','.join(addresses)))
    try:sender(dict(notice,email_only=email_only),addresses,key);state='accepted'
    except Rejected:state='failed'
    except Exception:state='unknown'
    c.execute('UPDATE notice_notifications SET state=?,updated=? WHERE notice_id=? AND version=?',(state,int(time.time()),ident,version));c.commit()
    return {'state':state,'recipients':len(addresses)}
