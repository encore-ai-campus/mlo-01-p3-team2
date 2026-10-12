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
test('opening frees the doorway while keeping the glass leaf solid; occupied thresholds cannot close',()=>{
 for(const door of doors){
  const closed=geometry.footprint(door,false),center={floor:'campus',x:closed.x+closed.w/2,y:closed.y+closed.h/2};
  assert.equal(geometry.blocked(door,false,[center]),true);
  assert.equal(geometry.blocked(door,true,[center]),false);
  const open=geometry.footprint(door,true),leafCenter={floor:'campus',x:open.x+open.w/2,y:open.y+open.h/2};
  assert.equal(geometry.blocked(door,true,[leafCenter]),true);
  assert.equal(geometry.blocked(door,false,[{...center,floor:'rooftop'}]),false);
 }
});
test('storage door slides parallel to its wall, clears the threshold and blocks occupied closing',()=>{
 const door=data.objects.find(o=>o.id==='door-storage'),closed=geometry.leaf(door,false),opened=geometry.leaf(door,true);
 assert.equal(geometry.isDoor(door),true);
 assert.equal(geometry.isDoor(data.objects.find(o=>o.type==='sliding-door'&&!o.interactiveDoor)),false);
 assert.equal(door.roomId,'storage');assert.equal(door.open,false);
 assert.equal(closed.dx,opened.dx);assert.equal(closed.dy,opened.dy);assert.ok(opened.start.x>closed.end.x);
 const opening=geometry.footprint(door,false),center={floor:'campus',x:opening.x+opening.w/2,y:opening.y+opening.h/2};
 assert.equal(geometry.blocked(door,false,[center]),true);assert.equal(geometry.blocked(door,true,[center]),false);
 assert.equal(geometry.distance({...door,open:true},center.x,center.y),0);
 const room=data.rooms.find(r=>r.id==='storage'),park=geometry.footprint(door,true);
 assert.ok(park.x+park.w<room.x+room.w);
 const bounds=geometry.bounds(door);assert.ok(bounds.x<=opening.x&&bounds.x+bounds.w>=park.x+park.w);
});
