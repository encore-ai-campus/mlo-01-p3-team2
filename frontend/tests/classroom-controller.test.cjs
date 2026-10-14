const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(subject='python'){
 const nodes={},listeners={},inputs=[],opens=[],commands=[],errors=[];const ctx=new Proxy({},{get:()=>()=>{},set:()=>true});
 for(const id of ['classroomDialog','classroomCanvas','classroomPrompt','classroomAreaHint','classroom-title'])nodes[id]={open:false,events:{},addEventListener(n,fn){this.events[n]=fn;},focus(){},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},getContext(){return ctx;},getBoundingClientRect(){return {width:800,height:600};}};
 let response={type:'learning_open',subject,questionType:'fill_blank'},exited=0;
 const control={setInput(keys){inputs.push([...keys]);},async command(action){commands.push(action);if(response instanceof Error)throw response;return response;}};
 const window={matchMedia:()=>({matches:false}),CampusLearning:{blocking:false,open(type,subject){opens.push({type,subject});}},CampusApp:{toast(message){errors.push(message);}},CampusIsometric:{create(){return {projection:{},draw(){}};}},addEventListener(){}};
 const c=vm.createContext({window,performance:{now:()=>0},document:{getElementById:id=>nodes[id],addEventListener(n,fn){listeners[n]=fn;}}});
 for(const file of ['classroom-map.js','classroom.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../learning/static/learning',file),'utf8'),c);
 const controller=window.CampusClassroom.create({getPlayer:()=>({avatar:'female-2',color:'#91a7a1'}),getControl:()=>control,onExit(){exited++;}});
 const state={subject,actor:{x:320,y:455,dir:'up',moving:false},nearby:null};
 const key=(name,key,extra={})=>listeners[name]({key,preventDefault(){},stopImmediatePropagation(){},target:{closest:()=>false},...extra});
 return {controller,window,nodes,inputs,commands,opens,errors,state,key,setResponse(value){response=value;},get exited(){return exited;}};
}
test('classroom opens from accepted state; keyboard collection cannot invent movement',()=>{
 const f=fixture();f.controller.applyState(f.state);assert.equal(f.controller.actor.avatar,'female-2');assert.equal(f.controller.blocking,true);
 f.key('keydown','d');f.controller.tick(100,.04);assert.deepEqual(f.inputs.at(-1),['d']);assert.equal(f.controller.actor.x,320);
 f.controller.applyState({...f.state,actor:{...f.state.actor,x:350,dir:'right',moving:true}});f.controller.tick(140,.04);assert.ok(f.controller.actor.x>320&&f.controller.actor.x<350);
 f.key('keyup','d');f.controller.applyState(null);assert.equal(f.controller.blocking,false);assert.equal(f.exited,1);
});
test('E opens the type and subject returned by the server and shows rejected interactions',async()=>{
 for(const subject of ['python','sql']){const f=fixture(subject);f.controller.applyState(f.state);f.key('keydown','e');await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(f.opens,[{type:'fill_blank',subject}]);
 f.setResponse(new Error('가까이에서 이용'));f.key('keydown','e');await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(f.errors,['가까이에서 이용']);}
});
test('typing and learning dialogs block movement and repeated E requests',()=>{
 const f=fixture();f.controller.applyState(f.state);f.key('keydown','w',{target:{closest:()=>true}});f.controller.tick(100,.04);assert.deepEqual(f.inputs.at(-1),[]);
 f.key('keydown','e',{repeat:true});assert.equal(f.commands.length,0);f.window.CampusLearning.blocking=true;f.key('keydown','d');f.key('keydown','e');f.controller.tick(140,.04);assert.deepEqual(f.inputs.at(-1),[]);assert.equal(f.commands.length,0);
});
