const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sandbox=vm.createContext({window:{}});
for(const name of ['map-data.js','rooftop-data.js','rooftop-city.js','isometric.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),sandbox);
const roof=sandbox.window.CampusWorlds.rooftop,city=sandbox.window.CampusRooftopCity;
const intersects=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
test('decorative city keeps neighboring buildings below the roof and outside its footprint',()=>{
  const before=JSON.stringify(roof),m=city.model(roof);
  assert.ok(m.buildings.length>200&&m.parks.length>10&&m.cars.length>100&&m.trees.length>500);
  assert.ok(m.buildings.every(b=>b.z+b.height<-700));
  assert.ok(m.buildings.every(b=>!intersects(b,m.roof)));
  assert.ok(m.parks.every(b=>!intersects(b,m.roof)));
  assert.ok(m.trees.every(t=>!intersects({x:t.x-22,y:t.y-22,w:44,h:44},m.roof)));
  assert.equal(JSON.stringify(roof),before,'Background must never mutate map geometry or interactive objects');
  assert.equal(JSON.stringify(city.model(roof)),JSON.stringify(m),'Town must not change when the player moves or changes floors');
});
test('city and street edges use the roof projection and retain the real vertical drop',()=>{
  const P=sandbox.window.CampusIsometric.createProjection(roof),m=city.model(roof),b=m.buildings[0];
  const ground=P.project(b.x,b.y,m.groundZ),top=P.project(b.x,b.y,b.z+b.height);
  assert.equal(top.x,ground.x);assert.ok(Math.abs((ground.y-top.y)-b.height)<1e-8);
  for(const [x,y] of [[700,0],[0,700]]){
    const a=P.project(0,0,m.groundZ),end=P.project(x,y,m.groundZ),v=P.vector(x,y);
    assert.ok(Math.abs((end.x-a.x)-v.x)<1e-8&&Math.abs((end.y-a.y)-v.y)<1e-8);
  }
  assert.equal(city.create({data:{id:'campus'},projection:P}),null,'Indoor floor must have no city');
});
