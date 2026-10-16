const test=require('node:test'),assert=require('node:assert/strict');
const {visibleRatio,ContinuousExposure}=require('../dist/ad-visibility.js');
const square=[{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100}];
test('노출 비율은 광고 면적을 기준으로 하며 50% 경계를 포함한다',()=>{
  assert.equal(visibleRatio(square,{left:0,top:0,right:50,bottom:100}),.5);
  assert.equal(visibleRatio(square,{left:200,top:0,right:300,bottom:100}),0);
  const d=new ContinuousExposure();
  assert.equal(d.observe('left','a',.5,0),false);
  assert.equal(d.observe('left','a',.5,999),false);
  assert.equal(d.observe('left','a',.5,1000),true);
  assert.equal(d.observe('left','a',1,2000),false);
});
test('40% 이탈을 반복한 0.1초 열 번은 누적하지 않는다',()=>{
  const d=new ContinuousExposure();
  for(let i=0;i<10;i++){
    assert.equal(d.observe('roof','a',.5,i*200),false);
    assert.equal(d.observe('roof','a',.4,i*200+100),false);
  }
  d.observe('roof','a',.5,2000);
  assert.equal(d.observe('roof','a',.5,3000),true);
});
test('좌우 시간은 합산하지 않고 동일 결정의 보고는 한 번만 한다',()=>{
  const d=new ContinuousExposure();
  d.observe('left','same',1,0);d.observe('left','same',0,500);
  d.observe('right','same',1,500);
  assert.equal(d.observe('right','same',1,1000),false);
  assert.equal(d.observe('right','same',1,1500),true);
  assert.equal(d.observe('left','same',1,2500),false);
});
test('결정 교체와 탭 숨김은 시간을 초기화하지만 인정된 결정은 유지한다',()=>{
  const d=new ContinuousExposure();d.observe('roof','a',1,0);
  d.observe('roof','b',1,900);assert.equal(d.observe('roof','b',1,1000),false);
  d.reset();d.observe('roof','b',1,1500);
  assert.equal(d.observe('roof','b',1,2500),true);
  d.reset();assert.equal(d.observe('roof','b',1,4000),false);
});
test('기울어진 광고도 경계 상자의 면적 대신 실제 다각형 면적으로 계산한다',()=>{
  const diamond=[{x:50,y:0},{x:100,y:50},{x:50,y:100},{x:0,y:50}];
  assert.equal(visibleRatio(diamond,{left:0,top:0,right:50,bottom:100}),.5);
  assert.equal(visibleRatio(diamond,{left:0,top:0,right:25,bottom:100}),.125);
});
