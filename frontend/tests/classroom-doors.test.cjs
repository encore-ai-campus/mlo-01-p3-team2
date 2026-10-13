const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({window:{}});
for(const name of ['classroom-doors.js','map-data.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),context);
const data=context.window.CampusData,geometry=context.window.CampusDoors,doors=data.objects.filter(o=>o.type==='glass-door');
test('both corridor entries span the same full width as the corridor',()=>{
 const corridor=data.rooms.find(r=>r.id==='corridor');
 for(const x of [corridor.x,corridor.x+corridor.w]){
  const segments=data.walls.filter(w=>w.x1===x&&w.x2===x);
  assert.ok(segments.some(w=>w.y2===corridor.y));assert.ok(segments.some(w=>w.y1===corridor.y+corridor.h));
  assert.ok(segments.every(w=>w.y2<=corridor.y||w.y1>=corridor.y+corridor.h));
 }
 assert.equal(corridor.h,153);
});
test('all seven glass doors swing 90 degrees into their assigned classroom',()=>{
 assert.equal(doors.length,7);
 assert.deepEqual([...new Set(doors.map(o=>o.roomId))].sort(),Array.from(data.rooms.filter(r=>r.floor==='class'),r=>r.id).sort());
 assert.deepEqual(Array.from(doors.filter(o=>o.roomId==='class3-4'),o=>o.id).sort(),['door-class3','door-class4']);
 for(const door of doors){
  const room=data.rooms.find(r=>r.id===door.roomId),closed=geometry.leaf(door,false),opened=geometry.leaf(door,true);
  assert.equal(closed.dx*opened.dx+closed.dy*opened.dy,0);
  assert.equal(Math.hypot(closed.dx,closed.dy),Math.hypot(opened.dx,opened.dy));
  if(door.orientation==='horizontal')assert.equal(closed.start.y,door.swing>0?room.y:room.y+room.h);
  else assert.equal(closed.start.x,room.x+room.w);
  assert.ok(opened.end.x>=room.x&&opened.end.x<=room.x+room.w&&opened.end.y>=room.y&&opened.end.y<=room.y+room.h);
  assert.equal(door.open,false);
 }
});
