/* Real user activity and server-authoritative session expiry. Socket pings are not activity. */
(() => {
  'use strict';
  const configElement=document.getElementById('campusSessionPolicyConfig');
  if(!configElement)return;
  const config=JSON.parse(configElement.textContent);
  let state=null,clockOffset=0,ending=false,pendingActivity=false,activityRequest=null,statusRequest=null;
  let lastActivityRequest=-Infinity,activityTimer=null,verification=false,warningMode='';
  const interval=Math.max(1000,config.activityIntervalSeconds*1000);
  const banner=document.createElement('aside');banner.id='sessionWarning';banner.className='session-warning';
  banner.setAttribute('role','alert');banner.setAttribute('popover','manual');banner.hidden=true;
  const copy=document.createElement('div'),title=document.createElement('strong'),message=document.createElement('p');
  copy.append(title,message);
  const buttons=document.createElement('div');buttons.className='session-warning-actions';
  const keep=document.createElement('button');keep.type='button';keep.className='session-continue';keep.textContent='계속 이용하기';
  const signOut=document.createElement('button');signOut.type='button';signOut.textContent='로그아웃';
  buttons.append(keep,signOut);banner.append(copy,buttons);document.body.append(banner);

  function placeWarning(){
    // A popover outside a modal dialog remains inert even when it is painted on top.
    const dialogs=[...document.querySelectorAll('dialog[open]')];
    const host=dialogs.filter(dialog=>dialog.matches(':modal')).at(-1)||document.body;
    if(banner.parentElement!==host){
      if(typeof banner.hidePopover==='function'&&banner.matches(':popover-open'))banner.hidePopover();
      host.append(banner);
    }
    if(typeof banner.showPopover==='function'&&!banner.matches(':popover-open'))banner.showPopover();
  }
  function hideWarning(){
    if(typeof banner.hidePopover==='function'&&banner.matches(':popover-open'))banner.hidePopover();
    banner.hidden=true;warningMode='';
  }
  function receive(value){
    if(ending||!value||value.reason==='retry')return;
    if(value.authenticated===false){expire(value.reason);return;}
    if(value.authenticated!==true||![value.serverNow,value.expiresAt,value.absoluteExpiresAt,value.idleExpiresAt,value.warningSeconds].every(Number.isFinite))return;
    state=value;clockOffset=value.serverNow-Date.now();renderWarning();
  }
  async function expire(reason='signed_out'){
    if(ending)return;
    const untilMaximum=state?state.absoluteExpiresAt-Date.now()-clockOffset:Infinity;
    // Browser cookie expiry rounds to whole seconds; let the server's exact deadline pass.
    const cookieRoundedEarly=reason==='signed_out'&&untilMaximum<=1000;
    if(cookieRoundedEarly)reason='maximum';
    ending=true;clearTimeout(activityTimer);clearInterval(timer);clearInterval(poll);
    hideWarning();
    if(cookieRoundedEarly&&untilMaximum>0)await new Promise(resolve=>setTimeout(resolve,untilMaximum+20));
    if(window.CampusApp){window.CampusApp.player.moving=false;window.CampusApp.presence.close();}
    // The server has saved the final accepted position and invalidated the session already.
    // Never POST logout from an old tab: another tab may have just logged into a new session.
    const url=new URL(config.loginUrl,location.href);
    if(['idle','maximum'].includes(reason))url.searchParams.set('expired',reason);
    location.replace(url.href);
  }
  async function requestStatus(){
    if(ending)return false;
    if(statusRequest)return statusRequest;
    statusRequest=(async()=>{
      try{
        const response=await fetch(config.statusUrl,{credentials:'same-origin',cache:'no-store'});
        if(response.status===200||response.status===401){receive(await response.json());return true;}
      }catch{ /* Keep the last deadline; retry without counting a network check as activity. */ }
      return false;
    })();
    try{return await statusRequest;}finally{statusRequest=null;}
  }
  async function sendActivity(force=false){
    if(ending||!pendingActivity||activityRequest)return;
    const delay=interval-(performance.now()-lastActivityRequest);
    if(!force&&delay>0){
      if(activityTimer===null)activityTimer=setTimeout(()=>{activityTimer=null;sendActivity();},delay);
      return;
    }
    pendingActivity=false;lastActivityRequest=performance.now();
    activityRequest=(async()=>{
      try{
        const response=await fetch(config.activityUrl,{method:'POST',credentials:'same-origin',cache:'no-store',
          headers:{'X-CSRFToken':config.csrfToken,'Content-Type':'application/json'},body:'{}'});
        if(response.status===200||response.status===401)receive(await response.json());
        else await requestStatus();
      }catch{ /* Offline activity cannot extend a server session. */ }
    })();
    try{await activityRequest;}finally{activityRequest=null;if(pendingActivity)sendActivity();}
  }
  function activity(event){
    if(ending||event.isTrusted!==true)return;
    // Warning controls have their own actions; one click produces one explicit extension.
    if(banner.contains(event.target))return;
    pendingActivity=true;sendActivity();
  }
  keep.addEventListener('click',()=>{pendingActivity=true;sendActivity(true);});
  signOut.addEventListener('click',()=>{
    const form=document.getElementById('campusLogoutForm');
    if(form){form.requestSubmit();return;}
    const fallback=document.createElement('form');fallback.method='post';fallback.action=config.logoutUrl;
    const token=document.createElement('input');token.type='hidden';token.name='csrfmiddlewaretoken';token.value=config.csrfToken;
    fallback.append(token);document.body.append(fallback);fallback.requestSubmit();
  });
  for(const name of ['pointerdown','keydown','input','wheel','touchstart'])document.addEventListener(name,activity,{capture:true,passive:true});
  function renderWarning(){
    if(ending||!state)return;
    const now=Date.now()+clockOffset,remaining=Math.ceil((state.expiresAt-now)/1000);
    if(remaining<=0){
      if(!verification){verification=true;requestStatus().finally(()=>{verification=false;});}
      return;
    }
    if(remaining>state.warningSeconds){hideWarning();return;}
    const mode=state.absoluteExpiresAt<=state.idleExpiresAt?'maximum':'idle';
    title.textContent=mode==='maximum'?'로그인 유지 시간이 곧 끝나요':'곧 자동 로그아웃돼요';
    message.textContent=mode==='maximum'
      ?`${remaining}초 뒤 마지막 위치를 저장하고 로그아웃합니다. 작성 중인 내용을 마무리해 주세요.`
      :`${remaining}초 동안 활동이 없으면 마지막 위치를 저장하고 로그아웃합니다.`;
    keep.hidden=mode==='maximum';banner.dataset.reason=mode;
    if(warningMode!==mode||banner.hidden){
      warningMode=mode;banner.hidden=false;
    }
    placeWarning();
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)requestStatus();});
  window.addEventListener('pageshow',event=>{if(event.persisted)requestStatus();});
  const timer=setInterval(renderWarning,1000),poll=setInterval(requestStatus,15000);
  window.CampusSession={receive,expire,get ending(){return ending;}};
  receive(config.status);
  requestStatus();
})();
