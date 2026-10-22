"""Resident scoping, collection warning calculation and notice validation."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json,math

def collection_status(data, now=None):
    now=now or datetime.now(ZoneInfo('Asia/Jerusalem'))
    year=int(data.get('year',2026));months=0 if now.year<year else 12 if now.year>year else now.month
    monthly=float(data.get('monthly') or 0)
    payments=data.get('monthlyPayments') or []
    arrears=max(0,monthly*months-sum(float(v or 0) for v in payments[:months]))
    if data.get('due') is not None:arrears=min(arrears,max(0,float(data['due'])))
    level='legal' if monthly>0 and arrears>monthly*3+0.01 else 'payment' if monthly>0 and arrears>monthly*2+0.01 else None
    return {'level':level,'amount':round(arrears,2),'throughMonth':months,'year':year}

def resident_payload(raw):
    data=json.loads(raw)
    keys=('year','monthly','annual','paid','due','monthlyPayments','owners','tenants','ownerContacts','tenantContacts','access','floor','rooms','parking','storage','electricVehicle','support','monthlyReceipts')
    result={k:data[k] for k in keys if k in data}
    if 'monthlyReceipts' in result:result['monthlyReceipts']=[str(v)[:80] if v is not None else '' for v in result['monthlyReceipts'][:12]] if isinstance(result['monthlyReceipts'],list) else []
    result['collection']=collection_status(result)
    return result

def notice_input(body,c):
    kind=body.get('kind','message');audience=body.get('audience','all');apt=body.get('apt')
    if kind not in ('note','message') or audience not in ('all','owner','tenant'):raise ValueError()
    if apt in ('',None):apt=None
    else:
        if isinstance(apt,bool) or not str(apt).isdigit():raise ValueError()
        apt=int(apt)
        if not c.execute('SELECT 1 FROM apartments WHERE apt=?',(apt,)).fetchone():raise ValueError()
    title=str(body.get('title','')).strip();text=str(body.get('body','')).strip()
    if not title or not text or len(title)>120 or len(text)>3000:raise ValueError()
    active=body.get('active',1)
    if active not in (0,1) or isinstance(active,str):raise ValueError()
    return apt,audience,kind,title,text,int(active)
