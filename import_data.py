"""Run on the private server only. Never commit input data or database."""
import argparse, json, re, os
from pathlib import Path
import server
import tenant_summary

def embedded(path, element):
    value = re.search(r'<script\b[^>]*\bid=["\']'+re.escape(element)+r'["\'][^>]*>(.*?)</script>',Path(path).read_text(),re.S)
    if not value: raise ValueError('Missing embedded data')
    return json.loads(value[1])

def import_data(full, tenants):
    data = embedded(full,'embedded-data')
    summary = embedded(tenants,'embedded-summary')
    if not isinstance(summary,dict): raise ValueError('Invalid tenants summary')
    html = Path(tenants).read_text()
    # Store only the explicit read-only tenant file, never the full committee HTML.
    if 'embedded-data' in html or 'fileInput' in html: raise ValueError('Expected read-only tenant dashboard')
    html = tenant_summary.render(html)
    rows, grants, rejected = {}, set(), 0
    for r in data['residents']:
        apt = int(r['apt'])
        if apt in rows: raise ValueError('Duplicate apartment')
        rows[apt] = {k:r.get(k,0) for k in ['monthly','annual','paid','due']}
        rows[apt]['monthlyPayments'] = r.get('monthlyPayments',[])
        rows[apt]['monthlyReceipts'] = r.get('monthlyReceipts',[])
        rows[apt]['year'] = int(data.get('year',2026))
        rows[apt]['support'] = data.get('support',[])
    for ev in (data.get('evTable') or {}).get('residents',[]):
        apt=int(ev['apt'])
        if apt not in rows: continue
        def clean_note(value):
            if not value:return None
            text=str(value)
            return text.split('Comment:',1)[-1].strip() if 'Comment:' in text else text.strip()
        rows[apt]['electricVehicle'] = {
            'holder':str(ev.get('name') or ''), 'months':ev.get('months',[]),
            'monthNotes':[clean_note(n) for n in ev.get('monthNotes',[])],
            'monthUnpaid':ev.get('monthUnpaid',[]),
            'sourceNotes':[str(ev[k]) for k in ('novemberText','decemberText') if ev.get(k)]}

    for entry in data['directory']:
        apt = int(entry['apt'])
        if apt in rows:
            for key in ('floor','rooms','parking','storage'): rows[apt][key]=entry.get(key)
            for key,prefixes in [('ownerContacts',['owner1','owner2']),('tenantContacts',['tenant1','tenant2','tenant3'])]:
                rows[apt][key]=[{'name':str(entry[prefix+'Name']).strip(),'phone':str(entry.get(prefix+'Phone') or '').strip(),'email':str(entry.get(prefix+'Email') or '').strip()} for prefix in prefixes if entry.get(prefix+'Name') and str(entry[prefix+'Name']).strip() not in ('-','אין')]
            for role, prefixes in [('owners',['owner1','owner2']),('tenants',['tenant1','tenant2','tenant3'])]:
                rows[apt][role] = list(dict.fromkeys(str(entry[prefix+'Name']).strip() for prefix in prefixes
                    if entry.get(prefix+'Name') and str(entry[prefix+'Name']).strip() not in ('-','אין')))
    for entry in data['directory']:
        apt = int(entry['apt'])
        if apt not in rows: continue
        rows[apt]['access'] = {key:str(entry.get(field) or '').strip() if str(entry.get(field) or '').strip() not in ('-','אין') else ''
                               for key,field in [('gym','gymAccess'),('pal','palAccess')]}
        for field in ['owner1Email','owner2Email','tenant1Email','tenant2Email','tenant3Email']:
            raw = entry.get(field)
            if raw is None or str(raw).strip() in ('','-'): continue
            value = str(raw).strip()
            try: p = server.email(value)
            except ValueError: rejected += 1; continue
            grants.add((p,apt,'owner' if field.startswith('owner') else 'tenant'))
    if not rows or not grants: raise ValueError('No valid apartments or memberships; import cancelled')
    if not os.environ.get('DATABASE_URL'): Path(server.DB).parent.mkdir(parents=True,exist_ok=True)
    try: photo = embedded(tenants,'embedded-photo')
    except ValueError: photo = None
    if photo is not None: server.photo_bytes(photo)
    c = server.connect()
    try:
        with c:
            if photo is not None:
                c.execute('INSERT INTO presentation VALUES(1,?) ON CONFLICT(id) DO UPDATE SET photo=excluded.photo',(photo,))
            c.execute('DELETE FROM apartments')
            c.executemany('INSERT INTO apartments VALUES(?,?)',[(apt,json.dumps(v,ensure_ascii=False)) for apt,v in rows.items()])
            # Preserve explicit deactivations for retained contacts; remove departed contacts.
            for old in c.execute('SELECT email,apt,role FROM email_memberships').fetchall():
                if (old['email'],old['apt'],old['role']) not in grants: c.execute('DELETE FROM email_memberships WHERE email=? AND apt=? AND role=?',(old['email'],old['apt'],old['role']))
            c.executemany('INSERT INTO email_memberships(email,apt,role) VALUES(?,?,?) ON CONFLICT(email,apt,role) DO NOTHING',sorted(grants))
            c.execute('INSERT INTO summary VALUES(1,?) ON CONFLICT(id) DO UPDATE SET html=excluded.html',(html,))
            c.execute('DELETE FROM email_sessions WHERE email NOT IN (SELECT email FROM email_memberships WHERE active=1)')
        if not c.postgres: os.chmod(server.DB,0o600)
        return {'apartments':len(rows),'email_apartment_roles':len(grants),'unique_emails':len({g[0] for g in grants}),'skipped_email_fields':rejected}
    finally: c.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--full',required=True); p.add_argument('--tenants',required=True)
    args = p.parse_args()
    print(json.dumps(import_data(args.full,args.tenants)))
