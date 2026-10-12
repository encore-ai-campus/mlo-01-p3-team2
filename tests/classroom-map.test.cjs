const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(root,'learning/static/learning/classroom-map.js'),'utf8'),c);
const m=c.window.CampusClassroomMap;
test('independent map has one room, two individually placed PCs and reachable spawn/interaction points',()=>{
 assert.equal(m.data.id,'python-classroom');assert.equal(m.data.rooms.length,1);
 assert.equal(m.walkable(...m.data.spawn),true);
 for(const pc of m.data.objects.filter(o=>o.action==='learning')){assert.equal(m.walkable(...pc.interactionPoint),true);assert.equal(m.nearby({x:pc.interactionPoint[0],y:pc.interactionPoint[1]}).id,pc.id);}
 assert.equal(m.nearby({x:320,y:380}),null);assert.equal(m.nearby({x:320,y:480}).id,'classroom-exit');
});
test('wall and furniture collision blocks tunnelling but permits aisle sliding',()=>{
 assert.equal(m.walkable(10,200),false);assert.equal(m.walkable(110,185),false);assert.equal(m.walkable(110,235),false);
 const a={x:110,y:150};m.move(a,0,200);assert.ok(a.y<=163);
 const b={x:320,y:455};m.move(b,1000,0);assert.ok(b.x<=617);assert.equal(m.walkable(b.x,b.y),true);
 const d={x:160,y:220};m.move(d,0,80);assert.ok(d.y>280);assert.equal(m.walkable(d.x,d.y),true);
});
test('both PC approach points can be reached from spawn using floor aisles',()=>{
 for(const target of m.data.objects.filter(o=>o.action==='learning')){
  const step=5,queue=[[320,455]],seen=new Set(['320,455']);let found=false;
  for(let i=0;i<queue.length;i++){
   const [x,y]=queue[i];if(Math.hypot(x-target.interactionPoint[0],y-target.interactionPoint[1])<20){found=true;break;}
   for(const [dx,dy] of [[step,0],[-step,0],[0,step],[0,-step]]){const a=x+dx,b=y+dy,k=a+','+b;if(!seen.has(k)&&m.walkable(a,b)){seen.add(k);queue.push([a,b]);}}
  }
  assert.equal(found,true,target.id);
 }
});

test('all eight visible PCs work from reachable desk-front positions, including lower-left screenshot location',()=>{
 const pcs=m.data.objects.filter(o=>o.action==='learning');assert.equal(pcs.length,8);
 for(const pc of pcs){assert.equal(m.walkable(...pc.interactionPoint),true,pc.id);assert.equal(m.nearby({x:pc.interactionPoint[0],y:pc.interactionPoint[1]}).id,pc.id);}
 assert.equal(m.nearby({x:135,y:348}).contentType,'multiple_choice');
 assert.equal(m.nearby({x:455,y:348}).contentType,'fill_blank');
 assert.equal(m.nearby({x:320,y:380}),null);
});
