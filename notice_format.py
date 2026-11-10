"""Validate rich notice markup and keep existing plain notices readable."""
import re
from html import escape
from html.parser import HTMLParser
import json

PREFIX='\x1eHARUV_RICH_V1:'
TAGS=set('p div br strong b em i u s strike ul ol li blockquote span h2 h3'.split())
FONTS={'arial':'Arial,sans-serif','georgia':'Georgia,serif','tahoma':'Tahoma,sans-serif','verdana':'Verdana,sans-serif','times new roman':'Times New Roman,serif'}
SIZES={str(n)+'px' for n in (12,14,16,18,20,24,28,32)}

def color(v):
    if re.fullmatch(r'#[a-f0-9]{6}',v):return v
    m=re.fullmatch(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)',v)
    if m and all(int(x)<=255 for x in m.groups()):return '#'+''.join(f'{int(x):02x}' for x in m.groups())

def styles(raw):
    safe={}
    for pair in raw.split(';'):
        key,sep,val=pair.partition(':')
        if not sep:continue
        key=key.strip().lower();val=val.strip().lower()
        if key in ('color','background-color'):val=color(val)
        elif key=='font-family':val=FONTS.get(val.split(',')[0].strip().strip('\"\''))
        elif key=='font-size':val=val if val in SIZES else None
        elif key=='text-align':val=val if val in ('right','left','center','justify') else None
        elif key=='font-weight':val=val if val in ('bold','normal','700','400') else None
        elif key=='font-style':val=val if val in ('italic','normal') else None
        elif key=='text-decoration':val=val if val in ('underline','line-through','none') else None
        else:val=None
        if val:safe[key]=val
    return ';'.join(k+':'+v for k,v in sorted(safe.items()))

class Clean(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.out=[];self.stack=[];self.skip=[]
    def handle_starttag(self,tag,attrs):
        if self.skip or tag in ('script','style','iframe','svg','math','object','template'):
            if tag in ('script','style','iframe','svg','math','object','template'):self.skip.append(tag)
            return
        if tag not in TAGS or len(self.stack)>40:return
        raw=dict(attrs).get('style') or ''
        css=styles(raw)
        self.out.append('<'+tag+(' style="'+escape(css,quote=True)+'"' if css else '')+'>')
        if tag!='br':self.stack.append(tag)
    def handle_endtag(self,tag):
        if self.skip:
            if tag==self.skip[-1]:self.skip.pop()
            return
        if tag in self.stack:
            while self.stack:
                top=self.stack.pop();self.out.append('</'+top+'>')
                if top==tag:break
    def handle_data(self,data):
        if not self.skip:self.out.append(escape(data,quote=False))
    def finish(self):
        self.close()
        return ''.join(self.out)+''.join('</'+t+'>' for t in reversed(self.stack))

def sanitize(markup):
    if not isinstance(markup,str) or len(markup)>24000:raise ValueError('עיצוב ההודעה ארוך מדי')
    parser=Clean();parser.feed(markup);return parser.finish()

def pack(body,markup):
    return PREFIX+json.dumps([body,sanitize(markup)],ensure_ascii=False,separators=(',',':')) if markup else body

def fields(body):
    if body.startswith(PREFIX):
        try:
            plain,markup=json.loads(body[len(PREFIX):])
            if isinstance(plain,str):return {'body':plain,'body_html':sanitize(markup)}
        except (ValueError,TypeError):pass
    return {'body':body}

def public(row):
    return {**dict(row),**fields(row['body'])}
