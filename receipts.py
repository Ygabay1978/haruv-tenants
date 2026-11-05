"""Receipt issuance ledger: fixed numbers, frozen PDFs and scoped downloads."""
import base64,hashlib,json,re,secrets,time
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
import receipt_docs

def ev_role(apt):return 'owner' if apt in (45,50) else 'tenant'
def permitted(kind,apt,roles):return kind=='dues' or 'committee' in roles or ev_role(apt) in roles

def metadata(row):
    p=json.loads(row['payload'])
    return {'id':row['id'],'number':row['number'],'kind':row['kind'],'months':p['months'],'year':p['year'],'amount':p['amount'],'paymentDate':p['date'],'issued':row['issued']}

def list_for(c,apt,roles):
    return [metadata(r) for r in c.execute('SELECT id,number,kind,payload,issued FROM receipts WHERE apt=? ORDER BY issued,number',(apt,)).fetchall() if permitted(r['kind'],apt,roles)]

def add_to(c,apt,roles,data):
    data['receiptFiles']=list_for(c,apt,roles)
    return data

def issue(c,body,issuer):
    apt=body.get('apt');year=body.get('year');months=body.get('months');kind=body.get('kind','dues')
    if type(apt) is not int or type(year) is not int or kind not in ('dues','ev'):raise ValueError('פרטי קבלה לא תקינים')
    if not isinstance(months,list) or not months or any(type(m) is not int or not 1<=m<=12 for m in months) or len(set(months))!=len(months):raise ValueError('יש לבחור חודשים תקינים')
    months=sorted(months)
    try:
        amount=Decimal(str(body.get('amount')))
        if not amount.is_finite() or amount<=0 or amount>1000000 or amount!=amount.quantize(Decimal('.01')):raise ValueError()
        paid_date=date.fromisoformat(body.get('paymentDate',''))
        if paid_date>datetime.now(ZoneInfo('Asia/Jerusalem')).date():raise ValueError()
    except (InvalidOperation,ValueError,TypeError):raise ValueError('סכום או תאריך תשלום לא תקינים')
    method=body.get('method');reference=str(body.get('reference','')).strip()
    if method not in ('מזומן','העברה בנקאית','הוראת קבע','צ׳ק'):raise ValueError('יש לבחור אמצעי תשלום')
    if len(reference)>100 or (method!='מזומן' and not reference):raise ValueError('יש להזין אסמכתא')
    with c.transaction(lock='receipt-issuance'):
        row=c.execute('SELECT payload FROM apartments WHERE apt=?',(apt,)).fetchone()
        if not row:raise ValueError('הדירה אינה קיימת')
        snapshot=json.loads(row['payload'])
        if year!=int(snapshot.get('year',2026)):raise ValueError('שנת הקבלה אינה תואמת לכרטסת')
        if kind=='ev':
            ev=snapshot.get('electricVehicle') or {}
            values=ev.get('months',[]);unpaid=ev.get('monthUnpaid',[])
            if any(m>len(values) or not isinstance(values[m-1],(int,float)) or m>len(unpaid) or unpaid[m-1] for m in months):raise ValueError('הטעינה אינה מסומנת כמשולמת')
        elif any(m>len(snapshot.get('monthlyPayments',[])) or not snapshot['monthlyPayments'][m-1] for m in months):raise ValueError('החודשים אינם מסומנים כמשולמים')
        source='bank:'+method+':'+reference+':'+paid_date.isoformat() if method!='מזומן' else f'cash:{apt}:{paid_date.isoformat()}:{amount}:{months}'
        source_key=hashlib.sha256(source.encode()).hexdigest()
        existing=c.execute('SELECT * FROM receipts WHERE source_key=?',(source_key,)).fetchone()
        if existing:
            p=json.loads(existing['payload'])
            if existing['apt']!=apt or p['amount']!=float(amount) or p['months']!=months or existing['kind']!=kind:raise ValueError('האסמכתא כבר משויכת לקבלה אחרת')
            return dict(metadata(existing),created=False)
        c.execute('INSERT INTO receipt_sequences(year,last_number) VALUES(?,0) ON CONFLICT(year) DO NOTHING',(year,))
        seq=c.execute('SELECT last_number FROM receipt_sequences WHERE year=?',(year,)).fetchone()['last_number']+1
        number=f'H-{year}-{seq:06d}'
        c.execute('UPDATE receipt_sequences SET last_number=? WHERE year=?',(seq,year))
        payer=str(body.get('payer','')).strip()
        if not payer or len(payer)>160:raise ValueError('יש לציין שם משלם')
        stamp=int(time.time());names=receipt_docs.months
        period=names[months[0]-1] if len(months)==1 else names[months[0]-1]+'–'+names[months[-1]-1]
        payload={'apt':apt,'year':year,'months':months,'kind':kind,'number':number,'amount':float(amount),'payer':payer,'date':paid_date.strftime('%d.%m.%Y'),'paymentDate':paid_date.isoformat(),'method':method,'reference':('אסמכתא: '+reference) if reference else 'ללא אסמכתא בנקאית','issueDate':datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%d.%m.%Y'),'description':('ועד בית' if kind=='dues' else 'טעינת רכב חשמלי')+' - '+period+' '+str(year),'note':paid_date.strftime('%d.%m.%Y')+' · '+method+(' · '+period if len(months)>1 else ''),'snapshot':snapshot,'issuer':issuer}
        pdf=receipt_docs.render(payload)
        ident=secrets.token_hex(16)
        c.execute('INSERT INTO receipts(id,number,apt,kind,source_key,payload,pdf,sha256,issued) VALUES(?,?,?,?,?,?,?,?,?)',(ident,number,apt,kind,source_key,json.dumps(payload,ensure_ascii=False),base64.b64encode(pdf).decode(),hashlib.sha256(pdf).hexdigest(),stamp))
        return {'id':ident,'number':number,'created':True}
