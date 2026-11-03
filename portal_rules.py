"""Resident scoping, collection warning calculation and notice validation."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json,math,re

def collection_status(data, now=None):
    now=now or datetime.now(ZoneInfo('Asia/Jerusalem'))
    year=int(data.get('year',2026));months=0 if now.year<year else 12 if now.year>year else now.month
    monthly=float(data.get('monthly') or 0)
    payments=data.get('monthlyPayments') or []
    arrears=max(0,monthly*months-sum(float(v or 0) for v in payments[:months]))
    if data.get('due') is not None:arrears=min(arrears,max(0,float(data['due'])))
    level='legal' if monthly>0 and arrears>monthly*3+0.01 else 'payment' if monthly>0 and arrears>monthly*2+0.01 else None
    return {'level':level,'amount':round(arrears,2),'throughMonth':months,'year':year}

def resident_payload(raw, apt, roles):
    data=json.loads(raw)
    keys=('year','monthly','annual','paid','due','monthlyPayments','owners','tenants','ownerContacts','tenantContacts','access','floor','rooms','parking','storage','electricVehicle','support','monthlyReceipts','paymentNotes','solarRepairDue')
    result={k:data[k] for k in keys if k in data}
    if 'monthlyReceipts' in result:result['monthlyReceipts']=[str(v)[:80] if v is not None else '' for v in result['monthlyReceipts'][:12]] if isinstance(result['monthlyReceipts'],list) else []
    required_role='owner' if apt in (45,50) else 'tenant'
    result['canViewElectricVehicle']=required_role in roles
    if not result['canViewElectricVehicle']:result.pop('electricVehicle',None)
    result['collection']=collection_status(result)
    return result

def ev_monthly_average(ev, limit):
    if not isinstance(ev,dict):return None
    months=(ev.get('months') or [])[:limit]
    notes=(ev.get('monthNotes') or [])[:limit]
    def positive(v):
        return type(v) in (int,float) and math.isfinite(v) and v>0
    last_charge=max((i for i,v in enumerate(months) if positive(v)),default=-1)
    last_sale=max((i for i,v in enumerate(notes) if re.search('מכר.*רכב',str(v or ''))),default=-1)
    if last_sale>=0 and last_sale>=last_charge:return None
    active=[]
    for amount,note in zip(months,notes):
        if not positive(amount):continue
        match=re.fullmatch(r"""([0-9,]+(?:[.][0-9]+)?)[\s]*(?:קוט["״”׳']?ש)?""",str(note or '').strip())
        if not match:continue
        try:kwh=float(match[1].replace(',',''))
        except ValueError:continue
        if positive(kwh):active.append((kwh,amount))
    if not active:return None
    count=ev.get('averagingMonths')
    if type(count) is not int or not len(active)<=count<=12:count=len(active)
    return tuple(sum(col)/count for col in zip(*active))

def add_ev_benchmark(c, apt, data):
    ev=data.get('electricVehicle')
    if not ev or not data['canViewElectricVehicle']:return data
    period=data['collection']
    averages=[]
    for row in c.execute('SELECT payload FROM apartments WHERE apt<>?',(apt,)).fetchall():
        other=json.loads(row['payload'])
        if int(other.get('year',2026))!=period['year']:continue
        average=ev_monthly_average(other.get('electricVehicle'),period['throughMonth'])
        if average is not None:averages.append(average)
    if len(averages)>=3:
        data['electricVehicle']={**ev,'peerAverage':{
            key:round(sum(values)/len(averages),2)
            for key,values in zip(('kwh','amount'),zip(*averages))
        }}
    return data

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
