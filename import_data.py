"""Run on the private server only. Never commit input data or database."""
import argparse, json, re, os
from pathlib import Path
import server

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
    rows, grants, rejected = {}, set(), 0
    for r in data['residents']:
        apt = int(r['apt'])
        if apt in rows: raise ValueError('Duplicate apartment')
        rows[apt] = {k:r.get(k,0) for k in ['monthly','annual','paid','due']}
        rows[apt]['monthlyPayments'] = r.get('monthlyPayments',[])
    for entry in data['directory']:
        apt = int(entry['apt'])
        if apt not in rows: continue
        for field in ['owner1Phone','owner1AltPhone','owner2Phone','tenant1Phone','tenant2Phone','tenant3Phone']:
            raw = entry.get(field)
            if raw is None or str(raw).strip() in ('','-'): continue
            value = str(raw).strip()
            if re.fullmatch(r'5\d{8}',value): value = '0'+value
            try: p = server.phone(value)
            except ValueError: rejected += 1; continue
            grants.add((p,apt,'owner' if field.startswith('owner') else 'tenant'))
    if not rows or not grants: raise ValueError('No valid apartments or memberships; import cancelled')
    if not os.environ.get('DATABASE_URL'): Path(server.DB).parent.mkdir(parents=True,exist_ok=True)
    c = server.connect()
    try:
        with c:
            c.execute('DELETE FROM apartments')
            c.executemany('INSERT INTO apartments VALUES(?,?)',[(apt,json.dumps(v,ensure_ascii=False)) for apt,v in rows.items()])
            # Preserve explicit deactivations for retained contacts; remove departed contacts.
            for old in c.execute('SELECT phone,apt,role FROM memberships').fetchall():
                if (old['phone'],old['apt'],old['role']) not in grants: c.execute('DELETE FROM memberships WHERE phone=? AND apt=? AND role=?',(old['phone'],old['apt'],old['role']))
            c.executemany('INSERT INTO memberships(phone,apt,role) VALUES(?,?,?) ON CONFLICT(phone,apt,role) DO NOTHING',sorted(grants))
            c.execute('INSERT INTO summary VALUES(1,?) ON CONFLICT(id) DO UPDATE SET html=excluded.html',(html,))
            c.execute('DELETE FROM sessions WHERE phone NOT IN (SELECT phone FROM memberships WHERE active=1)')
        if not c.postgres: os.chmod(server.DB,0o600)
        return {'apartments':len(rows),'phone_apartment_roles':len(grants),'unique_phones':len({g[0] for g in grants}),'skipped_phone_fields':rejected}
    finally: c.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--full',required=True); p.add_argument('--tenants',required=True)
    args = p.parse_args()
    print(json.dumps(import_data(args.full,args.tenants)))
