const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),ctx=vm.createContext({window:{}});
for(const file of ['dist/map-data.js','learning/static/learning/classroom.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),ctx);
const api=ctx.window.CampusClassroom,door=api.entrance(ctx.window.CampusData),center=(door.left+door.right)/2;
test('class1 entrance is derived from actual top-wall gap',()=>{
 assert.deepEqual([door.left,door.right,door.y],[1617,1681.5,553.5]);
 const before={floor:'campus',x:center,y:door.y-3},after={floor:'campus',x:center,y:door.y+3};
 assert.equal(api.crossedEntrance(before,after,door),true);
 assert.equal(api.crossedEntrance(before,{...after,y:door.y-1},door),false);
 assert.equal(api.crossedEntrance({...before,x:door.left-10},{...after,x:door.left-10},door),false);
 assert.equal(api.crossedEntrance(after,before,door),false);
 assert.equal(api.crossedEntrance(after,after,door),false);
 assert.equal(api.crossedEntrance({...before,floor:'rooftop'},{...after,floor:'rooftop'},door),false);
 const exit={floor:'campus',x:center,y:door.y-18};assert.equal(api.crossedEntrance(exit,exit,door),false);
});
