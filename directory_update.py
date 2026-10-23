"""Merge an explicitly uploaded directory without touching financial or operational data."""
import json,re
FIELDS=('owner1','owner2','tenant1','tenant2','tenant3')
def tokens(name):
    return {t for word in re.findall(r'[\w]+',name.lower()) for t in (word,word[1:] if word.startswith('ו') and len(word)>2 else word)}
def normalized(name):return ' '.join(sorted(re.findall(r'[\w]+',str(name).lower())))
def permission_names(value,names):
    value=str(value or '').strip()
    if value in ('','-','אין'):return ''
    parts=re.split(r'[,;\n/&]+|\s+ו(?=[א-ת])',value)
    result=[]
    for part in parts:
        part=part.strip()
        if not part:continue
        match=[name for name in names if tokens(part)<=tokens(name)]
        resolved=match[0] if len(match)==1 else part
        if resolved not in result:result.append(resolved)
    return '\n'.join(result)
def merge(old,entry):
    owners=[];tenants=[]
    for prefix in FIELDS:
        name=str(entry.get(prefix+'Name') or '').strip()
        if name in ('','-','אין'):continue
        phone=str(entry.get(prefix+'Phone') or '').strip();mail=str(entry.get(prefix+'Email') or '').strip()
        if len(name)>160 or len(phone)>40 or len(mail)>254:raise ValueError('פרטי קשר ארוכים מדי')
        if mail and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',mail):mail=''
        contacts=old.get('ownerContacts',[])+old.get('tenantContacts',[])
        previous=[c for c in contacts if normalized(c.get('name',''))==normalized(name) or (phone not in ('','-') and re.sub(r'\D','',phone)==re.sub(r'\D','',str(c.get('phone',''))))]
        if len(previous)==1:
            if mail in ('','-'):mail=str(previous[0].get('email','') or '')
            if mail and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',mail):mail=''
            if phone in ('','-'):phone=previous[0].get('phone','')
        (owners if prefix.startswith('owner') else tenants).append({'name':name,'phone':'' if phone=='-' else phone,'email':'' if mail=='-' else mail})
    names=[c['name'] for c in owners+tenants]
    return dict(old,owners=[c['name'] for c in owners],tenants=[c['name'] for c in tenants],ownerContacts=owners,tenantContacts=tenants,access={key:permission_names(entry.get(field),names) for key,field in [('gym','gymAccess'),('pal','palAccess')]})
def apply(c,entries,email_validator):
    if not isinstance(entries,list) or not entries or len(entries)>100:raise ValueError('רשימת דירות לא תקינה')
    changes=[];seen=set();grants=set()
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('נתוני דירה לא תקינים')
        apt=int(entry.get('apt'));row=c.execute('SELECT payload FROM apartments WHERE apt=?',(apt,)).fetchone()
        if apt in seen or not row:raise ValueError('דירה חסרה או כפולה')
        seen.add(apt);old=json.loads(row['payload']);new=merge(old,entry)
        if not new['owners']:raise ValueError('לא צוינו בעלי דירה')
        for role,key in [('owner','ownerContacts'),('tenant','tenantContacts')]:
            for contact in new[key]:
                if contact['email']:
                    try:grants.add((email_validator(contact['email']),apt,role))
                    except ValueError:raise ValueError('כתובת מייל לא תקינה במאגר')
        changes.append((apt,new))
    with c.transaction(lock='directory-update'):
        for apt,data in changes:
            c.execute('UPDATE apartments SET payload=? WHERE apt=?',(json.dumps(data,ensure_ascii=False),apt))
    return {'ok':True,'apartments':len(changes),'contact_emails':len(grants)}
