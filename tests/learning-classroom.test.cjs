const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),sandbox=vm.createContext({window:{}});
for(const name of ['map-data.js','navigation.js'])vm.runInContext(fs.readFileSync(path.join(root,'dist',name),'utf8'),sandbox);
const D=sandbox.window.CampusData;
const source=fs.readFileSync(path.join(root,'dist/campus.js'),'utf8');
const types=new Set(vm.runInNewContext(source.match(/const solidTypes=new Set\((\[[^\n]+?\])\)/)[1]));
const colliders=[...D.walls.map(w=>({x:Math.min(w.x1,w.x2),y:Math.min(w.y1,w.y2),w:Math.abs(w.x2-w.x1),h:Math.abs(w.y2-w.y1),pad:5})),...D.objects.filter(o=>o.solid!==false&&types.has(o.type)).map(o=>({x:o.x+(o.collision?.x??0),y:o.y+(o.collision?.y??0),w:o.collision?.w??o.w,h:o.collision?.h??o.h,pad:0}))];
const inside=(x,y,r)=>x>=r.x&&x<=r.x+r.w&&y>=r.y&&y<=r.y+r.h;
const walkable=(x,y)=>D.rooms.some(r=>inside(x,y,r))&&!colliders.some(r=>Math.max(r.x-x,0,x-r.x-r.w)**2+Math.max(r.y-y,0,y-r.y-r.h)**2<(5.5+r.pad)**2);
test('two existing classroom monitors are independently accessible with unchanged collision',()=>{
 const room=D.rooms.find(r=>r.id==='class1');assert.deepEqual([room.x,room.y,room.w,room.h],[1261.5,553.5,447,393]);
 const pcs=D.objects.filter(o=>o.action==='learning'&&o.roomId==='class1');assert.equal(pcs.length,2);
 assert.deepEqual(Array.from(pcs,o=>o.contentType),['python_multiple_choice','python_fill_blank']);
 assert.equal(D.objects.filter(o=>o.roomId==='class1'&&o.type==='monitor').length,12);
 const nav=sandbox.window.CampusNavigation.create({width:D.width,height:D.height,isWalkable:walkable});
 for(const pc of pcs){
  assert.equal(pc.type,'monitor');assert.equal(pc.solid,false);
  let approach=null;
  for(let x=pc.x-30;x<pc.x+pc.w+30&&!approach;x+=4)for(let y=pc.y-30;y<pc.y+pc.h+30;y+=4){
   const distance=Math.hypot(Math.max(pc.x-x,0,x-pc.x-pc.w),Math.max(pc.y-y,0,y-pc.y-pc.h));
   if(distance<35&&walkable(x,y)&&nav.route({x:1648.5,y:535},{x,y}).length){approach={x,y};break;}
  }
  assert.ok(approach,'reachable approach within unchanged 35-unit interaction distance');
  const desk=D.objects.find(o=>o.roomId==='class1'&&o.type==='desk'&&inside(pc.x,pc.y,o));
  assert.ok(desk);assert.equal(walkable(desk.x+desk.w/2,desk.y+desk.h/2),false);
  console.log(pc.contentType,JSON.stringify({x:pc.x,y:pc.y,w:pc.w,h:pc.h,approach}));
 }
 assert.equal(D.rooms.filter(r=>r.floor==='class'&&r.id!=='class1').length,5);
 assert.ok(source.includes('classroom.shouldEnter(previousPosition,player)'));
});

