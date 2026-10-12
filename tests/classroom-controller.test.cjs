const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..');
function setup(spawn){
 const listeners={},nodes={},draws=[],opens=[],subjects=[],exits=[];
 const ctx=new Proxy({},{get:()=>()=>{},set:()=>true});
 for(const id of ['classroomDialog','classroomCanvas','classroomPrompt'])nodes[id]={open:false,addEventListener(name,fn){(this.events??={})[name]=fn;},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;this.events?.close?.();},getContext(){return ctx;},getBoundingClientRect(){return {width:800,height:600};}};
 const c=vm.createContext({window:{devicePixelRatio:1,addEventListener(){},CampusLearning:{blocking:false,open(type,subject){subjects.push(subject);opens.push(type);this.blocking=true;}}},document:{getElementById:id=>nodes[id],addEventListener(name,fn){(listeners[name]??=[]).push(fn);}},performance:{now:()=>0}});
 for(const file of ['dist/map-data.js','dist/isometric.js','learning/static/learning/classroom-map.js','learning/static/learning/classroom.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),c);
 for(const door of c.window.CampusData.objects.filter(o=>o.type==='glass-door'))door.open=true;
 const projection=c.window.CampusIsometric.createProjection(c.window.CampusClassroomMap.data);
 c.window.CampusIsometric.create=()=>({projection,draw(_,options){draws.push({...options.actors[0]});}});
 if(spawn)c.window.CampusClassroomMap.data.spawn=spawn;
 const player={avatar:'female-2',dir:'down',x:1649,y:552,floor:'campus'};
 const controller=c.window.CampusClassroom.create({data:c.window.CampusData,getPlayer:()=>player,onOpen(){},onExit(point){exits.push(point);}});
 const key=(name,value,repeat=false)=>listeners[name].forEach(fn=>fn({key:value,repeat,preventDefault(){},target:{closest:()=>null}}));
 return {c,nodes,draws,opens,subjects,exits,player,controller,key};
}
test('classroom reuses selected avatar, screen-facing WASD movement and pauses without losing position',()=>{
 const s=setup();s.controller.open();const initial=s.draws.at(-1);assert.equal(initial.avatar,'female-2');
 s.key('keydown','w');s.controller.tick(40,.04);const moved=s.draws.at(-1);assert.equal(moved.x,initial.x);assert.ok(moved.y<initial.y);assert.equal(moved.dir,'up');
 s.c.window.CampusLearning.blocking=true;s.controller.tick(80,.04);assert.equal(s.draws.at(-1).x,moved.x);assert.equal(s.draws.at(-1).y,moved.y);
 s.c.window.CampusLearning.blocking=false;s.controller.focus();s.controller.tick(120,.04);assert.equal(s.draws.at(-1).x,moved.x);
 assert.equal(s.player.x,1649);assert.equal(s.player.y,552);
});
test('far E and canvas clicks never start learning; near E opens the correct API panel',()=>{
 const far=setup([320,380]);far.controller.open();far.key('keydown','e');far.nodes.classroomCanvas.events.pointerdown();assert.equal(far.opens.length,0);
 for(const [point,type] of [[[220,220],'multiple_choice'],[[540,220],'fill_blank']]){const s=setup(point);s.controller.open();s.key('keydown','e',true);assert.equal(s.opens.length,0);s.key('keydown','e');assert.deepEqual(s.opens,[type]);}
});
test('exit requires proximity and down arrow, closes classroom and returns outside main door',()=>{
 const s=setup([320,480]);s.controller.open();assert.equal(s.controller.blocking,true);s.key('keydown','ArrowDown');assert.equal(s.controller.blocking,false);assert.equal(s.exits.length,1);assert.equal(s.exits[0].y,s.controller.door.y-18);
});
test('popup input, E and Enter cannot move or start another interaction',()=>{
 const s=setup([220,220]);s.controller.open();s.key('keydown','e');s.key('keydown','a');s.key('keydown','e');s.key('keydown','Enter');s.controller.tick(40,.04);assert.deepEqual(s.opens,['multiple_choice']);assert.equal(s.draws.at(-1).x,220);assert.equal(s.draws.at(-1).y,220);
});

test('down arrow exits near doorway, but only moves elsewhere and is blocked during learning',()=>{
 const near=setup([320,480]);near.controller.open();near.key('keydown','ArrowDown');assert.equal(near.exits.length,1);assert.equal(near.controller.blocking,false);
 const far=setup([320,380]);far.controller.open();far.key('keydown','ArrowDown');assert.equal(far.exits.length,0);far.controller.tick(40,.04);assert.ok(far.draws.at(-1).y>380);
 const learning=setup([320,480]);learning.controller.open();learning.c.window.CampusLearning.blocking=true;learning.key('keydown','ArrowDown');assert.equal(learning.exits.length,0);
});

test('class2 doorway selects SQL API subject and E exit returns outside its own door',()=>{
 const s=setup([540,220]);
 const door=s.c.window.CampusClassroom.entrance(s.c.window.CampusData,'class2');const x=(door.left+door.right)/2;
 assert.equal(s.controller.shouldEnter({floor:'campus',x,y:door.y-1},{floor:'campus',x,y:door.y+1}),true);
 s.controller.open();s.key('keydown','e');assert.deepEqual(s.opens,['fill_blank']);assert.deepEqual(s.subjects,['sql']);
 const e=setup([320,480]);assert.equal(e.controller.shouldEnter({floor:'campus',x,y:door.y-1},{floor:'campus',x,y:door.y+1}),true);
 e.controller.open();e.key('keydown','e');assert.equal(e.controller.blocking,false);assert.equal(e.exits[0].x,x);assert.equal(e.exits[0].y,door.y-18);
});

test('E anywhere within either painted zone opens the matching Python or SQL type',()=>{
 for(const subject of ['python','sql'])for(const [point,type] of [[[180,280],'multiple_choice'],[[490,280],'fill_blank'],[[75,405],'multiple_choice'],[[585,405],'fill_blank']]){
  const s=setup(point);
  if(subject==='sql'){const door=s.c.window.CampusClassroom.entrance(s.c.window.CampusData,'class2'),x=(door.left+door.right)/2;s.controller.shouldEnter({floor:'campus',x,y:door.y-1},{floor:'campus',x,y:door.y+1});}
  s.controller.open();s.key('keydown','e');assert.deepEqual(s.opens,[type]);assert.deepEqual(s.subjects,[subject]);
 }
 for(const point of [[69,280],[271,280],[389,280],[591,280],[180,144],[180,414]]){const s=setup(point);s.controller.open();s.key('keydown','e');assert.equal(s.opens.length,0);}
});

test('closed glass doors prevent Python/SQL entry; opening enables normal crossing',()=>{
 for(const roomId of ['class1','class2']){
  const s=setup(),door=s.c.window.CampusClassroom.entrance(s.c.window.CampusData,roomId),x=(door.left+door.right)/2;
  const gate=s.c.window.CampusData.objects.find(o=>o.id==='door-'+roomId);
  const before={floor:'campus',x,y:door.y-1},after={floor:'campus',x,y:door.y+1};
  gate.open=false;assert.equal(s.controller.shouldEnter(before,after),false);
  gate.open=true;assert.equal(s.controller.shouldEnter(before,after),true);
 }
});
