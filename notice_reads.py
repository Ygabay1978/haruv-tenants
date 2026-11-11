"""Account-level notice visibility. A recorded view is not proof of comprehension."""
import json,time
from portal_rules import apartment_has_resident_owner, notice_audience_matches, resident_owner

def record(c,address,ident,version,apt):
    rows=c.execute("""SELECT n.audience,m.role FROM notices n
        JOIN email_memberships m ON m.email=? AND m.apt=? AND m.active=1
        WHERE n.id=? AND n.version=? AND n.active=1
        AND NOT EXISTS(SELECT 1 FROM notice_expirations e WHERE e.notice_id=n.id AND e.expires_at<=?)
        AND (n.apt IS NULL OR n.apt=?)""",(address,apt,ident,version,int(time.time()),apt)).fetchall()
    if not any(notice_audience_matches(r['audience'],r['role'],r['audience']=='residents'
        and r['role']=='owner' and apartment_has_resident_owner(c,apt)) for r in rows):
        return False
    stamp=int(time.time())
    c.execute("""INSERT INTO notice_reads(notice_id,version,email,apt,first_seen,last_seen)
        VALUES(?,?,?,?,?,?) ON CONFLICT(notice_id,version,email,apt)
        DO UPDATE SET last_seen=excluded.last_seen""",(ident,version,address,apt,stamp,stamp))
    c.commit()
    return True

def report(c,include_committee=False):
    committee=c.execute('SELECT email FROM committee_account WHERE id=1').fetchone()
    excluded=committee['email'] if committee and not include_committee else None
    memberships=[dict(r) for r in c.execute('SELECT email,apt,role FROM email_memberships WHERE active=1').fetchall()]
    tenant_apts={m['apt'] for m in memberships if m['role']=='tenant'}
    payloads={r['apt']:json.loads(r['payload']) for r in c.execute('SELECT apt,payload FROM apartments').fetchall()}
    views={}
    for r in c.execute('SELECT notice_id,version,email,min(first_seen) AS first_seen,max(last_seen) AS last_seen FROM notice_reads GROUP BY notice_id,version,email').fetchall():
        views[(r['notice_id'],r['version'],r['email'])]=dict(r)
    result=[]
    for n in c.execute("""SELECT n.* FROM notices n WHERE NOT EXISTS
        (SELECT 1 FROM notice_archives a WHERE a.notice_id=n.id) ORDER BY n.updated DESC,n.id LIMIT 100""").fetchall():
        eligible={}
        for g in memberships:
            if g['email']==excluded or (n['apt'] is not None and g['apt']!=n['apt']) or not notice_audience_matches(
                n['audience'],g['role'],n['audience']=='residents' and g['role']=='owner'
                and resident_owner(payloads.get(g['apt']),g['apt'] in tenant_apts)):continue
            person=eligible.setdefault(g['email'],{'email':g['email'],'apartments':set(),'names':[]})
            person['apartments'].add(g['apt'])
            key='ownerContacts' if g['role']=='owner' else 'tenantContacts'
            for contact in payloads.get(g['apt'],{}).get(key,[]):
                if str(contact.get('email','')).strip().lower()==g['email'] and contact.get('name'):person['names'].append(contact['name'])
        recipients=[]
        for email,person in eligible.items():
            seen=views.get((n['id'],n['version'],email),{}) if n['active'] else {}
            recipients.append({'email':email,'name':' / '.join(dict.fromkeys(person['names'])) or email,
                'apartments':sorted(person['apartments']),'first_seen':seen.get('first_seen'),'last_seen':seen.get('last_seen')})
        recipients.sort(key=lambda r:(r['first_seen'] is None,-(r['first_seen'] or 0),r['email']))
        job=c.execute('SELECT state,recipients FROM notice_notifications WHERE notice_id=? AND version=?',(n['id'],n['version'])).fetchone()
        result.append({'id':n['id'],'version':n['version'],'title':n['title'],'active':bool(n['active']),
            'email_only':c.execute('SELECT 1 FROM notice_email_only WHERE notice_id=? AND version=?',(n['id'],n['version'])).fetchone() is not None,
            'updated':n['updated'],'audience':n['audience'],'apt':n['apt'],'notification':dict(job) if job else None,
            'viewed':sum(r['first_seen'] is not None for r in recipients),'recipients':recipients})
    return result
