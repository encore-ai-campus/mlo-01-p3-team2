const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({window:{}});
for(const name of ['map-data.js','rooftop-data.js','stair-motion.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),context);
const {CampusWorlds:W,CampusStairs:S}=context.window;

test('stairs and the shortcut share the glow while regular extinguishers and rooftop stairs stay unchanged',()=>{
 const up=W.campus.objects.find(o=>o.id==='campus-roof-stairs'),down=W.rooftop.objects.find(o=>o.id==='roof-campus-stairs');
 assert.equal(up.portalGlow,true);assert.equal(Boolean(down.portalGlow),false);
 assert.equal(W.campus.objects.filter(o=>o.type==='floor-portal').length,0);
 assert.equal(W.rooftop.objects.filter(o=>o.type==='floor-portal').length,1);
 assert.equal(W.rooftop.objects.find(o=>o.type==='floor-portal').id,'roof-lounge2-portal');
 const extinguishers=W.campus.objects.filter(o=>o.type==='fire-extinguisher');
 assert.deepEqual(Array.from(extinguishers.filter(o=>o.portalGlow),o=>o.id),['extinguisher-meeting2']);
 const shortcut=W.rooftop.objects.find(o=>o.id==='roof-lounge2-portal');
 assert.equal(shortcut.portalStyle,'compact');assert.equal(shortcut.portalLabel,'18F');
});

test('the shortcut retains confirmation, both arrival positions and its original interaction geometry',()=>{
 const extinguisher=W.campus.objects.find(o=>o.id==='extinguisher-meeting2'),shortcut=W.rooftop.objects.find(o=>o.id==='roof-lounge2-portal');
 assert.equal(extinguisher.confirmTransfer,true);assert.equal(shortcut.confirmTransfer,true);
 assert.equal(extinguisher.toFloor,'rooftop');assert.equal(shortcut.toFloor,'campus');
 assert.deepEqual(Array.from(extinguisher.arrival),[145,1610]);
 assert.deepEqual(Array.from(shortcut.arrival),[529.5,928.5]);
 assert.equal(extinguisher.x,487.5);assert.equal(extinguisher.y,912);
 assert.equal(extinguisher.w,24);assert.equal(extinguisher.h,33);
 assert.equal(W.campus.portals.some(p=>p.objectId===extinguisher.id),false);
 const trigger=W.rooftop.portals.find(p=>p.objectId===shortcut.id);
 assert.equal(trigger.x,119);assert.equal(trigger.y,1584);assert.equal(trigger.w,52);assert.equal(trigger.h,52);
 assert.equal(shortcut.solid,false);
});

test('the advertising stand keeps its footprint',()=>{
 const board=W.rooftop.objects.find(o=>o.id==='roof-ad-board');
 assert.equal(board.imageUrl,'');
 assert.deepEqual([board.x,board.y,board.w,board.h],[2038,1385,24,250]);
});

test('the small portal rests entirely on the treads and remains within interaction reach',()=>{
 const stairs=W.campus.objects.find(o=>o.id==='campus-roof-stairs'),[x,y]=stairs.portalAnchor,radius=12;
 assert.ok(x-radius>=stairs.x&&x+radius<=stairs.x+stairs.w);
 assert.ok(y-radius>=stairs.y&&y+radius<=stairs.y+stairs.stairRun);
 assert.ok(Math.hypot(x-stairs.approach[0],y-stairs.approach[1])<35);
 const flight=S.flightFor(W.campus,stairs);
 assert.ok(S.groundAt(W.campus,x,y)>flight.bottom&&S.groundAt(W.campus,x,y)<flight.top);
});

test('the glow changes neither stair access, transfer targets nor collision geometry',()=>{
 const up=W.campus.objects.find(o=>o.id==='campus-roof-stairs'),trigger=W.campus.portals.find(p=>p.objectId===up.id);
 assert.deepEqual(Array.from(up.arrival),[2325,1565]);
 assert.equal(up.x,2218.5);assert.equal(up.y,829.5);assert.equal(up.w,150);assert.equal(up.h,105);
 assert.equal(trigger.h,25.2);assert.equal(trigger.x,up.x);assert.equal(up.solid,false);
 assert.equal(S.railLength(W.campus,up,'left'),0);assert.equal(S.railLength(W.campus,up,'right'),0);
 assert.ok(up.approach[0]>=trigger.x&&up.approach[0]<=trigger.x+trigger.w);
 assert.ok(up.approach[1]>=trigger.y&&up.approach[1]<=trigger.y+trigger.h);
});
