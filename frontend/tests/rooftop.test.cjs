const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sandbox=vm.createContext({window:{}});
for(const name of ['map-data.js','rooftop-data.js','isometric.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),sandbox);
const worlds=sandbox.window.CampusWorlds,roof=worlds.rooftop;
test('stairs connect both floors and arrive outside the reverse trigger',()=>{
  for(const data of Object.values(worlds))for(const portal of data.portals){
    const object=data.objects.find(o=>o.id===portal.objectId),destination=worlds[object.toFloor],[x,y]=object.arrival;
    assert.ok(destination&&x>0&&y>0&&x<destination.width&&y<destination.height);
    assert.ok(destination.rooms.some(r=>x>=r.x&&x<=r.x+r.w&&y>=r.y&&y<=r.y+r.h));
    assert.ok(!destination.portals.some(p=>x>=p.x&&x<=p.x+p.w&&y>=p.y&&y<=p.y+p.h));
    assert.ok(object.approach[0]>=portal.x&&object.approach[0]<=portal.x+portal.w&&object.approach[1]>=portal.y&&object.approach[1]<=portal.y+portal.h);
  }
});
test('central vertical terrace divides equal areas with three aligned open booths',()=>{
  assert.equal(roof.rooms.filter(r=>r.id.startsWith('festival-')).length,3);
  const booths=roof.objects.filter(o=>o.type==='exhibition-booth');
  assert.equal(booths.length,3);
  assert.equal(new Set(booths.map(o=>o.x)).size,1,'booth backs must share a floor line');
  const P=sandbox.window.CampusIsometric.createProjection(roof),axis=P.vector(0,1);
  const centers=booths.map(o=>P.project(o.x+o.w/2,o.y+o.h/2,roof.elevationAt(o.x,o.y)));
  for(let i=1;i<booths.length;i++){
    assert.ok(booths[i].y-booths[i-1].y>440,'the long floor row must have wide spacing');
    const dx=centers[i].x-centers[i-1].x,dy=centers[i].y-centers[i-1].y;
    assert.ok(Math.abs(dx*axis.y-dy*axis.x)<1e-8,'projected row must follow the rotated floor axis');
    assert.ok(Math.abs(dy)>100,'the floor row must retain the rotated perspective');
  }
  assert.ok(booths.every(o=>o.entrance==='right'&&o.rotation===90&&o.x+o.w<roof.terrace.x&&o.solid===false&&o.collision.w===9));
  const t=roof.terrace,upper=roof.surfaces[0],lower=roof.surfaces.at(-1);
  const rowCenter={x:booths[0].x+booths[0].w/2,y:(booths[0].y+booths.at(-1).y+booths.at(-1).h)/2};
  assert.ok(Math.abs(rowCenter.x-(upper.x+upper.w/2))<2,'booth row must be centered across the upper plaza');
  assert.ok(Math.abs(rowCenter.y-(upper.y+upper.h/2))<2,'booth row must have balanced margins along the floor');
  assert.ok(t.h>t.w*3);assert.equal(t.axis,'x');assert.equal(lower.w,upper.w);
  const fromLowerEnd=(lower.x+lower.w-(t.x+t.w/2))/(lower.x+lower.w-upper.x);
  assert.equal(fromLowerEnd,.5);
  assert.equal(t.levels,8);assert.equal(t.rise,12);assert.equal(roof.elevationAt(500,950),96);assert.equal(roof.elevationAt(1500,950),0);
  for(let i=0;i<t.levels;i++)assert.equal(roof.elevationAt(t.x+(i+.5)*t.w/t.levels,950),(t.levels-i)*t.rise);
  assert.ok(!roof.objects.some(o=>o.id==='roof-menu-board'||o.source==='menu'));
  assert.equal(roof.objects.filter(o=>o.type==='plaza-display').length,1);
  const tall=roof.walls.filter(w=>(w.height||roof.wallHeight)>roof.wallHeight);
  assert.equal(tall.length,1);assert.equal(tall[0].height,420);assert.equal(tall[0].topZ,420);
  assert.equal(tall[0].y1,tall[0].y2);assert.equal(tall[0].y1,64);
  assert.equal(tall[0].x1,64);assert.equal(tall[0].x2,2384);
  assert.ok(!roof.walls.some(w=>w.x1===2384&&w.x2===2384&&w.height>roof.wallHeight));
  for(const x of [64,1044,1089,1224,1404,2384]){
    const q=P.project(x,64,tall[0].topZ+4);
    assert.ok(q.y>15&&q.y<P.height,'wall over both landings and stairs must not be cropped');
    assert.ok(tall[0].topZ-roof.elevationAt(x,64)>300,'wall must stay tall above every tier');
  }
});
test('extinguisher shortcut touches classroom 5 wall and arrives at screen-left rooftop',()=>{
  const o=worlds.campus.objects.find(o=>o.id==='extinguisher-meeting2');
  assert.equal(o.x,487.5);assert.equal(o.y,912);assert.equal(o.toFloor,'rooftop');
  assert.equal(o.confirmTransfer,true);
  assert.deepEqual(Array.from(o.arrival),[145,1610]);
  assert.ok(!worlds.campus.portals.some(p=>p.objectId===o.id));
  const P=sandbox.window.CampusIsometric.createProjection(roof),q=P.project(...o.arrival,96);
  assert.ok(q.x<P.width*.15);
  const back=roof.objects.find(o=>o.id==='roof-lounge2-portal'),trigger=roof.portals.find(p=>p.objectId===back.id);
  assert.equal(back.toFloor,'campus');assert.equal(back.confirmTransfer,true);assert.equal(back.solid,false);
  assert.deepEqual(Array.from(back.approach),Array.from(o.arrival));
  assert.ok(o.arrival[0]>=trigger.x&&o.arrival[0]<=trigger.x+trigger.w&&o.arrival[1]>=trigger.y&&o.arrival[1]<=trigger.y+trigger.h);
  assert.ok(Math.hypot(back.arrival[0]-(o.x+o.w),back.arrival[1]-(o.y+o.h/2))<35);
});
test('all three booth centers have usable interaction points outside their furniture',()=>{
  const actions=roof.objects.filter(o=>o.action==='booth');assert.equal(actions.length,3);
  for(const action of actions){
    const shell=roof.objects.find(o=>o.roomId===action.roomId&&o.type==='exhibition-booth');
    const [x,y]=action.interactionPoint;assert.equal(x,shell.x+shell.w/2);assert.equal(y,shell.y+shell.h/2);
    for(const o of roof.objects.filter(o=>o.solid!==false)){
      const r=o.collision?{x:o.x+o.collision.x,y:o.y+o.collision.y,w:o.collision.w,h:o.collision.h}:o;
      const distance=Math.hypot(Math.max(r.x-x,0,x-r.x-r.w),Math.max(r.y-y,0,y-r.y-r.h));
      assert.ok(distance>5.5,action.id+' must not be inside '+o.id);
    }
  }
});
test('every raised surface stays inside the clockwise map and has a consistent elevation',()=>{
  const P=sandbox.window.CampusIsometric.createProjection(roof);
  for(const surface of roof.surfaces){const x=surface.x+surface.w/2,y=surface.y+surface.h/2,q=P.project(x,y,surface.z),back=P.unproject(q.x,q.y+surface.z);
    assert.equal(roof.elevationAt(x,y),surface.z);assert.ok(Math.abs(back.x-x)<1e-8&&Math.abs(back.y-y)<1e-8);
    assert.ok(q.x>0&&q.y>0&&q.x<P.width&&q.y<P.height);
  }
});
