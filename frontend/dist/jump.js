/* Cosmetic jumps: ground position and collisions stay server-owned. */
(()=>{
 'use strict';
 const DURATION=720,HEIGHT=52,LANDING=120;
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
 function age(actor,t){return actor?._campusJump?t-actor._campusJump.started:Infinity;}
 function height(actor,t=performance.now()){const p=age(actor,t)/DURATION;return p>=0&&p<1?4*p*(1-p)*HEIGHT:0;}
 function squash(actor,t){const elapsed=age(actor,t)-DURATION;return !reduced.matches&&elapsed>=0&&elapsed<LANDING?1-.1*Math.sin(elapsed/LANDING*Math.PI):1;}
 function pose(actor,t){return age(actor,t)>=0&&age(actor,t)<DURATION?{...actor,moving:true,stairFrame:2}:actor;}
 function create({getPlayer,getPresence,getClassroom,isBlocked,notify=()=>{}}){
  const seen=new Set();let readyAt=0,lastScope='',sequence=0;
  const scope=()=>getClassroom().blocking?{context:'classroom',subject:getClassroom().subject}:{context:'world',floor:getPlayer().floor};
  const actors=()=>[getPlayer(),...getPresence().peers.values(),getClassroom().actor].filter(Boolean);
  const own=()=>getClassroom().blocking?getClassroom().actor:getPlayer();
  function reset(){for(const actor of actors())delete actor._campusJump;readyAt=0;lastScope=JSON.stringify(scope());}
  function trigger(){
   const now=performance.now(),actor=own();
   if(!actor||isBlocked()||document.hidden||now<readyAt||age(actor,now)<DURATION)return false;
   if(!getPresence().connected){notify('연결된 뒤 점프를 이용해 주세요.');return false;}
   const context=scope(),id='local-'+(++sequence);lastScope=JSON.stringify(context);readyAt=now+DURATION;
   actor._campusJump={id,started:now,...context};
   getPresence().command('jump',context).catch(error=>{if(actor._campusJump?.id===id)delete actor._campusJump;if(!window.CampusSession?.ending)notify(error.message);});
   return true;
  }
  function receive(packet){
   if(typeof packet?.id!=='string'||typeof packet.actorId!=='string'||packet.durationMs!==DURATION||packet.height!==HEIGHT||seen.has(packet.id))return;
   seen.add(packet.id);if(seen.size>128)seen.delete(seen.values().next().value);
   // The local player already started immediately on input; its acknowledgement never restarts it.
   if(packet.actorId===getPresence().selfId)return;
   const actor=getPresence().peers.get(packet.actorId);
   if(packet.context!=='world'||!actor||actor.inClassroom||actor.floor!==packet.floor||getPlayer().floor!==packet.floor||getClassroom().blocking)return;
   actor._campusJump={id:packet.id,started:performance.now(),context:'world',floor:packet.floor};
  }
  function tick(t){
   const current=JSON.stringify(scope());if(current!==lastScope){reset();return;}
   for(const actor of actors()){const jump=actor._campusJump;if(jump&&(age(actor,t)>DURATION+LANDING||(jump.context==='world'&&(actor.floor!==jump.floor||actor.inClassroom))))delete actor._campusJump;}
  }
  document.getElementById('campusJumpButton')?.addEventListener('click',trigger);
  window.addEventListener('campus:guide-open',reset);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)reset();});
  return {trigger,receive,tick,reset};
 }
 window.CampusJump={DURATION,HEIGHT,height,squash,pose,create};
})();
