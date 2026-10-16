/* Stair geometry and walking poses share the same floor coordinates. */
(() => {
  'use strict';
  const flightsByWorld=new WeakMap(), previous=new WeakMap();
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const ease=value=>{const t=clamp(value,0,1);return t*t*(3-2*t);};
  function flightFor(data,object) {
    const axis=object.axis||'y',levels=object.stairSteps||8,rise=object.stairRise||4;
    const base=data.elevationAt?.(object.x+object.w/2,object.y+object.h/2)||0;
    const span=axis==='x'?object.w:object.h;
    return {...object,axis,levels,rise,origin:axis==='x'?object.x:object.y,
      run:Number.isFinite(object.stairRun)?clamp(object.stairRun,1,span):span,
      top:object.stairDirection==='down'?base:base+levels*rise,
      bottom:object.stairDirection==='down'?base-levels*rise:base};
  }
  function railLength(data,object,side) {
    if(object.stairRails===false)return 0;
    const run=flightFor(data,object).run;
    const clearance=object.stairEntrySide===side?(object.stairEntryClearance||0):0;
    return clamp(run-clearance,0,run);
  }
  function flights(data) {
    if(!flightsByWorld.has(data)) {
      const list=data.objects.filter(o=>o.type==='stairs').map(o=>flightFor(data,o));
      if(data.terrace) {
        const t=data.terrace;
        list.push({...t,id:'terrace',origin:t.axis==='x'?t.x:t.y,run:t.axis==='x'?t.w:t.h,
          top:t.levels*t.rise,bottom:0});
      }
      flightsByWorld.set(data,list);
    }
    return flightsByWorld.get(data);
  }
  const coordinate=(f,x,y)=>f.axis==='x'?x:y;
  function contains(f,x,y,margin=0) {
    const along=coordinate(f,x,y),across=f.axis==='x'?y:x;
    const start=f.axis==='x'?f.y:f.x,span=f.axis==='x'?f.h:f.w;
    return across>=start&&across<=start+span&&along>=f.origin&&along<=f.origin+f.run+margin;
  }
  function flightAt(data,x,y,smooth=false) {
    return flights(data).find(f=>contains(f,x,y,smooth?Math.min(8,f.run/f.levels*.2):0));
  }
  function treadHeight(f,along) {
    const index=clamp(Math.floor((along-f.origin)/(f.run/f.levels)),0,f.levels);
    return f.top-index*f.rise;
  }
  function walkingHeight(f,along) {
    // Ease over each nosing, never lag behind a step after crossing it.
    const depth=f.run/f.levels,half=Math.min(8,depth*.2);
    let height=f.top;
    for(let i=1;i<=f.levels;i++)height-=f.rise*ease((along-f.origin-i*depth+half)/(half*2));
    return height;
  }
  function groundAt(data,x,y) {
    const flight=flightAt(data,x,y);
    return flight?treadHeight(flight,coordinate(flight,x,y)):(data.elevationAt?.(x,y)||0);
  }
  function heightAt(data,x,y) {
    const flight=flightAt(data,x,y,true);
    return flight?walkingHeight(flight,coordinate(flight,x,y)):(data.elevationAt?.(x,y)||0);
  }
  function resetActor(data,actor) {
    actor.visualZ=heightAt(data,actor.x,actor.y);
    actor.stairMotion={direction:null,lift:0,lean:0};actor.stairFrame=null;
    previous.set(actor,{world:data.id,x:actor.x,y:actor.y,z:actor.visualZ,vx:0,vy:0,direction:null,distance:0,flight:null});
  }
  function updateActor(data,actor,dt) {
    const last=previous.get(actor),dx=last?actor.x-last.x:0,dy=last?actor.y-last.y:0;
    if(!last||last.world!==data.id||Math.hypot(dx,dy)>80) {resetActor(data,actor);return;}
    actor.visualZ=heightAt(data,actor.x,actor.y);
    const flight=flightAt(data,actor.x,actor.y,true),along=flight?(flight.axis==='x'?dx:dy):0;
    const seconds=Math.max(dt,.001),blend=1-Math.exp(-seconds*18);
    const vx=last.vx+(dx/seconds-last.vx)*blend,vy=last.vy+(dy/seconds-last.vy)*blend;
    const speed=flight?(flight.axis==='x'?vx:vy):0,cross=flight?(flight.axis==='x'?vy:vx):0;
    const active=flight&&last.flight===flight.id&&last.direction;
    const heightChange=actor.visualZ-last.z;
    // Hysteresis keeps a small sideways correction from toggling the stair pose.
    const climbing=flight&&actor.moving&&Math.abs(along)>.015&&
      (Math.abs(speed)>=Math.abs(cross)*(active ? .45 : 1.1)||Math.abs(heightChange)>.02);
    const distance=flight&&last.flight===flight.id?last.distance:0;
    let nextDistance=distance,direction=null,lift=0,lean=0;
    if(climbing) {
      nextDistance+=Math.abs(along);
      const stride=Math.max(20,flight.run/flight.levels),phase=nextDistance/stride;
      direction=Math.abs(heightChange)>.02?(heightChange>0?'up':'down'):(speed<0?'up':'down');
      lift=Math.sin(phase*Math.PI)**2*(direction==='up'?1.6:1);
      const screenDx=dx-dy;
      lean=Math.sign(screenDx)*.035;
      actor.stairFrame=Math.floor(phase*2)%4;
    } else actor.stairFrame=null;
    const old=actor.stairMotion||{};
    actor.stairMotion={direction,lift:climbing?lift:(old.lift||0)*(1-blend),
      lean:(old.lean||0)+(lean-(old.lean||0))*blend};
    previous.set(actor,{world:data.id,x:actor.x,y:actor.y,z:actor.visualZ,vx,vy,direction,distance:nextDistance,flight:flight?.id||null});
  }
  function barriers(data) {
    // Side doors enter a flat landing; rails stop before that doorway.
    return data.objects.filter(o=>o.type==='stairs').flatMap(o=>['left','right'].map(side=>({
      x:side==='left'?o.x:o.x+o.w-4,y:o.y,w:4,h:railLength(data,o,side),pad:0,
    })).filter(rail=>rail.h>0));
  }
  window.CampusStairs={flightFor,railLength,flightAt,treadHeight,walkingHeight,groundAt,heightAt,resetActor,updateActor,barriers};
})();
