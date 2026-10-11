const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

function setup(){
  let now=0,ending=false;
  const timers=[],frames=[],events=[],listeners={};
  const dialog={open:false,addEventListener(name,fn){listeners[name]=fn;},showModal(){this.open=true;},close(){this.open=false;},focus(){}};
  const sandbox={window:{dispatchEvent:event=>events.push(event.type)},document:{getElementById:()=>dialog},Event,
    setTimeout(fn,delay){timers.push({fn,at:now+delay});},requestAnimationFrame:fn=>frames.push(fn)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/floor-transition.js'),'utf8'),sandbox);
  let starts=0,finishes=0;
  const transition=sandbox.window.CampusFloorTransition.create({onStart:()=>starts++,onFinish:()=>finishes++,isCancelled:()=>ending});
  return {transition,dialog,events,listeners,get starts(){return starts;},get finishes(){return finishes;},
    endSession(){ending=true;},async advance(ms){now+=ms;for(const timer of timers.filter(t=>t.at<=now&&!t.done)){timer.done=true;timer.fn();}await Promise.resolve();},
    async paint(){for(const fn of frames.splice(0))fn();await Promise.resolve();}};
}

test('floor changes wait 3 seconds, block duplicate requests, and reveal after destination paint',async()=>{
  const h=setup();let commits=0;
  const result=h.transition.run(()=>{commits++;return true;});
  assert.equal(h.transition.blocking,true);assert.equal(h.dialog.open,true);
  assert.equal(await h.transition.run(()=>{throw Error('Duplicate must not run');}),false);
  await h.advance(2999);assert.equal(commits,0);assert.equal(h.dialog.open,true);
  await h.advance(1);assert.equal(commits,1);assert.equal(h.dialog.open,true);
  await h.paint();assert.equal(await result,true);assert.equal(h.transition.blocking,false);assert.equal(h.dialog.open,false);
  assert.equal(h.starts,1);assert.equal(h.finishes,1);assert.deepEqual(h.events,['campus:floor-transition-end']);
});
test('session expiry during loading prevents a late floor change and releases the screen',async()=>{
  const h=setup();let commits=0;
  const result=h.transition.run(()=>++commits);
  h.endSession();await h.advance(3000);
  assert.equal(await result,false);assert.equal(commits,0);assert.equal(h.dialog.open,false);assert.equal(h.transition.blocking,false);
  assert.equal(await h.transition.run(()=>++commits),false);assert.equal(h.starts,1);
});
test('Escape cannot dismiss the transition, and a failed map change releases input',async()=>{
  const h=setup();let prevented=false;
  const result=h.transition.run(()=>{throw Error('Map unavailable');});
  const rejection=assert.rejects(result,/Map unavailable/);
  h.listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(h.dialog.open,true);
  await h.advance(3000);await rejection;
  assert.equal(h.dialog.open,false);assert.equal(h.transition.blocking,false);assert.equal(h.finishes,1);
});
