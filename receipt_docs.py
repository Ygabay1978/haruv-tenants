"""Immutable receipt PDF rendering from the stored issue-time snapshot."""
from io import BytesIO
from pathlib import Path
import re
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from bidi.algorithm import get_display
pdfmetrics.registerFont(TTFont('Num','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('NumBold','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
W,H=A4
ink='#37271F';oak='#886342';line='#DDD1BF';muted='#756B60';green='#315F4C';cream='#F5EFE5'
months=['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר']
short=['ינו׳','פבר׳','מרץ','אפר׳','מאי','יוני','יולי','אוג׳','ספט׳','אוק׳','נוב׳','דצמ׳']
def render(e):
 d=e['snapshot'];apt=e['apt'];ev=d.get('electricVehicle') if e['kind']=='ev' else None
 stream=BytesIO();c=canvas.Canvas(stream,pagesize=A4,invariant=1);c.setTitle('קבלה '+e['number']);c.setAuthor('ועד הבית חרוב')
 def rect(x,y,w,h,fill=cream,stroke=None,r=8):
  c.setFillColor(HexColor(fill))
  c.setStrokeColor(HexColor(stroke or fill))
  c.roundRect(x,y,w,h,r,fill=1,stroke=bool(stroke))
 def txt(t,x,y,size=10,color=ink,bold=False,align='right'):
  c.setFillColor(HexColor(color));c.setFont('NumBold' if bold else 'Num',size)
  t=get_display(str(t))
  getattr(c,{'right':'drawRightString','left':'drawString','center':'drawCentredString'}[align])(x,y,t)
 def num(t,x,y,size=10,color=ink,bold=False,align='right'):
  c.setFillColor(HexColor(color));c.setFont('NumBold' if bold else 'Num',size)
  getattr(c,{'right':'drawRightString','left':'drawString','center':'drawCentredString'}[align])(x,y,str(t))
 def rule(y):
  c.setStrokeColor(HexColor(line));c.setLineWidth(.6);c.line(36,y,W-36,y)
 def chart(title,values,labels,x,y,w,h,unit,color):
  # y is bottom, labels under baseline; null is absent.
  txt(title,x+w,y+h+22,10,bold=True)
  maxv=max([v for v in values if v is not None] or [1])*1.20
  c.setLineWidth(.4)
  for n in range(3):
   gy=y+h*n/2
   c.setStrokeColor(HexColor(line));c.line(x,gy,x+w,gy)
   num(f'{maxv*n/2:,.0f}',x-5,gy-3,6,muted,align='right')
  step=w/12
  for i,v in enumerate(values):
   bx=x+w-(i+1)*step+step*.18
   if v is not None:
    c.setFillColor(HexColor(color));c.roundRect(bx,y,step*.64,max(1,h*v/maxv),2,fill=1,stroke=0)
    num(f'{v:g}',bx+step*.32,y+h*v/maxv+4,5.6,ink,align='center')
   else:
    num('-',bx+step*.32,y+5,7,muted,align='center')
   txt(labels[i],bx+step*.32,y-12,6,muted,align='center')
  txt(unit,x,y+h+22,7,muted,align='left')
 c.setFillColor(HexColor('#FFFFFF'));c.rect(0,0,W,H,fill=1,stroke=0)
 txt('בס״ד',W-36,H-23,7,muted)
 c.drawImage(str(Path(__file__).parent/'static/receipt-logo.png'),W-106,H-101,width=70,height=57,preserveAspectRatio=True,anchor='c')
 txt('ועד הבית ״חרוב״',W-123,H-57,18,bold=True);txt('שתולים 57, תל אביב',W-123,H-77,9,muted)
 txt('קבלה',36,H-57,18,bold=True,align='left');txt('שנת '+str(e['year']),36,H-77,8,muted,align='left');rule(H-112)
 rect(36,704,W-72,18,fill='#EEE0C9',r=3);txt('אישור קבלת תשלום לוועד הבית',W/2,710,8,oak,True,'center')
 def card(label,value,x,y,accent):
  width=(W-84)/2;rect(x,y,width,48,fill='#F5EFE5',r=5);rect(x,y+45,width,3,fill=accent,r=1)
  txt(label,x+width/2,y+31,8,muted,align='center');txt(value,x+width/2,y+11,10,bold=True,align='center')
 card('לכבוד',e['payer'],W/2+6,642,oak);card('מספר קבלה',e['number'],36,642,green)
 card('מועד התשלום',e['date'],W/2+6,584,oak);card('אמצעי התשלום',e['method'],36,584,green)
 # Dedicated information strip, outside the cards.
 contacts=d['tenantContacts'] if d['tenants'] else d['ownerContacts'];contact=next((v for v in contacts if v['name'] in e['payer']),contacts[0]);phone=contact.get('phone','');phone=phone if '@' not in phone else '';mail=contact.get('email','')
 rect(36,544,W-72,27,fill='#FAF6EF',r=3);txt(' | '.join(filter(None,[f'דירה {apt}',f'קומה {d["floor"]}',phone,mail])),W/2,554,8,muted,align='center')
 # One amount only; no balances or credit boxes.
 rect(36,471,W-72,60,fill='#F0E7D8',r=6)
 description=e['description']
 txt(description,W-50,509,10,bold=True);txt(e['reference'] or 'ללא אסמכתא בנקאית',W-50,489,8,muted)
 txt(f'{e["amount"]:,.2f} ש״ח',53,493,23,bold=True,align='left')
 txt('פירוט התשלומים בשנת '+str(e['year']),W-36,448,13,bold=True)
 txt(f'ועד בית שנרשם כשולם השנה: {d["paid"]:,.2f} ש״ח',36,449,8,muted,align='left')
 rect(36,415,W-72,22,fill='#E9DFD0',r=2)
 cols=[506,377,245,111] if ev else [475,300,110]
 heads=['חודש','ועד בית | ש״ח','טעינה | ש״ח','קוט״ש'] if ev else ['חודש','ועד בית | ש״ח','הערה']
 for t,x in zip(heads,cols):txt(t,x,423,8,bold=True,align='center')
 kwh=[]
 for i in range(12):
  y=400-i*14
  if i%2==0:rect(36,y-4,W-72,14,fill='#FAF6EF',r=0)
  txt(months[i],cols[0],y,8,bold=True,align='center');v=d['monthlyPayments'][i];num(f'{v:,.2f}',cols[1],y,8,green if v else '#B7312D',align='center')
  if ev:
   val=ev['months'][i];note=ev['monthNotes'][i] or '';m=re.match(r'\s*([\d.]+)',note);kw=float(m[1]) if m else None;kwh.append(kw)
   num(f'{val:.2f}' if val is not None else '-',cols[2],y,8,green if val is not None and not ev['monthUnpaid'][i] else muted,align='center');num(f'{kw:g}' if kw is not None else '-',cols[3],y,8,align='center')
  else:
   note='התשלום הנוכחי' if i+1 in e['months'] else '-';txt(note,cols[2],y,7,muted,align='center')
 chart('תשלומי ועד בית לפי חודש',d['monthlyPayments'],short,65,174,484,38,'ש״ח',oak)
 if ev:
  chart('חיובי טעינה לפי חודש',ev['months'],short,65,83,214,38,'ש״ח',green);chart('צריכת טעינה לפי חודש',kwh,short,335,83,214,38,'קוט״ש',green)
  txt('מיועד לבעלי הרכב בלבד, ללא העתק לבעלי הדירה.',W/2,49,8,muted,align='center')
  txt('יש להשלים תאריך, אמצעי תשלום ואסמכתא לפני הפקה רשמית.',W/2,35,7.5,oak,align='center')
 else:
  rect(36,77,W-72,65,fill='#F5EFE5',r=4)
  if not d['tenants']:
   txt('פרטי התשלום',W/2,123,9,bold=True,align='center');txt(e['note'],W/2,103,8,muted,align='center')
  else:
   owner=d['ownerContacts'][0];txt('העתק לבעלי הדירה',W/2,123,9,bold=True,align='center');txt(' | '.join(filter(None,[owner['name'],owner.get('phone'),owner.get('email')])),W/2,103,8,muted,align='center');txt(e['note'],W/2,87,8,muted,align='center')
  txt('סכומי החודשים משקפים את הרישום בכרטסת; סכום התקבול מוצג בראש המסמך.',W/2,51,7.5,muted,align='center')
 rule(25);txt('הופק ב-'+e['issueDate']+' · ועד הבית חרוב · שתולים 57 תל אביב',W/2,13,7,muted,align='center');c.save()
 return stream.getvalue()
