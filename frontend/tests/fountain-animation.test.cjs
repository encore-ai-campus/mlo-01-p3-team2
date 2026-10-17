const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(reduced){
 const strokes=[];
 const g=new Proxy({measureText:t=>({width:t.length*7}),createLinearGradient:()=>({addColorStop(){}}),createRadialGradient:()=>({addColorStop(){}}),bezierCurveTo:(...args)=>strokes.push(['jet',...args]),ellipse:(...args)=>strokes.push(['water',...args])},{get:(o,k)=>o[k]??(()=>{}),set:(o,k,v)=>(o[k]=v,true)});
 const c=vm.createContext({window:{matchMedia:()=>({matches:reduced})},document:{createElement:()=>({getContext:()=>g})}});
 for(const f of ['stair-motion.js','map-data.js','rooftop-data.js','isometric.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',f),'utf8'),c);
 const roof=c.window.CampusWorlds.rooftop,data={...roof,objects:roof.objects.filter(o=>o.type==='fountain'),walls:[],portals:[]};
 const renderer=c.window.CampusIsometric.create({data}),before=JSON.stringify(data);
 function frame(t){strokes.length=0;renderer.draw(g,{camera:{zoom:1,x:0,y:0},actors:[],t,viewportWidth:10000,viewportHeight:10000});return JSON.stringify(strokes);}
 return {frame,data,before};
}
test('fountain water changes with elapsed time without modifying basin, map or collision data',()=>{
 const s=setup(false);assert.notEqual(s.frame(0),s.frame(500));assert.equal(JSON.stringify(s.data),s.before);
});
test('reduced motion keeps water still and nonfinite frame time remains safe',()=>{
 const s=setup(true);assert.equal(s.frame(0),s.frame(500));assert.equal(s.frame(0),s.frame(NaN));
});
