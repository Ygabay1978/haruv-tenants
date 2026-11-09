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

def _notice_recipient(snapshot,payer):
    """Resolve a named payer to one unshared resident account, or fail closed."""
    if not isinstance(snapshot,dict):return None
    normalize=lambda value:' '.join(str(value or '').split()).casefold()
    payer=normalize(payer)
    if not payer:return None
    contacts=set()
    for role,key in (('owner','ownerContacts'),('tenant','tenantContacts')):
        for contact in snapshot.get(key) or []:
            if isinstance(contact,dict):
                contacts.add((normalize(contact.get('name')),str(contact.get('email') or '').strip().lower(),role))
    matches=[entry for entry in contacts if entry[0]==payer]
    if len(matches)!=1 or not matches[0][1]:return None
    _,address,role=matches[0]
    if sum(entry[1]==address for entry in contacts)!=1:return None
    return address,role

def add_to(c,apt,roles,data,viewer_email=None):
    rows=c.execute('SELECT id,number,kind,payload,issued FROM receipts WHERE apt=? ORDER BY issued,number',(apt,)).fetchall()
    data['receiptFiles']=[]
    latest=rows[-1] if rows else None
    for row in rows:
        if not permitted(row['kind'],apt,roles):continue
        file=metadata(row)
        # The resident UI uses the issuance timestamp to select an alert.
        # Strip it from all other records; PDF access stays as before.
        file.pop('issued')
        if row is latest and viewer_email:
            payload=json.loads(row['payload']);payer=payload.get('payer')
            recipient=_notice_recipient(payload.get('snapshot'),payer)
            if recipient and recipient==_notice_recipient(data,payer) and roles==[recipient[1]] and viewer_email==recipient[0]:
                file['issued']=row['issued']
        data['receiptFiles'].append(file)
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
        existing=c.execute('SELECT * FROM receipts WHERE source_key=? OR id IN (SELECT receipt_id FROM receipt_revisions WHERE old_source_key=?)',(source_key,source_key)).fetchone()
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


def amend_reference(c,body,actor):
    ident=body.get('id');reference=body.get('reference');expected=body.get('expectedReference')
    if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{32}',ident) or not isinstance(reference,str) or not re.fullmatch(r'[0-9]{1,30}',reference):raise ValueError('יש להזין מספר אסמכתא בנקאית תקין')
    with c.transaction(lock='receipt-issuance'):
        row=c.execute('SELECT * FROM receipts WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('הקבלה לא נמצאה')
        payload=json.loads(row['payload']);new_reference='אסמכתא: '+reference
        if payload['reference']==new_reference:return dict(metadata(row),updated=False)
        if payload['reference']!=expected:raise ValueError('פרטי הקבלה השתנו. יש לרענן לפני העדכון')
        if payload['method']=='מזומן':raise ValueError('לא ניתן להוסיף אסמכתא בנקאית לקבלת מזומן')
        if hashlib.sha256(base64.b64decode(row['pdf'])).hexdigest()!=row['sha256']:raise ValueError('בדיקת תקינות הקבלה נכשלה')
        source='bank:'+payload['method']+':'+reference+':'+payload['paymentDate']
        source_key=hashlib.sha256(source.encode()).hexdigest()
        other=c.execute('SELECT id FROM receipts WHERE source_key=? OR id IN (SELECT receipt_id FROM receipt_revisions WHERE old_source_key=?)',(source_key,source_key)).fetchone()
        if other and other['id']!=ident:raise ValueError('האסמכתא משויכת לקבלה אחרת')
        payload['reference']=new_reference
        pdf=receipt_docs.render(payload)
        c.execute('INSERT INTO receipt_revisions VALUES(?,?,?,?,?,?,?,?,?)',(secrets.token_hex(16),ident,row['source_key'],row['payload'],row['pdf'],row['sha256'],int(time.time()),actor,new_reference))
        c.execute('UPDATE receipts SET source_key=?,payload=?,pdf=?,sha256=? WHERE id=?',(source_key,json.dumps(payload,ensure_ascii=False),base64.b64encode(pdf).decode(),hashlib.sha256(pdf).hexdigest(),ident))
        return {'id':ident,'number':row['number'],'updated':True,'reference':new_reference}
