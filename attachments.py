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

def office_text(raw,mime):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist()
        def xml(name):
            if z.getinfo(name).file_size>2_000_000:raise ValueError('Preview too large')
            data=z.read(name)
            if b'<!doctype' in data.lower() or b'<!entity' in data.lower() or b'\x00' in data:raise ValueError('Unsupported XML')
            return ET.fromstring(data)
        def tag(e):return e.tag.rsplit('}',1)[-1]
        def text(e):return ''.join(n.text or '' for n in e.iter() if tag(n)=='t')
        if mime==TYPES['.docx']:
            out='\n'.join(text(e) for e in xml('word/document.xml').iter() if tag(e)=='p')
        elif mime==TYPES['.pptx']:
            slides=sorted((n for n in names if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml',n)),key=lambda n:int(re.search(r'(\d+)\.xml$',n)[1]))[:20]
            out='\n\n'.join(f'שקופית {i+1}\n'+'\n'.join(text(e) for e in xml(n).iter() if tag(e)=='p') for i,n in enumerate(slides))
        else:
            shared=[text(e) for e in xml('xl/sharedStrings.xml') if tag(e)=='si'] if 'xl/sharedStrings.xml' in names else []
            sheets=sorted((n for n in names if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml',n)),key=lambda n:int(re.search(r'(\d+)\.xml$',n)[1]))[:10]
            def cell(c):
                v=next((e.text or '' for e in c if tag(e)=='v'),'')
                if c.get('t')=='s' and v.isdigit() and int(v)<len(shared):return shared[int(v)]
                return text(c) if c.get('t')=='inlineStr' else v
            out='\n\n'.join(f'גיליון {i+1}\n'+'\n'.join(' | '.join(cell(c) for c in row if tag(c)=='c') for row in [e for e in xml(n).iter() if tag(e)=='row'][:100]) for i,n in enumerate(sheets))
        return out.strip()[:18000]

def pdf_preview(raw,requested):
    import pypdfium2 as pdfium
    # Imported lazily so uploads and downloads do not depend on the renderer.
    with _preview_lock:
        document=pdfium.PdfDocument(raw)
        try:
            total=len(document)
            if not total:raise ValueError('Empty PDF')
            index=min(max(1,requested),total)
            page=document[index-1]
            try:
                w,h=page.get_size()
                if min(w,h)<=0:raise ValueError('Invalid page size')
                bitmap=page.render(scale=min(2,1550/max(w,h)))
                try:
                    stream=io.BytesIO();bitmap.to_pil().convert('RGB').save(stream,format='JPEG',quality=87)
                    return index,total,base64.b64encode(stream.getvalue()).decode('ascii')
                finally:bitmap.close()
            finally:page.close()
        finally:document.close()

from threading import Lock
_preview_lock=Lock()

def preview_html(raw,filename,mime,url,page=1):
    from html import escape
    name=escape(filename);url=escape(url,quote=True)
    nav='';heading=''
    try:
        if mime=='application/pdf':
            index,total,image=pdf_preview(raw,page)
            content=f'<img alt="עמוד {index} מתוך {total}" src="data:image/jpeg;base64,{image}">'
            nav=(f'<a href="?page={index-1}">עמוד קודם</a>' if index>1 else '')+f'<span>עמוד {index} מתוך {total}</span>'+(f'<a href="?page={index+1}">עמוד הבא</a>' if index<total else '')
        elif mime.startswith('image/'):
            content=f'<img alt="{name}" src="data:{mime};base64,{base64.b64encode(raw).decode("ascii")}">'
        else:
            if mime=='text/plain':plain=raw.decode('utf-8')[:18000]
            else:
                plain=office_text(raw,mime)
                heading='<p>תצוגה מקדימה של תוכן המסמך. להעתק המלא, כולל העיצוב, הורידו את הקובץ.</p>'
            if not plain.strip():raise ValueError('Empty preview')
            content='<pre dir="auto">'+escape(plain)+'</pre>'
    except Exception:
        content='<p>לא ניתן להציג תצוגה מקדימה לקובץ הזה. אפשר להוריד את המקור באמצעות הכפתור למעלה.</p>'
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>צפייה בקובץ · {name}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f6f0e7;color:#38291e;font:16px Arial,sans-serif}}header{{position:sticky;top:0;padding:12px;background:#fffaf3;border-bottom:1px solid #d8c5a8;text-align:center}}h1{{font-size:19px;overflow-wrap:anywhere;margin:0 0 8px}}nav{{display:flex;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap}}a{{display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;color:white;background:#60452f;border-radius:7px;text-decoration:none;font-weight:bold}}main{{max-width:950px;margin:auto;padding:12px;text-align:center}}img{{display:block;max-width:100%;height:auto;margin:auto}}pre{{text-align:start;white-space:pre-wrap;overflow-wrap:anywhere;padding:14px;background:white;font:inherit;line-height:1.6}}</style>
</head><body><header><h1><bdi>{name}</bdi></h1><nav aria-label="אפשרויות צפייה">{nav}<a href="{url}/download" download>הורדת הקובץ</a></nav></header><main>{heading}{content}</main></body></html>'''
