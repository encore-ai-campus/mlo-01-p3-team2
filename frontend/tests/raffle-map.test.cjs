const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({window:{}});
for(const file of ['map-data.js','rooftop-data.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',file),'utf8'),context);
const roof=context.window.CampusWorlds.rooftop;
test('event buzzer can be approached without blocking stairs or fountain paths',()=>{
  const buzzer=roof.objects.find(o=>o.id==='roof-event-buzzer');
  const [x,y]=buzzer.interactionPoint;
  assert.equal(buzzer.action,'raffle');
  assert.equal(roof.elevationAt(x,y),0);
  for(const o of roof.objects.filter(o=>o.solid===true)){
    const r=o.collision?{x:o.x+o.collision.x,y:o.y+o.collision.y,w:o.collision.w,h:o.collision.h}:o;
    const distance=Math.hypot(Math.max(r.x-x,0,x-r.x-r.w),Math.max(r.y-y,0,y-r.y-r.h));
    assert.ok(distance>=5.5,`${o.id} blocks the E interaction point`);
  }
  assert.ok(!roof.portals.some(p=>x>=p.x&&x<=p.x+p.w&&y>=p.y&&y<=p.y+p.h));
  const server=fs.readFileSync(path.join(__dirname,'../../backend/raffle/service.py'),'utf8');
  assert.ok(server.includes(`BUZZER_POINT = (${x}, ${y})`),'server and floor interaction points must agree');
});
