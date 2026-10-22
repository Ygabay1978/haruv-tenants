(async()=>{
const status=document.getElementById('connect-status');const state=new URLSearchParams(location.search).get('state');
if(!/^[a-f0-9]{32}$/.test(state||'')||!window.opener){status.textContent='יש לפתוח את החיבור מתוך דשבורד הוועד.';return}
try{const response=await fetch('/api/admin/dashboard-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});const data=await response.json();if(response.status===401){location.replace('/?dashboard='+state);return}if(!response.ok)throw new Error(data.error||'אין הרשאה לחשבון זה');
if(data.origin!=='https://haruv-building-private.spiffydog258.chatgpt.site')throw new Error('מקור הדשבורד אינו תקין');
window.opener.postMessage({type:'haruv-dashboard-auth',state,token:data.token},data.origin);status.textContent='החיבור הושלם. אפשר לחזור לדשבורד.';window.close()
}catch(error){status.textContent=error.message}
})();