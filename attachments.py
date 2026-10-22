"""Private, bounded note attachments; never serve active web content."""
import base64,io,zipfile,re
from pathlib import PurePath
MAX_FILE=5*1024*1024
MAX_NOTICE=15*1024*1024
TYPES={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.pdf':'application/pdf','.txt':'text/plain','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
def decode(body):
    name=str(body.get('filename','')).replace('\\','/').split('/')[-1].strip()
    if not name or len(name)>120 or any(ord(c)<32 for c in name):raise ValueError('שם קובץ לא תקין')
    ext=PurePath(name).suffix.lower();mime=TYPES.get(ext)
    if not mime:raise ValueError('אפשר לצרף תמונות, PDF, Word, Excel, PowerPoint או טקסט')
    value=body.get('data')
    if not isinstance(value,str) or len(value)>MAX_FILE*4//3+8:raise ValueError('גודל הקובץ המרבי הוא 5 MB')
    try:raw=base64.b64decode(value,validate=True)
    except Exception:raise ValueError('הקובץ לא נקרא כראוי')
    if not raw or len(raw)>MAX_FILE:raise ValueError('גודל הקובץ המרבי הוא 5 MB')
    valid=True
    if ext in ('.jpg','.jpeg'):valid=raw.startswith(b'\xff\xd8\xff')
    elif ext=='.png':valid=raw.startswith(b'\x89PNG\r\n\x1a\n')
    elif ext=='.webp':valid=raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'
    elif ext=='.pdf':valid=raw.startswith(b'%PDF-')
    elif ext=='.txt':
        try:raw.decode('utf-8')
        except UnicodeDecodeError:valid=False
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names=z.namelist();folder={'.docx':'word/','.xlsx':'xl/','.pptx':'ppt/'}[ext]
                valid='[Content_Types].xml' in names and any(n.startswith(folder) for n in names) and not any(n.lower().endswith('vbaproject.bin') for n in names) and sum(i.file_size for i in z.infolist())<100*1024*1024 and len(names)<3000
        except (zipfile.BadZipFile,OSError):valid=False
    if not valid:raise ValueError('תוכן הקובץ אינו תואם לסוג שנבחר')
    return name,mime,raw

def list_for(c,ident):
    return [dict(r) for r in c.execute('SELECT id,filename,mime,size FROM notice_attachments WHERE notice_id=? ORDER BY created,id',(ident,)).fetchall()]

def validate_selection(c,ids,ident=None):
    if not isinstance(ids,list) or len(ids)>5 or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids):raise ValueError('אפשר לצרף עד 5 קבצים')
    total=0
    for value in ids:
        if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{32}',value):raise ValueError('מזהה קובץ לא תקין')
        row=c.execute('SELECT notice_id,size FROM notice_attachments WHERE id=?',(value,)).fetchone()
        if not row or row['notice_id'] not in (None,ident):raise ValueError('הקובץ אינו זמין להודעה זו')
        total+=row['size']
    if total>MAX_NOTICE:raise ValueError('סך הקבצים בהודעה מוגבל ל־15 MB')
    return ids

def bind(c,ident,ids):
    current=list_for(c,ident)
    for old in current:
        if old['id'] not in ids:c.execute('UPDATE notice_attachments SET notice_id=NULL WHERE id=?',(old['id'],))
    for value in ids:
        if c.execute('UPDATE notice_attachments SET notice_id=? WHERE id=? AND (notice_id IS NULL OR notice_id=?)',(ident,value,ident)).rowcount!=1:raise ValueError('Attachment is already in use')
