const $=id=>document.getElementById(id);let address='',previewSelection=null,viewerContextLoaded=false;
const money=x=>new Intl.NumberFormat('he-IL',{style:'currency',currency:'ILS',minimumFractionDigits:2,maximumFractionDigits:2}).format(x||0);
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});let data=await r.json();if(!r.ok){const error=new Error(data.error||'אירעה שגיאה');error.status=r.status;throw error}return data}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':''}
function text(tag,value,parent){const e=document.createElement(tag);e.textContent=value;parent.appendChild(e);return e}
function clear(){previewSelection=null;viewerContextLoaded=false;$('viewer-controls').hidden=true;document.body.classList.add('login-mode');if($('access-dialog').open)$('access-dialog').close();$('access-detail').replaceChildren(); $('portal').hidden=true;$('help-contacts').replaceChildren();$('summary').removeAttribute('src');$('apartments').replaceChildren();$('login').hidden=false;$('code').value=''; }
function people(data,box){
  if(!Array.isArray(data.owners)&&!Array.isArray(data.tenants)) return;
  const group=document.createElement('div');group.className='people';
  for(const [label,key] of [['בעלי הדירה','owners'],['שוכרים','tenants']]){
    const names=Array.isArray(data[key])?data[key]:[];
    if(key==='tenants'&&!names.length) continue;
    const col=document.createElement('div');text('h3',label+': ',col);
    const contacts=Array.isArray(data[key==='owners'?'ownerContacts':'tenantContacts'])?data[key==='owners'?'ownerContacts':'tenantContacts']:[];
    for(const name of names){
      const person=document.createElement('div');person.className='person';const e=text('div',name,person);e.className='person-name';
      const contact=contacts.find(c=>c.name===name);
      if(contact){
        if(contact.phone&&contact.phone!=='-'){const phone=text('a',contact.phone,person);phone.href='tel:'+contact.phone.replace(/[^+0-9]/g,'');phone.className='person-contact';phone.dir='ltr'}
        if(contact.email&&contact.email!=='-'){const mail=text('a',contact.email,person);mail.href='mailto:'+contact.email;mail.className='person-contact';mail.dir='ltr'}
      }
      col.appendChild(person);
    }
    if(!names.length)text('div','טרם עודכן',col);
    group.appendChild(col);
  }
  box.appendChild(group);
}
function accessButtons(data,apt,box){
  const group=document.createElement('div');group.className='access-buttons';
  for(const [label,key,icon] of [['חדר כושר','gym','◇'],['PAL','pal','↗']]){
    const known=data.access&&typeof data.access[key]==='string';
    const names=known?data.access[key]:'';
    const button=document.createElement('button');button.type='button';button.className='access-button';
    const mark=text('span',icon,button);mark.className='access-icon';mark.setAttribute('aria-hidden','true');
    const copy=document.createElement('span');copy.className='access-copy';text('strong',label,copy);
    text('small',known?(names?'הרשאה רשומה':'לא רשומה הרשאה'):'פרטי ההרשאה טרם נטענו',copy);button.appendChild(copy);
    const arrow=text('span','←',button);arrow.className='access-arrow';arrow.setAttribute('aria-hidden','true');
    button.setAttribute('aria-haspopup','dialog');
    button.onclick=()=>{
      $('access-title').textContent=label+' · דירה '+apt;
      const detail=$('access-detail');detail.replaceChildren();
      text('p',names?'השמות הרשומים במאגר ההרשאות:':known?'לא רשומה הרשאה לדירה זו במאגר. לבירור ולעדכון פנו לוועד הבית.':'פרטי ההרשאה טרם נטענו. פנו לוועד הבית.',detail);
      if(names){const line=text('div',names,detail);line.className='permission-names'}
      $('access-dialog').showModal();
    };
    group.appendChild(button);
  }
  box.appendChild(group);
}
const monthsHE=['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר'];
function unitDetails(data,box){
  const grid=document.createElement('dl');grid.className='unit-details';
  for(const [label,key] of [['קומה','floor'],['חדרים','rooms'],['חניה','parking'],['מחסן','storage']]){
    const cell=document.createElement('div');text('dt',label,cell);text('dd',data[key]===null||data[key]===undefined||data[key]===''?'לא רשום במאגר':String(data[key]),cell);grid.appendChild(cell)
  }
  const evCell=document.createElement('div');text('dt','בעל רכב חשמלי',evCell);text('dd',data.electricVehicle?'כן':'לא',evCell);grid.appendChild(evCell);box.appendChild(grid);
}
function notices(items,box){
  if(!items||!items.length)return;
  const section=document.createElement('section');section.className='notices';text('h3','עדכונים מוועד הבית',section);
  for(const n of items){const card=document.createElement('article');card.className='notice';text('small',n.kind==='note'?'הערה לדירה':'הודעה',card);text('h4',n.title,card);text('p',n.body,card);for(const attachment of n.attachments||[]){const link=text('a',attachment.filename,card);link.href='/api/attachments/'+attachment.id;link.target='_blank';link.rel='noopener';link.className='notice-attachment';if(attachment.mime.startsWith('image/')){const img=document.createElement('img');img.src=link.href;img.alt=attachment.filename;img.loading='lazy';link.prepend(img)}}section.appendChild(card)}box.appendChild(section);
}
function collectionWarning(data,box){
  const c=data.collection;if(!c||!c.level)return;
  const warning=document.createElement('div');warning.className='collection-alert '+c.level;warning.setAttribute('role','status');
  text('strong',c.level==='legal'?'התראת גבייה — חוב מעל שלושה חודשים':'התראת גבייה — נדרש תשלום',warning);
  text('p',c.level==='legal'?'נדרש להסדיר את החוב בהקדם. אי־הסדרת החוב עלולה להביא לנקיטת הליכי גבייה משפטיים.':'החוב עולה על שני חודשי תשלום. נא להסדיר את התשלום מול ועד הבית.',warning);
  text('small','חוב שהגיע מועדו: '+money(c.amount)+' · עד '+monthsHE[c.throughMonth-1]+' '+c.year+' · ללא חודשים עתידיים',warning);box.appendChild(warning);
}
function evDetails(ev,box){
  if(!ev)return;
  const notes=ev.sourceNotes||[];if(!ev.holder&&!notes.length)return;
  const section=document.createElement('div');section.className='ev-details compact-ev';
  if(ev.holder)text('small','רישום עמדת הטעינה: '+ev.holder,section);
  for(const note of notes)text('small',note,section);box.appendChild(section);
}
function help(contacts){
 for(const [container,section] of [['help-contacts','help-section'],['login-help-contacts','login-support']]){
  const parent=$(container);parent.replaceChildren();
  for(const c of contacts||[]){const card=document.createElement('div');card.className='help-contact';text('strong',c.name,card);text('p',c.topics,card);const phone=text('a',c.phone.replace(/^(052)([0-9]{7})$/,'$1-$2'),card);phone.href='tel:'+c.phone.replace(/[^+0-9]/g,'');phone.dir='ltr';parent.appendChild(card)}$(section).hidden=!parent.children.length;
 }
}
async function load(){
  const result=previewSelection?await api('/api/preview',previewSelection):await api('/api/apartments');if(/^[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get('dashboard')||'')){location.replace('/dashboard-connect?state='+new URLSearchParams(location.search).get('dashboard'));return}if(new URLSearchParams(location.search).get('admin')==='1'){const apt=new URLSearchParams(location.search).get('apt');location.replace('/admin'+(/^[0-9]{1,3}$/.test(apt||'')?'?apt='+apt:'')+(['note','message'].includes(new URLSearchParams(location.search).get('kind'))?(/^[0-9]{1,3}$/.test(apt||'')?'&':'?')+'kind='+new URLSearchParams(location.search).get('kind'):''));return}$('apartments').replaceChildren();
  help(result.apartments[0]?.data.support||[]);
  $('viewer-controls').hidden=!result.canPreview;
  if(result.canPreview&&!viewerContextLoaded){const context=await api('/api/viewer/context');const select=$('viewer-apt');select.replaceChildren();for(const a of context.apartments){const option=text('option','דירה '+a.apt+' · '+[...a.owners,...a.tenants].join(' / '),select);option.value=a.apt}viewerContextLoaded=true;const own=result.apartments[0];if(own)select.value=own.apt}
  $('viewer-status').textContent=result.preview?'תצוגה מקדימה בלבד · דירה '+result.preview.apt+' · '+({owner:'בעל/ת דירה',tenant:'שוכר/ת',committee:'ועד הבית — כרטיס מלא'}[result.preview.role]):'';
  for(const a of result.apartments){
    const box=document.createElement('article');box.className='apartment';
    const top=document.createElement('div');top.className='apartment-top';
    text('h2','דירה '+a.apt,top);
    const role=text('span',a.roles.map(r=>({owner:'בעל/ת דירה',tenant:'שוכר/ת',committee:'ועד הבית — צפייה בדירה'}[r]||r)).join(' · '),top);role.className='role-tag';box.appendChild(top);
    notices(a.notices,box);
    collectionWarning(a.data,box);
    unitDetails(a.data,box);
    people(a.data,box);
    accessButtons(a.data,a.apt,box);
    const metrics=document.createElement('div');metrics.className='metrics';
    for(const [label,key] of [['תשלום חודשי','monthly'],['שולם השנה','paid'],['יתרה שנתית לתשלום','due']]){
      const m=document.createElement('div');m.className='metric';text('span',label,m);text('strong',money(a.data[key]),m);metrics.appendChild(m)
    }
    box.appendChild(metrics);
    const detail=document.createElement('details');detail.open=true;text('summary','פירוט תשלומים חודשי',detail);
    const table=document.createElement('table');table.className='payment-table';const head=document.createElement('thead');const row=document.createElement('tr');const ev=a.data.electricVehicle;
    ['חודש','שולם ועד בית',...(ev?['רכב חשמלי']:[]),'מספר קבלה'].forEach(v=>text('th',v,row));head.appendChild(row);table.appendChild(head);const body=document.createElement('tbody');
    (a.data.monthlyPayments||[]).forEach((v,i)=>{
      const r=document.createElement('tr');const month=text('th',monthsHE[i],r);month.scope='row';const amount=text('td',money(v),r);amount.className=Number(v)>0?'paid':'unpaid';
      if(ev){const value=(ev.months||[])[i];const cell=text('td',value===null||value===undefined?'—':money(value),r);if(value!==null&&value!==undefined){const unpaid=!!(ev.monthUnpaid||[])[i];cell.className=unpaid?'unpaid':'paid';cell.classList.add('ev-payment')}const note=(ev.monthNotes||[])[i];if(note){cell.classList.add('ev-payment');text('span',note,cell,'ev-consumption')}}
      const receipt=(a.data.monthlyReceipts||[])[i];const receiptCell=text('td',receipt||'—',r);receiptCell.className='receipt-number';body.appendChild(r)
    });
    table.appendChild(body);const scroll=document.createElement('div');scroll.className='payment-scroll';scroll.appendChild(table);detail.appendChild(scroll);box.appendChild(detail);evDetails(a.data.electricVehicle,box);$('apartments').appendChild(box)
  }
  if(!$('summary').getAttribute('src'))$('summary').src='/api/summary';
  document.body.classList.remove('login-mode');$('login').hidden=true;$('portal').hidden=false;message('')
}
async function busy(form,action){const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);try{await action()}catch(e){message(e.message,true)}finally{buttons.forEach(b=>b.disabled=false)}}
async function selectApartment(){
 const fields=[$('viewer-apt'),$('viewer-role')];fields.forEach(f=>f.disabled=true);
 try{previewSelection={apt:Number($('viewer-apt').value),role:$('viewer-role').value};await load()}catch(e){message(e.message,true)}finally{fields.forEach(f=>f.disabled=false)}
}
$('viewer-form').onsubmit=e=>e.preventDefault();$('viewer-apt').onchange=selectApartment;$('viewer-role').onchange=selectApartment;
window.addEventListener('message',event=>{if(event.source!==$('summary').contentWindow||event.data?.type!=='haruv-summary-height')return;const height=Number(event.data.height);if(Number.isFinite(height)&&height>=300&&height<=6000)$('summary').style.height=height+'px'});
$('email-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{address=$('email').value;const r=await api('/api/send-code',{email:address});message(r.message);$('email-form').hidden=true;$('code-form').hidden=false;$('code').focus()})};
$('code-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{await api('/api/verify-code',{email:address,code:$('code').value});await load()})};
$('back').onclick=()=>{$('code-form').hidden=true;$('email-form').hidden=false;$('code').value='';message('')};
$('logout').onclick=async()=>{try{await api('/api/logout',{})}finally{clear();$('back').click()}};
api('/api/support').then(r=>help(r.contacts)).catch(()=>{});
load().catch(()=>clear());
setInterval(async()=>{if(!$('portal').hidden){try{await load()}catch(e){clear();message('יש להתחבר מחדש',true)}}},60000);

document.querySelectorAll('.building-photo').forEach(img=>img.addEventListener('error',()=>{img.hidden=true}));
