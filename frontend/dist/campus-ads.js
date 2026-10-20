/* 서버 회차와 이동 승인을 사용하며 광고 실패가 게임 이동을 막지 않게 한다. */
(() => {
  'use strict';
  const {ContinuousExposure,visibleRatio}=window.CampusAdVisibility;
  const detector=new ContinuousExposure();
  let roof=null,nextRoof=0,roofLoading=false,portalVersion=0,portalAds=[];
  const reporting=new Map();
  const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]')?.value||decodeURIComponent(document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1]||'');
  async function post(path,body={},timeout=5000){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch('/api/ads/'+path,{method:'POST',credentials:'same-origin',signal:controller.signal,
        headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(body)});
      if(!response.ok)throw Error('ad_unavailable');
      return await response.json();
    }finally{clearTimeout(timer);}
  }
  function safeUrl(raw){const url=new URL(raw,location.href);if(!['https:','http:'].includes(url.protocol))throw Error('ad_url');return url.href;}
  function image(ad,cors=false){return new Promise((resolve,reject)=>{
    const img=new Image(),timer=setTimeout(()=>{img.onload=null;img.onerror=null;reject(Error('image_timeout'));},4000);if(cors)img.crossOrigin='anonymous';
    img.onload=()=>{clearTimeout(timer);resolve(img);};img.onerror=()=>{clearTimeout(timer);reject(Error('image_failed'));};
    try{img.src=safeUrl(ad.image_url);}catch(error){clearTimeout(timer);reject(error);}
  });}
  function report(decision){
    if(reporting.has(decision))return;
    reporting.set(decision,true);
    // 접수 응답 유실 시 같은 결정을 한 번 재전송한다. 백엔드가 최초 반응 ID를 재사용한다.
    const send=()=>post('decisions/'+decision+'/impression/');
    send().catch(()=>setTimeout(()=>send().catch(()=>{}),1000));
  }
  async function refreshRoof(view){
    roofLoading=true;
    try{
      const started=performance.now(),batch=await post('placements/rooftop/');
      const remaining=Date.parse(batch.expires_at)-Date.parse(batch.server_time)-(performance.now()-started);
      if(!Number.isFinite(remaining))throw Error('ad_expiry');
      if(remaining<=0){nextRoof=performance.now()+100;return;}
      if(batch.state==='PENDING'){nextRoof=performance.now()+250;return;}
      // 서버 회차는 다음 조회 시각으로만 사용하고, 표시 중인 광고를 먼저 지우지 않는다.
      const deadline=performance.now()+remaining;nextRoof=deadline;
      const entry=batch.ads[0];
      if(batch.state!=='READY'||!entry?.ad)return;
      const candidate={...entry,ad:{...entry.ad,click_url:safeUrl(entry.ad.click_url)},view};
      const img=await image(candidate.ad,true);
      // 로딩 중 회차가 끝난 후보는 버리되, 기존 이미지·링크·노출 측정은 유지한다.
      if(performance.now()>=deadline)return;
      if(view.setDisplayImage('roof-ad-board',img)){
        // 실제 이미지 교체가 성공한 순간에만 클릭 대상과 새 광고의 노출 측정을 바꾼다.
        if(roof?.decision_id!==candidate.decision_id)detector.reset('roof');
        roof=candidate;
      }
    }catch{nextRoof=performance.now()+5000;}
    finally{roofLoading=false;}
  }
  function tick({now,floor,renderer,camera,canvas,width,height,blocked}){
    if(floor==='rooftop'&&!document.hidden&&!roofLoading&&now>=nextRoof)refreshRoof(renderer);
    let ratio=0;
    if(roof&&floor==='rooftop'&&!blocked&&!document.hidden&&document.hasFocus()){
      const bounds=canvas.getBoundingClientRect(),polygon=renderer.displayPolygon('roof-ad-board');
      if(polygon){
        const points=polygon.map(p=>({x:bounds.left+(p.x*camera.zoom+camera.x)*bounds.width/width,y:bounds.top+(p.y*camera.zoom+camera.y)*bounds.height/height}));
        ratio=visibleRatio(points,{left:Math.max(0,bounds.left),top:Math.max(0,bounds.top),right:Math.min(innerWidth,bounds.right),bottom:Math.min(innerHeight,bounds.bottom)});
      }
    }
    if(detector.observe('roof',roof?.decision_id,ratio,now))report(roof.decision_id);
  }
  function stopPortal(){
    portalVersion++;portalAds=[];detector.reset();
    const slot=document.getElementById('floorTransitionAdSlot');slot.replaceChildren();slot.hidden=true;
  }
  async function startPortal(token){
    stopPortal();const version=portalVersion;if(!token)return;
    try{
      const batch=await post('placements/portal/',{token},2500);
      if(version!==portalVersion||!document.getElementById('floorTransitionDialog').open||batch.state!=='READY')return;
      const slot=document.getElementById('floorTransitionAdSlot');
      await Promise.all(batch.ads.map(async(entry,index)=>{
        if(!entry.ad)return;
        try{
          const img=await image(entry.ad);
          if(version!==portalVersion||!document.getElementById('floorTransitionDialog').open)return;
          const link=document.createElement('a');link.href=safeUrl(entry.ad.click_url);link.target='_blank';link.rel='noopener noreferrer';
          link.className='portal-ad portal-ad-'+index;img.alt=entry.ad.title;link.append(img);slot.append(link);slot.hidden=false;
          portalAds.push({entry,img,index});
        }catch{ /* 로딩하지 못한 이미지는 표시·노출 보고하지 않는다. */ }
      }));
    }catch{ /* 광고 실패에도 3초 이동 화면은 계속 진행한다. */ }
  }
  function portalTick(now){
    for(const {entry,img,index} of portalAds){
      const r=img.getBoundingClientRect(),points=[{x:r.left,y:r.top},{x:r.right,y:r.top},{x:r.right,y:r.bottom},{x:r.left,y:r.bottom}];
      const active=!document.hidden&&document.hasFocus()&&document.getElementById('floorTransitionDialog').open;
      const ratio=active?visibleRatio(points,{left:0,top:0,right:innerWidth,bottom:innerHeight}):0;
      if(detector.observe('portal-'+index,entry.decision_id,ratio,now,active))report(entry.decision_id);
    }
    requestAnimationFrame(portalTick);
  }
  document.addEventListener('visibilitychange',()=>detector.reset());
  window.addEventListener('blur',()=>detector.reset());
  window.addEventListener('campus:floor-transition-end',stopPortal);
  requestAnimationFrame(portalTick);
  window.CampusAds={tick,startPortal,stopPortal,clickRoof(){
    if(!roof)return false;
    window.open(safeUrl(roof.ad.click_url),'_blank','noopener,noreferrer');return true;
  }};
})();
