/* Main doorway detection with an independent local classroom and the existing renderer. */
(() => {
  'use strict';
  function entrance(data,roomId="class1") {
    const room=data.rooms.find(r=>r.id===roomId);
    const segments=data.walls.filter(w=>w.y1===room.y&&w.y2===room.y)
      .map(w=>[Math.max(room.x,Math.min(w.x1,w.x2)),Math.min(room.x+room.w,Math.max(w.x1,w.x2))])
      .filter(([a,b])=>b>a).sort((a,b)=>a[0]-b[0]);
    let end=room.x;
    for(const [a,b] of segments){if(a-end>20)return {room,left:end,right:a,y:room.y};end=Math.max(end,b);}
    if(room.x+room.w-end>20)return {room,left:end,right:room.x+room.w,y:room.y};
    throw new Error('class1 doorway gap not found');
  }
  function crossedEntrance(previous,current,door) {
    if(previous.floor!=='campus'||current.floor!=='campus'||previous.y>=door.y||current.y<door.y)return false;
    const t=(door.y-previous.y)/(current.y-previous.y),x=previous.x+(current.x-previous.x)*t;
    const r=door.room;
    return x>door.left&&x<door.right&&current.x>=r.x&&current.x<=r.x+r.w&&current.y<=r.y+r.h;
  }
  function create({data,onOpen,onExit,getPlayer,moveSpeed=125}) {
    const dialog=document.getElementById('classroomDialog'),pythonDoor=entrance(data);
    const sqlDoor=data.rooms.some(r=>r.id==='class2')?entrance(data,'class2'):null;
    let door=pythonDoor,subject='python',map=window.CampusClassroomMap;
    const canvas=document.getElementById('classroomCanvas'),ctx=canvas.getContext('2d'),prompt=document.getElementById('classroomPrompt');
    const keys=new Set();let renderer=null,actor=null,near=null;
    function focus(){keys.clear();if(dialog.open)canvas.focus({preventScroll:true});}
    function open(){
      if(dialog.open)return;
      map=window.CampusClassroomMap.forSubject(subject);
      const title=document.getElementById('classroom-title');if(title)title.textContent=map.data.name;
      canvas.setAttribute?.('aria-label',`${subject==='sql'?'SQL':'Python'} 학습교실. WASD와 방향키로 이동하고 학습 영역 안에서 E키를 누르세요.`);
      onOpen();keys.clear();
      actor={...getPlayer(),x:map.data.spawn[0],y:map.data.spawn[1],moving:false,walkTime:0,visualZ:0,dir:'up'};
      renderer = window.CampusIsometric.create({data:map.data});
      dialog.showModal();focus();tick(performance.now(),0);
    }
    function activate(){
      near=map.nearby(actor);if(!near)return;
      keys.clear();actor.moving=false;
      if(near.id==='classroom-exit'){
        if(onExit({x:(door.left+door.right)/2,y:door.y-18})!==false){dialog.close();subject="python";door=pythonDoor;}
      }else window.CampusLearning.open(near.contentType,subject);
    }
    document.addEventListener('keydown',event=>{
      if(!dialog.open||window.CampusSession?.ending||window.CampusLearning?.blocking||event.isComposing||event.target.closest?.('input,textarea,[contenteditable="true"]'))return;
      const key=event.key.toLowerCase();
      if(key==="arrowdown"&&map.nearby(actor)?.id==="classroom-exit"){event.preventDefault();event.stopImmediatePropagation?.();activate();return;}
      if(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright'].includes(key)){event.preventDefault();keys.add(key);}
      else if(key==='e'&&!event.repeat){event.preventDefault();event.stopImmediatePropagation?.();activate();}
      else if(key==='enter'){event.preventDefault();}
    });
    document.addEventListener('keyup',event=>keys.delete(event.key.toLowerCase()));
    window.addEventListener('blur',()=>{keys.clear();if(actor)actor.moving=false;});
    canvas.addEventListener('pointerdown',focus);
    dialog.addEventListener('cancel',event=>event.preventDefault());
    dialog.addEventListener('close',()=>keys.clear());
    function tick(t,dt){
      if(!dialog.open)return;
      const wasMoving=actor.moving;actor.moving=false;
      if(window.CampusLearning?.blocking||window.CampusSession?.ending)keys.clear();
      else{
        const dx=Number(keys.has('d')||keys.has('arrowright'))-Number(keys.has('a')||keys.has('arrowleft'));
        const dy=Number(keys.has('s')||keys.has('arrowdown'))-Number(keys.has('w')||keys.has('arrowup'));
        if(dx||dy){
          const horizontal=dx>0?'right':'left',vertical=dy>0?'down':'up';
          if(!dx)actor.dir=vertical;else if(!dy||!wasMoving||(actor.dir!==horizontal&&actor.dir!==vertical))actor.dir=horizontal;
          const length=Math.hypot(dx,dy),v=renderer.projection.inverseVector(dx/length,dy/length);
          map.move(actor,v.x*moveSpeed*Math.min(dt,.04),v.y*moveSpeed*Math.min(dt,.04));
        }
      }
      actor.walkTime=actor.moving?(actor.walkTime||0)+dt:0;
      actor.avatar=getPlayer().avatar;
      near=map.nearby(actor);prompt.hidden=near?.id==="classroom-exit";prompt.textContent=near?'[E] '+near.name:'WASD / 방향키로 이동 · 학습 영역 안에서 E';
      const bounds=canvas.getBoundingClientRect(),width=bounds.width,height=bounds.height,dpr=Math.min(window.devicePixelRatio||1,2);
      if(!width||!height)return;
      if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
      const P=renderer.projection,view=map.data.viewBounds,zoom=Math.min(width/view.w,height/view.h),camera={zoom,x:(width-view.w*zoom)/2-view.x*zoom,y:(height-view.h*zoom)/2-view.y*zoom};
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);ctx.fillStyle="#e3cda8";ctx.fillRect(0,0,width,height);
      ctx.save();ctx.translate(camera.x,camera.y);ctx.scale(zoom,zoom);
      renderer.draw(ctx,{camera,actors:[actor,...map.data.residents],t,nearby:null,viewportWidth:width,viewportHeight:height});
      window.CampusClassroomAssets?.paintWallCorners(ctx,P);
      ctx.restore();
    }
    return {open,focus,tick,get door(){return door;},get actor(){return actor;},get subject(){return subject;},get blocking(){return dialog.open;},shouldEnter:(a,b)=>{
      for(const [candidate,value] of [[pythonDoor,'python'],[sqlDoor,'sql']]){
        const gate=candidate&&data.objects.find(o=>o.id==='door-'+candidate.room.id);
        if(candidate&&(!gate||gate.open)&&crossedEntrance(a,b,candidate)){door=candidate;subject=value;return true;}
      }
      return false;
    }};
  }
  window.CampusClassroom={entrance,crossedEntrance,create};
})();
