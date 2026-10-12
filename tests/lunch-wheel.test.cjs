const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../dist/lunch-wheel.js'),'utf8');
function fixture({reduced=false}={}){
 const element=()=>({style:{},dataset:{},children:[],listeners:{},textContent:'',disabled:false,
  replaceChildren(){this.children=[];},append(child){this.children.push(child);},setAttribute(){},
  addEventListener(name,callback){this.listeners[name]=callback;},getBoundingClientRect(){return {};},
 });
 const wheel=element(),button=element(),choice=element(),message=element(),legend=element(),root=element(),classes=new Set(),timers=new Map();
 const fields={'[data-lunch-wheel]':wheel,'[data-lunch-spin]':button,'[data-lunch-choice]':choice,'[data-lunch-message]':message,'[data-lunch-options]':legend};
 root.querySelector=selector=>fields[selector];root.closest=selector=>selector==='[hidden]'&&root.hidden?root:null;
 root.classList={add:value=>classes.add(value),remove:value=>classes.delete(value)};
 const window={matchMedia:()=>({matches:reduced}),setTimeout:(callback,delay)=>{const key={};timers.set(key,{callback,delay});return key;},clearTimeout:key=>timers.delete(key)};
 const document={getElementById:()=>root,createElement:element,createElementNS:element};
 vm.runInNewContext(source,{window,document,Uint32Array,Math});
 const samples=[];const api=window.CampusLunchWheel.create({root,random:()=>{assert.ok(samples.length,'random draws must not occur while blocked');return samples.shift();}});
 return {root,wheel,button,choice,message,legend,classes,timers,api,samples,options:Array.from(window.CampusLunchWheel.options),finish(){wheel.listeners.transitionend({target:wheel,propertyName:'transform'});}};
}

test('every equal-probability outcome lands its matching slice under the fixed pointer, including repeat spins and jitter limits',()=>{
 const f=fixture(),wanted=['한식','일식','양식','중식','분식','패스트푸드','베트남음식','구내식당'];
 assert.deepEqual(f.options,wanted);
 for(let index=0;index<8;index++)for(const jitter of [0,.999999]){
  f.samples.push((index+.5)/8,jitter,.6);
  assert.equal(f.api.spin(),true);assert.equal(f.button.disabled,true);
  const target=Number(f.wheel.style.transform.match(/rotate\((.+)deg\)/)[1]);
  const pointerAngle=((-target%360)+360)%360;
  assert.equal(Math.round(pointerAngle/45)%8,index,'visual pointer must match the selected category');
  assert.ok(target-f.api.rotation>=5*360,'the wheel must make multiple complete turns');
  f.finish();assert.equal(f.api.choice,wanted[index]);assert.equal(f.choice.textContent,wanted[index]);
  assert.equal(f.api.rotation,target);assert.equal(f.button.disabled,false);assert.equal(f.timers.size,0);
 }
});

test('duplicate clicks cannot change an in-flight choice and unrelated transitions cannot end the spin',()=>{
 const f=fixture();f.samples.push(.2,.5,.2);f.api.spin();
 const target=f.wheel.style.transform;
 assert.equal(f.api.spin(),false);assert.equal(f.wheel.style.transform,target);
 f.wheel.listeners.transitionend({target:f.wheel,propertyName:'opacity'});
 assert.equal(f.api.spinning,true);assert.equal(f.api.choice,null);f.finish();assert.equal(f.api.choice,'일식');
});

test('closing cancels timers and preserves the previous completed result; a hidden card cannot spin',()=>{
 const f=fixture();f.samples.push(.9,.5,.5);f.api.spin();f.finish();
 const rotation=f.api.rotation;f.samples.push(.1,.5,.5);f.api.spin();
 const pending=[...f.timers.values()][0].callback;f.api.cancel();
 assert.equal(f.api.spinning,false);assert.equal(f.button.disabled,false);assert.equal(f.timers.size,0);
 assert.equal(f.wheel.style.transform,`rotate(${rotation}deg)`);assert.equal(f.api.choice,'구내식당');
 pending();assert.equal(f.api.choice,'구내식당');
 f.root.hidden=true;assert.equal(f.api.spin(),false);assert.equal(f.classes.has('is-spinning'),false);
});

test('reduced motion shortens the animation and the timer still resolves when a transition event is unavailable',()=>{
 const f=fixture({reduced:true});f.samples.push(.5,.5,.5);f.api.spin();
 assert.ok(f.wheel.style.transition.includes('500ms'));
 const timer=[...f.timers.values()][0];assert.equal(timer.delay,600);timer.callback();
 assert.equal(f.api.spinning,false);assert.equal(f.api.choice,'분식');assert.equal(f.button.disabled,false);
});
