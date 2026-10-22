const $=id=>document.getElementById(id);let address='';
const money=x=>new Intl.NumberFormat('he-IL',{style:'currency',currency:'ILS',maximumFractionDigits:2}).format(x||0);
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});let data=await r.json();if(!r.ok){const error=new Error(data.error||'אירעה שגיאה');error.status=r.status;throw error}return data}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':''}
function text(tag,value,parent){const e=document.createElement(tag);e.textContent=value;parent.appendChild(e);return e}
function clear(){if($('access-dialog').open)$('access-dialog').close();$('access-detail').replaceChildren(); $('portal').hidden=true;$('summary').removeAttribute('src');$('apartments').replaceChildren();$('login').hidden=false;$('code').value=''; }
function people(data,box){
  if(!Array.isArray(data.owners)&&!Array.isArray(data.tenants)) return;
  const group=document.createElement('div');group.className='people';
  for(const [label,key] of [['בעלי הדירה','owners'],['שוכרים','tenants']]){
    const names=Array.isArray(data[key])?data[key]:[];
    if(key==='tenants'&&!names.length) continue;
    const col=document.createElement('div');text('h3',label,col);
    for(const name of names){const e=text('div',name,col);e.className='person-name'}
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
async function load(){
  const result=await api('/api/apartments');$('apartments').replaceChildren();
  for(const a of result.apartments){
    const box=document.createElement('article');box.className='apartment';
    const top=document.createElement('div');top.className='apartment-top';
    text('h2','דירה '+a.apt,top);
    const role=text('span',a.roles.map(r=>r==='owner'?'בעל/ת דירה':'שוכר/ת').join(' · '),top);role.className='role-tag';box.appendChild(top);
    people(a.data,box);
    accessButtons(a.data,a.apt,box);
    const metrics=document.createElement('div');metrics.className='metrics';
    for(const [label,key] of [['תשלום חודשי','monthly'],['שולם השנה','paid'],['יתרה שנתית לתשלום','due']]){
      const m=document.createElement('div');m.className='metric';text('span',label,m);text('strong',money(a.data[key]),m);metrics.appendChild(m)
    }
    box.appendChild(metrics);
    const detail=document.createElement('details');detail.open=true;text('summary','פירוט תשלומים חודשי',detail);
    const table=document.createElement('table');const head=document.createElement('thead');const row=document.createElement('tr');
    ['חודש','שולם'].forEach(v=>text('th',v,row));head.appendChild(row);table.appendChild(head);const body=document.createElement('tbody');
    (a.data.monthlyPayments||[]).forEach((v,i)=>{const r=document.createElement('tr');text('td',['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר'][i],r);text('td',money(v),r);body.appendChild(r)});
    table.appendChild(body);detail.appendChild(table);box.appendChild(detail);$('apartments').appendChild(box)
  }
  if(!$('summary').getAttribute('src'))$('summary').src='/api/summary';
  $('login').hidden=true;$('portal').hidden=false;message('')
}
async function busy(form,action){const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);try{await action()}catch(e){message(e.message,true)}finally{buttons.forEach(b=>b.disabled=false)}}
$('email-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{address=$('email').value;const r=await api('/api/send-code',{email:address});message(r.message);$('email-form').hidden=true;$('code-form').hidden=false;$('code').focus()})};
$('code-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{await api('/api/verify-code',{email:address,code:$('code').value});await load()})};
$('back').onclick=()=>{$('code-form').hidden=true;$('email-form').hidden=false;$('code').value='';message('')};
$('logout').onclick=async()=>{try{await api('/api/logout',{})}finally{clear();$('back').click()}};
load().catch(()=>clear());
setInterval(async()=>{if(!$('portal').hidden){try{await load()}catch(e){clear();message('יש להתחבר מחדש',true)}}},60000);

document.querySelectorAll('.building-photo').forEach(img=>img.addEventListener('error',()=>{img.hidden=true}));
