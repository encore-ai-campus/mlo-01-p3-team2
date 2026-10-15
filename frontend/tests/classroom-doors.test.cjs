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
test('classroom entrances stay open and the storage sliding door remains operable',()=>{
 assert.equal(doors.length,0);
 const storage=data.objects.find(o=>o.id==='door-storage');
 assert.ok(storage && storage.type==='sliding-door' && geometry.isDoor(storage));
 const closed=geometry.footprint(storage,false),opened=geometry.footprint(storage,true);
 assert.notDeepEqual(closed,opened);
 assert.equal(closed.w,opened.w);assert.equal(closed.h,opened.h);
});
