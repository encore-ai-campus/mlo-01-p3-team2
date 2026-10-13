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
test('enlarged map merges classroom 3/4 with only glass doors and a mounted board, and keeps the vertical worktable',()=>{
  assert.equal(D.width,2448);assert.equal(D.height,1230);assert.equal(D.spaceScale,1.5);
  assert.deepEqual(Array.from(D.rooms.filter(r=>r.floor==='class'),r=>r.name).sort(),['Python 학습교실','SQL 학습교실','강의실 3·4','강의실 5','강의실 6','강의실 7']);
  const merged=D.rooms.find(r=>r.id==='class3-4');assert.equal(merged.w,916.5);assert.equal(merged.h,364.5);
  assert.equal(merged.label,false);assert.equal(merged.info,false);
  assert.equal(D.rooms.some(r=>r.id==='class3'||r.id==='class4'),false);
  assert.equal(D.objects.some(o=>o.roomId==='class3'||o.roomId==='class4'),false);
  const board=D.objects.find(o=>o.id==='class3-4-noticeboard');assert.equal(board.roomId,merged.id);
  assert.equal(board.mounted,true);assert.equal(board.solid,false);assert.equal(board.w,510);assert.equal(board.panelHeight,100);
  assert.equal(board.x+board.w/2,merged.x+merged.w/2);assert.ok(board.y>=merged.y&&board.y+board.h<=merged.y+7);
  assert.ok(D.objects.filter(o=>o.roomId===merged.id).every(o=>o.type==='glass-door'||o===board));
  const dividerX=(769+72)*D.spaceScale;
  assert.equal(D.walls.some(w=>w.x1===dividerX&&w.x2===dividerX&&w.y1<merged.y+merged.h),false);
  assert.ok(D.walls.some(w=>w.x1===dividerX&&w.x2===dividerX&&w.y1===369*D.spaceScale));
  const support=D.walls.find(w=>w.y1===merged.y&&w.y2===merged.y&&w.x1===merged.x&&w.x2===merged.x+merged.w);
  assert.ok(support.height>=board.mountHeight+board.panelHeight);
  const printer=D.objects.find(o=>o.type==='printer'&&o.roomId==='lounge1'),frontY=84*D.spaceScale;
  assert.ok(D.walls.filter(w=>w.y1===frontY&&w.y2===frontY).every(w=>w.x2<=printer.x||w.x1>=printer.x+printer.w));
  const printerSide=D.walls.find(w=>w.x1===2043&&w.x2===2043&&w.y1===36);assert.ok(printerSide.y2<=printer.y+printer.h);
  const worktable=D.objects.find(o=>o.id==='lounge1-worktable');assert.equal(worktable.w,42);assert.equal(worktable.h,172.5);
  assert.equal(D.objects.filter(o=>o.workSeat).length,4);
  assert.equal(D.rooms.find(r=>r.id==='lounge1').target[0],1893);
});
