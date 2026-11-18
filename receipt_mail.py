"""Idempotent payer-only email notifications for issued receipts."""
import json,time,uuid
import notice_mail,receipts

def recipient(c,row):
    frozen=json.loads(row['payload'])
    target=receipts._notice_recipient(frozen.get('snapshot'),frozen.get('payer'))
    current=c.execute('SELECT payload FROM apartments WHERE apt=?',(row['apt'],)).fetchone()
    if not target or not current:return None
    if target!=receipts._notice_recipient(json.loads(current['payload']),frozen.get('payer')):return None
    address,role=target
    if not receipts.permitted(row['kind'],row['apt'],[role]):return None
    membership=c.execute('SELECT 1 FROM email_memberships WHERE apt=? AND email=? AND role=? AND active=1',
        (row['apt'],address,role)).fetchone()
    return address if membership else None

def latest(c,ident):
    row=c.execute('SELECT state,updated FROM receipt_notifications WHERE receipt_id=?',(ident,)).fetchone()
    if not row:return None
    result=dict(row)
    if result['state']=='sending' and result['updated']<int(time.time())-60:result['state']='unknown'
    return result

def deliver(c,ident,sender):
    with c.transaction(lock='receipt-email:'+ident):
        row=c.execute('SELECT * FROM receipts WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('הקבלה לא נמצאה')
        old=c.execute('SELECT state FROM receipt_notifications WHERE receipt_id=?',(ident,)).fetchone()
        if old and old['state'] not in ('failed','pending'):return latest(c,ident)
        address=recipient(c,row)
        if not address:return {'state':'recipient_unresolved','recipients':0}
        stamp=int(time.time())
        c.execute("""INSERT INTO receipt_notifications(receipt_id,state,updated) VALUES(?,'sending',?)
            ON CONFLICT(receipt_id) DO UPDATE SET state='sending',updated=excluded.updated""",(ident,stamp))
    key=str(uuid.uuid5(uuid.NAMESPACE_URL,'haruv:receipt-email:'+ident))
    body='קבלה על התשלום שלך מחכה לך בפורטל הדיירים. לאחר ההתחברות ניתן לצפות בקבלה או להוריד אותה.'
    state='accepted'
    try:
        sender({'title':'קבלה על התשלום שלך מחכה לך בפורטל','body':body,'email_only':True},[address],key)
    except notice_mail.Rejected:state='failed'
    except Exception:state='unknown'
    c.execute('UPDATE receipt_notifications SET state=?,updated=? WHERE receipt_id=?',(state,int(time.time()),ident))
    c.commit()
    return {'state':state,'recipients':1}

def issue(c,body,issuer,sender):
    result=receipts.issue(c,body,issuer)
    try:result['notification']=deliver(c,result['id'],sender)
    except Exception:result['notification']={'state':'unknown','recipients':0}
    return result
