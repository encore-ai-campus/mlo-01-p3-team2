/* A server-accepted, transient hand overlay; character and wallet positions stay untouched. */
(() => {
  'use strict';
  const diagonal=Math.SQRT1_2;
  const vectors={up:[0,-1],down:[0,1],left:[-1,0],right:[1,0],
    'up-left':[-diagonal,-diagonal],'up-right':[diagonal,-diagonal],
    'down-left':[-diagonal,diagonal],'down-right':[diagonal,diagonal]};
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  const duration=220,reactionDuration=240,interval=250;
  function directionVector(P,dir){
    const [x,y]=vectors[dir],floor=P.inverseVector(x,y),scale=1/Math.hypot(floor.x,floor.y);
    return {x:x*scale,y:y*scale};
  }
  function effect(actor,key,t,limit){
    const value=actor[key];
    if(!value)return null;
    if(t-value.started>=limit){delete actor[key];return null;}
    return value;
  }
  function action(actor,t){
    const loop=actor._campusPokeLoop;
    if(loop){
      if(Number.isFinite(loop.lastHit)&&t-loop.lastHit>350)loop.reach=72;
      if(Number.isFinite(actor.receivedAt)&&t-actor.receivedAt>750){loop.paused=true;return null;}
      else{loop.paused=false;const phase=Math.max(0,t-loop.started)%interval;return phase<duration?{...loop,started:t-phase,loop:true}:null;}
    }
    return effect(actor,'_campusPoke',t,duration);
  }
  function pose(actor,t){
    const current=action(actor,t);
    if(!current)return actor;
    const parts=current.dir.split('-'),dir=parts.includes(actor.dir)?actor.dir:parts.at(-1);
    return {...actor,dir,moving:current.loop?actor.moving:false};
  }
  function react(ctx,actor,t,P){
    const hit=effect(actor,'_campusPokeReaction',t,reactionDuration);
    if(!hit||reducedMotion.matches)return;
    const p=(t-hit.started)/reactionDuration,fade=Math.max(0,1-p);
    const v=directionVector(P,hit.dir);
    ctx.translate(v.x*Math.sin(p*Math.PI)*3,Math.sin(p*Math.PI*5)*1.2*fade);
    ctx.rotate(Math.sin(p*Math.PI*3)*.11*fade);
  }
  function draw(ctx,actor,t,P,behind){
    const current=action(actor,t);
    if(!current)return;
    const v=directionVector(P,current.dir);
    if((v.y<0)!==behind)return;
    const progress=Math.max(0,(t-current.started)/duration);
    const extension=reducedMotion.matches?1:Math.sin(Math.PI*progress);
    const size=window.CampusAvatars?.size||40,start=size*.18,maxReach=Math.max(start,(current.reach||72)-size*.68);
    const reach=start+(maxReach-start)*extension;
    ctx.save();ctx.strokeStyle=actor.color||window.CampusAvatars?.definitions[actor.avatar]?.color||'#4e9b91';ctx.lineWidth=3;ctx.lineCap='round';
    ctx.beginPath();ctx.moveTo(v.x*size*.12,-size*.32+v.y*size*.12);ctx.lineTo(v.x*(reach-3),-size*.32+v.y*(reach-3));ctx.stroke();ctx.restore();
    ctx.save();ctx.translate(v.x*reach,-size*.32+v.y*reach);ctx.rotate(Math.atan2(v.y,v.x));ctx.scale(size/100,size/100);
    ctx.lineWidth=1.7;ctx.lineJoin='round';ctx.lineCap='round';ctx.fillStyle='#fff9e9';ctx.strokeStyle='#796d54';
    ctx.beginPath();ctx.moveTo(-8,7);ctx.bezierCurveTo(-15,6,-16,-1,-10,-5);ctx.bezierCurveTo(-8,-10,-1,-11,3,-6);
    ctx.lineTo(21,-6);ctx.bezierCurveTo(27,-6,27,0,21,0);ctx.lineTo(7,0);ctx.bezierCurveTo(14,2,12,9,6,9);
    ctx.bezierCurveTo(9,14,1,16,-3,11);ctx.bezierCurveTo(-7,15,-14,12,-12,5);ctx.closePath();ctx.fill();ctx.stroke();
    ctx.strokeStyle='#d6cdb5';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(1,6);ctx.lineTo(7,7);ctx.moveTo(-4,10);ctx.lineTo(1,11);ctx.stroke();
    ctx.fillStyle='#fff9e9';ctx.strokeStyle='#796d54';ctx.beginPath();ctx.roundRect(-18,-2,6,10,2);ctx.fill();ctx.stroke();
    if(!reducedMotion.matches&&progress<.6){ctx.strokeStyle='#79a785';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(-12,-15);ctx.quadraticCurveTo(-6,-18,1,-15);ctx.moveTo(-15,-21);ctx.quadraticCurveTo(-8,-24,0,-21);ctx.stroke();}
    ctx.restore();
  }
  function contact(ctx,actor,t,P){
    const hit=effect(actor,'_campusPokeReaction',t,reactionDuration);
    if(!hit)return;
    const age=Math.max(0,(t-hit.started)/reactionDuration),v=directionVector(P,hit.dir);
    ctx.save();ctx.translate(-v.x*9,-13-v.y*6);ctx.globalAlpha*=1-age;
    ctx.strokeStyle='#d9a64e';ctx.lineWidth=1.4;ctx.lineCap='round';
    for(let i=0;i<5;i++){const a=i*Math.PI*2/5;ctx.beginPath();ctx.moveTo(Math.cos(a)*3,Math.sin(a)*3);ctx.lineTo(Math.cos(a)*6.5,Math.sin(a)*6.5);ctx.stroke();}
    ctx.restore();
  }
  function create({getPlayer,getPresence,getClassroom,getInput=()=>[],isBlocked,notify=()=>{}}){
    const button=document.getElementById('campusPokeButton'),held=new Set(),seen=new Set();
    let lastContext='',readyAt=0,pulseTimer=null,suppressClick=false;
    function context(){const classroom=getClassroom();return classroom.blocking?{context:'classroom',subject:classroom.subject}:{context:'world',floor:getPlayer().floor};}
    function selfActor(){return getClassroom().blocking?getClassroom().actor:getPlayer();}
    function actors(){return [getPlayer(),...getPresence().peers.values(),getClassroom().actor,...(getClassroom().residents||[])].filter(Boolean);}
    function finish(actor){
      const loop=actor?._campusPokeLoop;if(!loop)return;
      const now=performance.now(),phase=Math.max(0,now-loop.started)%interval;
      if(phase<duration&&(!Number.isFinite(actor.receivedAt)||now-actor.receivedAt<=750))actor._campusPoke={...loop,started:now-phase};
      delete actor._campusPokeLoop;
    }
    function facing(actor,t){
      const keys=new Set(getInput()),dx=Number(keys.has('d')||keys.has('arrowright'))-Number(keys.has('a')||keys.has('arrowleft')),
        dy=Number(keys.has('s')||keys.has('arrowdown'))-Number(keys.has('w')||keys.has('arrowup'));
      let direction=dx&&dy?(dy<0?'up':'down')+'-'+(dx<0?'left':'right'):dx?(dx<0?'left':'right'):dy?(dy<0?'up':'down'):null;
      if(dx&&dy)actor._campusPokeDiagonalAt=t;
      else if(direction&&actor._campusPokeFacing?.includes('-')&&t-(actor._campusPokeDiagonalAt||0)<80)direction=actor._campusPokeFacing;
      if(direction)actor._campusPokeFacing=direction;
      return actor._campusPokeFacing||actor.dir;
    }
    function predict(t){
      const actor=selfActor();
      if(!actor||actor._campusPokeLoop||t<readyAt||t-(actor.receivedAt||0)>750)return;
      actor._campusPokeLoop={id:'local',started:t,dir:facing(actor,t),reach:72};
      delete actor._campusPoke;readyAt=t+interval;
    }
    function setHeld(active,source='keyboard'){
      if(active){
        if(held.has(source)||isBlocked()||document.hidden)return;
        if(!getPresence().connected){notify('연결된 뒤 찌르기를 이용해 주세요.');return;}
        held.add(source);
        getPresence().setPoking(true,context(),getInput());predict(performance.now());
      }else{
        held.delete(source);
        if(!held.size){getPresence().setPoking(false,null,getInput());finish(selfActor());}
      }
    }
    function stop(clearMovement=false){
      held.clear();clearTimeout(pulseTimer);pulseTimer=null;
      getPresence().setPoking(false,null,clearMovement||isBlocked()||document.hidden?[]:getInput());finish(selfActor());
    }
    function trigger(){
      if(performance.now()<readyAt)return;
      setHeld(true,'pulse');clearTimeout(pulseTimer);
      pulseTimer=setTimeout(()=>setHeld(false,'pulse'),90);
    }
    function receive(packet){
      if(!packet||typeof packet.id!=='string'||typeof packet.actorId!=='string'||!Object.hasOwn(vectors,packet.dir))return;
      const view=context(),presence=getPresence(),own=packet.actorId===presence.selfId;
      if(packet.context!==view.context||(view.context==='classroom'?packet.subject!==view.subject||!own:packet.floor!==view.floor))return;
      const classroom=getClassroom(),source=view.context==='classroom'?classroom.actor:own?getPlayer():presence.peers.get(packet.actorId);
      if(!source)return;
      const now=performance.now();
      if(packet.type==='poke_state'){
        if(typeof packet.active!=='boolean')return;
        if(!packet.active){if(source._campusPokeLoop?.id===packet.id)finish(source);return;}
        if(own&&!held.size)return;
        const phase=Number.isFinite(packet.phaseMs)?Math.max(0,Math.min(interval-1,packet.phaseMs)):0;
        const old=source._campusPokeLoop;
        const same=old?.id===packet.id;
        source._campusPokeLoop={id:packet.id,dir:packet.dir,started:same?old.started:now-phase,reach:same?old.reach:72,lastHit:same?old.lastHit:undefined};
        delete source._campusPoke;
        if(own){source._campusPokeFacing=packet.dir;readyAt=Math.max(readyAt,now+interval-phase);}
        return;
      }
      if(!['poke_hit','poke'].includes(packet.type)||(packet.targetId!==null&&typeof packet.targetId!=='string')||seen.has(packet.id))return;
      seen.add(packet.id);if(seen.size>128)seen.delete(seen.values().next().value);
      const target=view.context==='classroom'?classroom.residents.find(actor=>actor.id===packet.targetId):packet.targetId===presence.selfId?getPlayer():presence.peers.get(packet.targetId);
      const distance=target?Math.hypot(target.x-source.x,target.y-source.y):72,reach=Number.isFinite(distance)?Math.min(72,distance):72;
      if(source._campusPokeLoop){source._campusPokeLoop.reach=reach;source._campusPokeLoop.lastHit=now;}
      if(packet.type==='poke')source._campusPoke={started:now,dir:packet.dir,reach};
      if(target)target._campusPokeReaction={started:now,dir:packet.dir};
    }
    function tick(t){
      const current=JSON.stringify(context());
      if(current!==lastContext){stop();for(const actor of actors()){delete actor._campusPokeLoop;delete actor._campusPoke;delete actor._campusPokeReaction;delete actor._campusPokeFacing;delete actor._campusPokeDiagonalAt;}lastContext=current;}
      if(isBlocked()||!getPresence().connected||document.hidden)stop();
      const actor=selfActor();if(actor){facing(actor,t);if(held.size){predict(t);if(actor._campusPokeLoop)actor._campusPokeLoop.dir=actor._campusPokeFacing||actor.dir;}}
      if(button){const disabled=!getPresence().connected||isBlocked();if(button.disabled!==disabled)button.disabled=disabled;button.setAttribute('aria-pressed',String(held.size>0));}
    }
    lastContext=JSON.stringify(context());
    document.addEventListener('keyup',event=>{
      const key=window.CampusKeyboard.key(event);
      if(key==='z')setHeld(false,'keyboard');
      if(key==='enter'||key===' ')setHeld(false,'button-key');
    });
    window.addEventListener('blur',()=>stop(true));window.addEventListener('pagehide',()=>stop(true));
    document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
    document.addEventListener('focusin',event=>{if(event.target!==button&&event.target.closest?.('input,textarea,select,button,a,[contenteditable="true"]'))stop();});
    button?.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();suppressClick=true;button.focus({preventScroll:true});button.setPointerCapture(event.pointerId);setHeld(true,'pointer');});
    for(const type of ['pointerup','pointercancel','lostpointercapture'])button?.addEventListener(type,()=>setHeld(false,'pointer'));
    button?.addEventListener('click',()=>{if(suppressClick){suppressClick=false;return;}trigger();});
    button?.addEventListener('keydown',event=>{
      if((event.isComposing&&!window.CampusKeyboard.isGameKey(event))||event.ctrlKey||event.altKey||event.metaKey)return;
      const key=window.CampusKeyboard.key(event);
      if(key==='z'||key==='enter'||key===' '){event.preventDefault();event.stopImmediatePropagation();if(!event.repeat)setHeld(true,key==='z'?'keyboard':'button-key');}
    });
    return {receive,trigger,setHeld,stop,tick,get held(){return held.size>0;}};
  }
  window.CampusPoke={create,pose,react,draw,contact};
})();
