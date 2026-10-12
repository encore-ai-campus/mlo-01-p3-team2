const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..');
test('SQL classroom has independent PC identifiers and keeps local walkability and exit',()=>{
 const c=vm.createContext({window:{}});
 for(const f of ['learning/static/learning/classroom-map.js','learning/static/learning/classroom.js','dist/map-data.js'])vm.runInContext(fs.readFileSync(path.join(root,f),'utf8'),c);
 const base=c.window.CampusClassroomMap,sql=base.forSubject('sql');
 assert.equal(sql.data.subject,'sql');assert.equal(base.data.subject,'python');
 for(const pc of sql.data.objects.filter(o=>o.action==='learning')){assert.ok(pc.id.startsWith('sql_'));assert.equal(sql.walkable(...pc.interactionPoint),true);assert.equal(sql.nearby({x:pc.interactionPoint[0],y:pc.interactionPoint[1]}).id,pc.id);}
 assert.equal(base.data.objects.find(o=>o.action==='learning').id,'python_multiple_choice');
 assert.notEqual(sql.data.objects,base.data.objects);assert.equal(sql.nearby({x:320,y:480}).id,'classroom-exit');
 const door=c.window.CampusClassroom.entrance(c.window.CampusData,'class2');
 const x=(door.left+door.right)/2;
 assert.equal(c.window.CampusClassroom.crossedEntrance({floor:'campus',x,y:door.y-1},{floor:'campus',x,y:door.y+1},door),true);
 assert.equal(c.window.CampusClassroom.crossedEntrance({floor:'campus',x:door.left-10,y:door.y-1},{floor:'campus',x:door.left-10,y:door.y+1},door),false);
});

test('main map class2 is SQL classroom with wall sign and unchanged geometry',()=>{
 const c=vm.createContext({window:{}});vm.runInContext(fs.readFileSync(path.join(root,'dist/map-data.js'),'utf8'),c);
 const room=c.window.CampusData.rooms.find(r=>r.id==='class2');assert.equal(room.name,'SQL 학습교실');assert.equal(room.label,false);assert.equal(room.x,792);assert.equal(room.y,553.5);assert.equal(room.w,469.5);assert.equal(room.h,393);
 const sign=c.window.CampusData.objects.find(o=>o.id==='sql-classroom-wall-sign');assert.equal(sign.text,'SQL 학습교실');assert.equal(sign.solid,false);
});
