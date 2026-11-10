/* Shared by the portal and the committee dashboard. */
(()=>{
  const el=(tag,txt)=>{const n=document.createElement(tag);if(txt)n.textContent=txt;return n};
  function show(parent,notice){
    const body=el(notice.body_html?'div':'p');body.className='notice-rich-body';body.dir='rtl';
    if(notice.body_html)body.innerHTML=notice.body_html;else body.textContent=notice.body;
    parent.append(body);
  }
  function create(field){
    const wrap=el('div'),bar=el('div'),edit=el('div');
    wrap.className='haruv-rich-editor';bar.className='haruv-editor-toolbar';edit.className='haruv-editor-input';
    bar.setAttribute('role','group');bar.setAttribute('aria-label','כלי עיצוב ההודעה');
    edit.contentEditable='true';edit.dir='rtl';edit.setAttribute('role','textbox');edit.setAttribute('aria-label','תוכן ההודעה');edit.setAttribute('aria-multiline','true');
    field.hidden=true;field.required=false;field.before(wrap);wrap.append(bar,edit);
    const label=field.labels?.[0];if(label){edit.id=field.id+'-editable';label.addEventListener('click',()=>edit.focus())}
    let range=null, pendingSize=null;
    const current=()=>{const s=getSelection();return s.rangeCount&&edit.contains(s.getRangeAt(0).commonAncestorContainer)?s.getRangeAt(0):null};
    const capture=()=>{const r=current();if(r)range=r.cloneRange()};
    document.addEventListener('selectionchange',capture);
    const sync=()=>{field.value=edit.innerText.replace(/\u00a0/g,' ').trim()};
    const applySize=()=>{if(!pendingSize)return;for(const node of edit.querySelectorAll('font[size="7"],span'))if(node.tagName==='FONT'||node.style.fontSize==='xxx-large'){
      node.removeAttribute('size');node.style.fontSize=pendingSize;
      if(node.tagName==='FONT'){const span=el('span');span.style.fontSize=pendingSize;span.append(...node.childNodes);node.replaceWith(span)}
    }};
    const run=(command,value=null)=>{
      edit.focus();if(range&&edit.contains(range.commonAncestorContainer)){const s=getSelection();s.removeAllRanges();s.addRange(range)}
      document.execCommand('styleWithCSS',false,true);
      if(command==='size'){
        pendingSize=value;document.execCommand('fontSize',false,'7');applySize();
      }else document.execCommand(command,false,value);
      capture();sync();
    };
    const button=(title,label,cmd,value)=>{const n=el('button',label);n.type='button';n.title=title;n.setAttribute('aria-label',title);n.addEventListener('pointerdown',e=>{capture();if(e.pointerType==='mouse')e.preventDefault()});n.onclick=()=>run(cmd,value);bar.append(n);return n};
    const select=(title,choices,cmd)=>{const n=el('select');n.setAttribute('aria-label',title);const empty=el('option',title);empty.value='';n.append(empty);for(const [v,t] of choices){const o=el('option',t);o.value=v;n.append(o)}n.onpointerdown=capture;n.onchange=()=>{if(n.value)run(cmd,n.value);n.value=''};bar.append(n)};
    select('גופן',[['Arial','Arial'],['Tahoma','Tahoma'],['Verdana','Verdana'],['Georgia','Georgia'],['Times New Roman','Times New Roman']],'fontName');
    select('גודל טקסט',[12,14,16,18,20,24,28,32].map(n=>[n+'px',String(n)]),'size');
    button('מודגש','B','bold').classList.add('is-bold');button('נטוי','I','italic').classList.add('is-italic');button('קו תחתי','U','underline').classList.add('is-underlined');button('קו חוצה','S','strikeThrough').classList.add('is-struck');
    for(const [title,cmd,initial] of [['צבע טקסט','foreColor','#38291e'],['צבע רקע להדגשה','hiliteColor','#ffe69a']]){
      const lbl=el('label',title),n=el('input');n.type='color';n.value=initial;n.setAttribute('aria-label',title);n.onpointerdown=capture;n.onchange=()=>run(cmd,n.value);lbl.append(n);bar.append(lbl);
    }
    button('רשימת תבליטים','• רשימה','insertUnorderedList');button('רשימה ממוספרת','1. רשימה','insertOrderedList');
    button('יישור לימין','ימין','justifyRight');button('יישור למרכז','מרכז','justifyCenter');button('יישור לשמאל','שמאל','justifyLeft');
    button('בטל','↶','undo');button('בצע שוב','↷','redo');button('נקה עיצוב','נקה עיצוב','removeFormat');
    edit.addEventListener('input',()=>{applySize();sync()});
    edit.addEventListener('paste',e=>{e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'));sync()});
    edit.addEventListener('drop',e=>e.preventDefault());
    return {set(notice={}){range=null;pendingSize=null;if(notice.body_html)edit.innerHTML=notice.body_html;else edit.textContent=notice.body||'';sync()},get(){sync();return {body:field.value,body_html:edit.querySelector('[style],b,strong,i,em,u,s,strike,ul,ol,blockquote,h2,h3')?edit.innerHTML:undefined}},focus(){edit.focus()}};
  }
  window.HaruvNoticeEditor={create,show};
})();
