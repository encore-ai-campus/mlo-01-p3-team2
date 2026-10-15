/* Private classroom: collect keys, render accepted state, and show server decisions. */
(() => {
  'use strict';
  function create({onOpen=()=>{},onExit=()=>{},getPlayer,getControl,onPoke=()=>{}}) {
    const dialog=document.getElementById('classroomDialog'),canvas=document.getElementById('classroomCanvas');
    const ctx=canvas.getContext('2d'),keys=new Set(),suppressedKeys=new Set();
    const areaHint=document.getElementById('classroomAreaHint'),prompt=document.getElementById('classroomPrompt');
    const movementKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright']);
    const guidedSubjects=new Set(),reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
    let renderer=null,actor=null,map=null,subject='python',activeType=null,guideUntil=0;
    function focus(){keys.clear();getControl().setInput([]);if(dialog.open)canvas.focus({preventScroll:true});}
    function applyState(state){
      if(!state){
        if(dialog.open){keys.clear();getControl().setInput([]);dialog.close();onExit();}
        actor=null;activeType=null;return;
      }
      const opening=!dialog.open||subject!==state.subject;
      if(opening){
        suppressedKeys.clear();
        for(const key of getControl().inputKeys||[])if(movementKeys.has(key))suppressedKeys.add(key);
        subject=state.subject;map=window.CampusClassroomMap.forSubject(subject);
        guideUntil=guidedSubjects.has(subject)?0:performance.now()+4500;guidedSubjects.add(subject);
        renderer=window.CampusIsometric.create({data:map.data});
        actor={...getPlayer(),...state.actor,walkTime:0,visualZ:0};
        delete actor._campusPoke;delete actor._campusPokeReaction;delete actor._campusPokeLoop;delete actor._campusPokeFacing;
        for(const resident of map.data.residents){delete resident._campusPoke;delete resident._campusPokeReaction;}
        const title=document.getElementById('classroom-title');if(title)title.textContent=map.data.name;
        canvas.setAttribute?.('aria-label',`${subject==='sql'?'SQL':'Python'} 학습교실. WASD와 방향키로 이동하고 학습 영역 안에서 E키, 가까운 캐릭터 앞에서 Z키를 누르세요.`);
        onOpen();keys.clear();if(!dialog.open)dialog.showModal();focus();
      }
      actor.targetX=state.actor.x;actor.targetY=state.actor.y;actor.receivedAt=performance.now();
      Object.assign(actor,{dir:state.actor.dir,moving:state.actor.moving,avatar:state.actor.avatar||getPlayer().avatar});
      const nearby=state.nearby,inside=Boolean(nearby);
      activeType=nearby?.contentType||null;
      if(activeType)guideUntil=0;
      if(areaHint.hidden!==inside)areaHint.hidden=inside;
      const cooldown=Math.ceil(Math.max(0,state.exitCooldownMs||0)/1000);
      const instruction=nearby?.id==='classroom-exit'?(cooldown?`나가기 · ${cooldown}초 후`:'메타버스로 나가기'):'상호작용';
      if(prompt.textContent!==instruction)prompt.textContent=instruction;
    }
    async function activate(){
      keys.clear();getControl().setInput([]);
      try{
        const result=await getControl().command('interact');
        if(result?.type==='learning_open')window.CampusLearning.open(result.questionType,result.subject);
      }catch(error){window.CampusApp?.toast(error.message);}
    }
    document.addEventListener('keydown',event=>{
      if(!dialog.open||window.CampusSession?.ending||window.CampusLearning?.blocking||(event.isComposing&&!window.CampusKeyboard.isGameKey(event))||event.target.closest?.('input,textarea,select,[contenteditable="true"]'))return;
      const key=window.CampusKeyboard.key(event);
      if(suppressedKeys.has(key)){event.preventDefault();return;}
      if(movementKeys.has(key)){event.preventDefault();keys.add(key);}
      else if(key==='e'&&!event.repeat){event.preventDefault();event.stopImmediatePropagation?.();activate();}
      else if(key==='z'&&!event.repeat&&!event.ctrlKey&&!event.altKey&&!event.metaKey){event.preventDefault();event.stopImmediatePropagation?.();onPoke();}
      else if(key==='enter')event.preventDefault();
    });
    document.addEventListener('keyup',event=>{const key=window.CampusKeyboard.key(event);keys.delete(key);suppressedKeys.delete(key);});
    window.addEventListener('blur',()=>{keys.clear();suppressedKeys.clear();getControl().setInput([]);});
    canvas.addEventListener('pointerdown',focus);
    dialog.addEventListener('cancel',event=>event.preventDefault());
    dialog.addEventListener('close',()=>keys.clear());
    function paintAreaGuide(ctx,P){
      window.CampusClassroomAssets?.paintAreaGuide(ctx,P,{activeType,
        intro:Math.max(0,(guideUntil-performance.now())/4500),
        time:performance.now()/1000,reducedMotion:reducedMotion.matches});
    }
    function tick(t,dt){
      if(!dialog.open||!actor)return;
      if(window.CampusLearning?.blocking||window.CampusSession?.ending)keys.clear();
      getControl().setInput([...keys]);
      const blend=1-Math.exp(-dt*18);
      actor.x+=(actor.targetX-actor.x)*blend;actor.y+=(actor.targetY-actor.y)*blend;
      actor.walkTime=actor.moving?(actor.walkTime||0)+dt:0;actor.avatar=getPlayer().avatar;
      const bounds=canvas.getBoundingClientRect(),width=bounds.width,height=bounds.height,dpr=Math.min(window.devicePixelRatio||1,2);
      if(!width||!height)return;
      if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
      const P=renderer.projection,view=map.data.viewBounds,zoom=Math.min(width/view.w,height/view.h),camera={zoom,x:(width-view.w*zoom)/2-view.x*zoom,y:(height-view.h*zoom)/2-view.y*zoom};
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);ctx.fillStyle='#e3cda8';ctx.fillRect(0,0,width,height);
      ctx.save();ctx.translate(camera.x,camera.y);ctx.scale(zoom,zoom);
      renderer.draw(ctx,{camera,actors:[actor,...map.data.residents],t,nearby:null,viewportWidth:width,viewportHeight:height,floorOverlay:paintAreaGuide});
      window.CampusClassroomAssets?.paintWallCorners(ctx,P);ctx.restore();
    }
    return {applyState,focus,tick,get actor(){return actor;},get subject(){return subject;},get residents(){return map?.data.residents||[];},get inputKeys(){return [...keys];},get blocking(){return dialog.open;}};
  }
  window.CampusClassroom={create};
})();
