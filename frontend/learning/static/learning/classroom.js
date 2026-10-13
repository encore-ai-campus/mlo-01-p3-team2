/* Private classroom: collect keys, render accepted state, and show server decisions. */
(() => {
  'use strict';
  function create({onOpen=()=>{},onExit=()=>{},getPlayer,getControl}) {
    const dialog=document.getElementById('classroomDialog'),canvas=document.getElementById('classroomCanvas');
    const ctx=canvas.getContext('2d'),prompt=document.getElementById('classroomPrompt'),keys=new Set();
    const movementKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright']);
    let renderer=null,actor=null,near=null,map=null,subject='python';
    function focus(){keys.clear();getControl().setInput([]);if(dialog.open)canvas.focus({preventScroll:true});}
    function applyState(state){
      if(!state){
        if(dialog.open){keys.clear();getControl().setInput([]);dialog.close();onExit();}
        actor=null;near=null;return;
      }
      const opening=!dialog.open||subject!==state.subject;
      if(opening){
        subject=state.subject;map=window.CampusClassroomMap.forSubject(subject);
        renderer=window.CampusIsometric.create({data:map.data});
        actor={...getPlayer(),...state.actor,walkTime:0,visualZ:0};
        const title=document.getElementById('classroom-title');if(title)title.textContent=map.data.name;
        canvas.setAttribute?.('aria-label',`${subject==='sql'?'SQL':'Python'} 학습교실. WASD와 방향키로 이동하고 학습 영역 안에서 E키를 누르세요.`);
        onOpen();keys.clear();if(!dialog.open)dialog.showModal();focus();
      }
      actor.targetX=state.actor.x;actor.targetY=state.actor.y;
      Object.assign(actor,{dir:state.actor.dir,moving:state.actor.moving,avatar:state.actor.avatar||getPlayer().avatar});
      near=state.nearby;
    }
    async function activate(){
      keys.clear();getControl().setInput([]);
      try{
        const result=await getControl().command('interact');
        if(result?.type==='learning_open')window.CampusLearning.open(result.questionType,result.subject);
      }catch(error){window.CampusApp?.toast(error.message);}
    }
    document.addEventListener('keydown',event=>{
      if(!dialog.open||window.CampusSession?.ending||window.CampusLearning?.blocking||event.isComposing||event.target.closest?.('input,textarea,[contenteditable="true"]'))return;
      const key=event.key.toLowerCase();
      if(movementKeys.has(key)){event.preventDefault();keys.add(key);}
      else if(key==='e'&&!event.repeat){event.preventDefault();event.stopImmediatePropagation?.();activate();}
      else if(key==='enter')event.preventDefault();
    });
    document.addEventListener('keyup',event=>keys.delete(event.key.toLowerCase()));
    window.addEventListener('blur',()=>{keys.clear();getControl().setInput([]);});
    canvas.addEventListener('pointerdown',focus);
    dialog.addEventListener('cancel',event=>event.preventDefault());
    dialog.addEventListener('close',()=>keys.clear());
    function tick(t,dt){
      if(!dialog.open||!actor)return;
      if(window.CampusLearning?.blocking||window.CampusSession?.ending)keys.clear();
      getControl().setInput([...keys]);
      const blend=1-Math.exp(-dt*18);
      actor.x+=(actor.targetX-actor.x)*blend;actor.y+=(actor.targetY-actor.y)*blend;
      actor.walkTime=actor.moving?(actor.walkTime||0)+dt:0;actor.avatar=getPlayer().avatar;
      prompt.hidden=near?.id==='classroom-exit';prompt.textContent=near?'[E] '+near.name:'WASD / 방향키로 이동 · 학습 영역 안에서 E';
      const bounds=canvas.getBoundingClientRect(),width=bounds.width,height=bounds.height,dpr=Math.min(window.devicePixelRatio||1,2);
      if(!width||!height)return;
      if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
      const P=renderer.projection,view=map.data.viewBounds,zoom=Math.min(width/view.w,height/view.h),camera={zoom,x:(width-view.w*zoom)/2-view.x*zoom,y:(height-view.h*zoom)/2-view.y*zoom};
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);ctx.fillStyle='#e3cda8';ctx.fillRect(0,0,width,height);
      ctx.save();ctx.translate(camera.x,camera.y);ctx.scale(zoom,zoom);
      renderer.draw(ctx,{camera,actors:[actor,...map.data.residents],t,nearby:null,viewportWidth:width,viewportHeight:height});
      window.CampusClassroomAssets?.paintWallCorners(ctx,P);ctx.restore();
    }
    return {applyState,focus,tick,get actor(){return actor;},get subject(){return subject;},get blocking(){return dialog.open;}};
  }
  window.CampusClassroom={create};
})();
