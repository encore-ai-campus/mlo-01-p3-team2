const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..');
test('procedural classroom assets integrate with real sprite cache, depth rendering and attached PC monitors',()=>{
 const calls=[];
 const context=new Proxy({measureText:text=>({width:text.length*7}),createLinearGradient:()=>({addColorStop(){}})},{get(target,name){return target[name]??(()=>{});},set(target,name,value){target[name]=value;return true;}});
 const c=vm.createContext({window:{CampusAvatars:{size:40,draw:()=>true}},document:{createElement:()=>({getContext:()=>context})}});
 for(const file of ['dist/stair-motion.js','dist/isometric.js','learning/static/learning/classroom-assets.js','learning/static/learning/classroom-map.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),c);
 const data=c.window.CampusClassroomMap.data,paint=data.paintFurniture;
 data.paintFurniture=(object,api,z)=>{calls.push(object.id);return paint(object,api,z);};
 const renderer=c.window.CampusIsometric.create({data});
 renderer.draw(context,{camera:{zoom:1,x:0,y:0},actors:[{x:320,y:455,avatar:'male-1'}],viewportWidth:1200,viewportHeight:900});
 for(const id of ['python-board','teacher-desk','python_multiple_choice','python_fill_blank','student-0-0-chair','books-left','plant-0','entry-threshold','entry-left-post'])assert.ok(calls.includes(id),id);
 assert.equal(paint({classroomAsset:false},{},0),false);
 assert.equal(paint({classroomAsset:true,type:'laptop',x:0,y:0,w:10,h:10},{shadow(){}},0),false);
});
