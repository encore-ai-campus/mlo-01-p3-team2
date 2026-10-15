const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({window:{}});
for(const name of ['classroom-doors.js','map-data.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),context);
const D=context.window.CampusData,door=D.objects.find(o=>o.id==='door-storage');
const overlap=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
test('storage threshold is clear of boxes, cabinets and the printer partition',()=>{
 const threshold=context.window.CampusDoors.footprint(door,false);
 for(const o of D.objects.filter(o=>['cabinet','box'].includes(o.type)))assert.equal(overlap(o,threshold),false);
 const walls=D.walls.filter(w=>w.y1===126&&w.y2===126);
 assert.ok(walls.every(w=>w.x2<=threshold.x||w.x1>=threshold.x+threshold.w));
 const printer=D.objects.find(o=>o.type==='printer');assert.ok(walls.every(w=>w.x2<=printer.x||w.x1>=printer.x+printer.w));
});
test('lounge seating remains separated from the front wall and nearby furniture',()=>{
 const sofa=D.objects.find(o=>o.type==='sofa'&&o.dir==='up'&&o.roomId==='lounge1');
 assert.ok(946.5-(sofa.y+sofa.h)>=45);
 for(const o of D.objects.filter(o=>['coffee','ottoman','woodwall'].includes(o.type)))assert.equal(overlap(sofa,o),false);
 const wood=D.objects.find(o=>o.type==='woodwall');assert.ok(wood.x>1708.5+10);
});
test('classroom prompts, old panels and glass doors are removed while the PLAYDATA board remains',()=>{
 assert.equal(D.objects.filter(o=>o.type==='board').length,0);
 for(const room of D.rooms.filter(r=>r.floor==='class')){
  assert.equal(room.info,false);assert.equal(room.label,false);
 }
 assert.equal(D.objects.filter(o=>o.type==='glass-door').length,0);
 assert.ok(D.objects.find(o=>o.id==='class3-4-noticeboard').mounted);
});

test('consultation tables, monitors and chairs fit inside their rooms with separate footprints',()=>{
 for(const room of D.rooms.filter(r=>r.id.startsWith('consult-'))){
  const desk=D.objects.find(o=>o.type==='desk'&&o.roomId===room.id);
  assert.ok(desk.x>=room.x+30&&desk.x+desk.w<=room.x+room.w-12);
  assert.ok(desk.y>=room.y+30&&desk.y+desk.h<=room.y+room.h-40);
  const monitor=D.objects.find(o=>o.type==='monitor'&&o.x>=desk.x&&o.x+o.w<=desk.x+desk.w&&o.y>=desk.y&&o.y+o.h<=desk.y+desk.h);
  assert.ok(monitor,'The display belongs completely on the tabletop');
  for(const chair of D.objects.filter(o=>o.type==='chair'&&o.x>=room.x&&o.x<room.x+room.w&&o.y>=room.y&&o.y<room.y+room.h))assert.equal(overlap(chair,desk),false);
 }
});
