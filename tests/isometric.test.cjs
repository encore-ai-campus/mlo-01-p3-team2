const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sandbox=vm.createContext({window:{}});
for(const name of ['map-data.js','isometric.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist',name),'utf8'),sandbox);
const D=sandbox.window.CampusData,P=sandbox.window.CampusIsometric.createProjection(D);
test('clockwise 45 degrees: east is down-right, south is down-left',()=>{
  assert.equal(P.angle,Math.PI/4);const east=P.vector(100,0),south=P.vector(0,100);
  assert.ok(east.x>0&&east.y>0&&south.x<0&&south.y>0);
  assert.ok(Math.abs(Math.abs(east.x)-Math.abs(south.x))<1e-9);
});
test('every room, entrance and map corner round-trips through the projection',()=>{
  for(const r of [...D.rooms,D.entrance,{x:0,y:0,w:D.width,h:D.height}])for(const [x,y] of [[r.x,r.y],[r.x+r.w,r.y+r.h],r.target||[r.x+r.w/2,r.y+r.h/2]]) {
    const q=P.project(x,y),b=P.unproject(q.x,q.y);assert.ok(Math.abs(b.x-x)<1e-8&&Math.abs(b.y-y)<1e-8);
    assert.ok(q.x>=0&&q.x<=P.width&&q.y>=0&&q.y<=P.height);
  }
});
test('screen arrow directions map back to the same visible directions',()=>{
  for(const [x,y] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[-1,1]]){
    const world=P.inverseVector(x,y),visible=P.vector(world.x,world.y);
    assert.ok(Math.abs(visible.x-x)<1e-8&&Math.abs(visible.y-y)<1e-8);
  }
});
test('enlarged map keeps seven rooms and the board floor footprint',()=>{
  assert.equal(D.width,2448);assert.equal(D.height,1230);assert.equal(D.spaceScale,1.5);
  assert.deepEqual(Array.from(D.rooms.filter(r=>r.floor==='class'),r=>r.name).sort(),['강의실 1','강의실 2','강의실 3','강의실 4','강의실 5','강의실 6','강의실 7']);
  const board=D.objects.find(o=>o.type==='noticeboard');assert.equal(board.collision.y,96);assert.equal(board.collision.h,16.5);
  assert.equal(D.rooms.find(r=>r.id==='lounge1').target[0],1893);
});
