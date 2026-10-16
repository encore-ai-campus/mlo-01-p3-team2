const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const visibility=require('../dist/ad-visibility.js');
function setup(){
  let now=0,respond,autoLoad=true,timerId=0;const calls=[],frames=[],listeners={},images=[],opened=[],timers=new Map();
  const slot={hidden:true,children:[],append(child){this.children.push(child);},replaceChildren(){this.children=[];}};
  const dialog={open:true};
  const context={URL,Date,Promise,AbortController,Error,Map,Set,innerWidth:1000,innerHeight:800,
    performance:{now:()=>now},location:{href:'https://game.test/'},CampusAdVisibility:visibility,
    setTimeout(fn,delay){const id=++timerId;timers.set(id,{fn,at:now+delay});return id;},
    clearTimeout:id=>timers.delete(id),requestAnimationFrame:fn=>frames.push(fn),open:(...args)=>opened.push(args),
    addEventListener:(name,fn)=>listeners[name]=fn,
    document:{hidden:false,hasFocus:()=>true,cookie:'csrftoken=test',querySelector:()=>null,addEventListener(){},
      getElementById:id=>id==='floorTransitionAdSlot'?slot:dialog,
      createElement:()=>({append(img){this.img=img;}})},
    Image:class{set src(value){this.url=value;images.push(this);if(autoLoad)Promise.resolve().then(()=>this.onload?.());}getBoundingClientRect(){return {left:0,top:0,right:100,bottom:100};}},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>respond(url)};},
  };
  context.window=context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/campus-ads.js'),'utf8'),context);
  return {context,slot,dialog,calls,listeners,images,opened,setResponse(fn){respond=fn;},setTime(time){now=time;},
    holdImages(){autoLoad=false;},loadImage(index){images[index].onload?.();},failImage(index){images[index].onerror?.();},
    async flush(){for(let i=0;i<20;i++)await Promise.resolve();},
    async advance(time){now=time;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}await this.flush();},
    async frame(time){now=time;for(const fn of frames.splice(0))fn(time);await this.flush();}};
}
const entry=id=>({decision_id:id,ad:{title:'광고',creative_id:'creative',image_url:'https://ads.test/image/'+id,click_url:'https://ads.test/click/'+id}});

// 응답 도착과 이미지 로딩을 별도로 제어해 화면·링크·노출 대상의 교체 시점을 검증한다.
function setupRoof(){
  const h=setup(),writes=[];let current=null;
  const renderer={setDisplayImage(id,img){writes.push({id,img});current=img;return true;},
    displayPolygon(){return current?[{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100}]:null;}};
  return {...h,writes,renderer,tick(now,{floor='rooftop',blocked=false}={}){
    h.setTime(now);h.context.CampusAds.tick({now,floor,renderer,camera:{zoom:1,x:0,y:0},
      canvas:{getBoundingClientRect:()=>({left:0,top:0,right:100,bottom:100,width:100,height:100})},width:100,height:100,blocked});
  }};
}
const stamp=ms=>new Date(Date.UTC(2026,9,16)+ms).toISOString();
const roofBatch=(id,now=0,end=10000)=>({state:'READY',ads:[entry(id)],server_time:stamp(now),expires_at:stamp(end)});
const roofCalls=h=>h.calls.filter(c=>c.url.includes('placements/rooftop/'));
const impressions=(h,id)=>h.calls.filter(c=>c.url.includes('/'+id+'/impression/'));
function assertRoof(h,id){
  assert.equal(h.writes.at(-1).img.url,entry(id).ad.image_url);
  assert.equal(h.context.CampusAds.clickRoof(),true);
  assert.equal(h.opened.at(-1)[0],entry(id).ad.click_url);
  assert.ok(h.writes.every(write=>write.img!==null));
}

test('10초 뒤에도 기존 이미지와 링크를 유지하고 새 이미지가 준비된 순간 함께 교체한다',async()=>{
  const h=setupRoof();let release;
  assert.equal(h.context.CampusAds.clickRoof(),false);
  h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
  h.tick(0);await h.flush();assertRoof(h,'old');
  h.tick(9999);assert.equal(roofCalls(h).length,1);
  h.setResponse(url=>url.includes('rooftop')?new Promise(resolve=>release=resolve):{});
  h.tick(10000);await h.flush();h.tick(10100);assertRoof(h,'old');
  assert.equal(roofCalls(h).length,2);
  h.holdImages();release(roofBatch('new',10100,20000));await h.flush();
  h.tick(10500);assertRoof(h,'old');assert.equal(h.writes.length,1);
  assert.equal(impressions(h,'new').length,0);
  h.setTime(10700);h.loadImage(1);await h.flush();
  assertRoof(h,'new');assert.equal(h.writes.length,2);
  // 이미지 도착 시점에 10초를 더하지 않고 서버 회차의 다음 경계에서 조회한다.
  h.setResponse(url=>url.includes('rooftop')?roofBatch('third',20000,30000):{});
  h.tick(19899);assert.equal(roofCalls(h).length,2);
  h.tick(20000);await h.flush();assert.equal(roofCalls(h).length,3);
});

test('기존 광고의 연속 노출은 10초 경계에서 끊지 않고 새 광고는 실제 표시 후 1초를 센다',async()=>{
  const h=setupRoof();
  h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
  h.tick(0);await h.flush();h.tick(9500);
  h.holdImages();h.setResponse(url=>url.includes('rooftop')?roofBatch('new',10000,20000):{});
  h.tick(10000);await h.flush();h.tick(10499);
  assert.equal(impressions(h,'old').length,0);
  h.tick(10500);await h.flush();
  assert.equal(impressions(h,'old').length,1);assert.equal(impressions(h,'new').length,0);
  h.setTime(10700);h.loadImage(1);await h.flush();h.tick(10700);
  h.tick(11699);assert.equal(impressions(h,'new').length,0);
  h.tick(11700);await h.flush();h.tick(13000);
  assert.equal(impressions(h,'old').length,1);assert.equal(impressions(h,'new').length,1);
});

for(const failure of ['광고 조회 실패','이미지 로딩 실패','이미지 시간 초과']){
  test(failure+' 시 기존 광고와 링크를 유지하고 재시도에 성공하면 교체한다',async()=>{
    const h=setupRoof();
    h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
    h.tick(0);await h.flush();h.holdImages();
    h.setResponse(url=>{
      if(!url.includes('rooftop'))return {};
      if(failure==='광고 조회 실패')throw Error('network');
      return roofBatch('failed',10000,20000);
    });
    h.tick(10000);await h.flush();let retryAt=15000;
    if(failure==='이미지 로딩 실패'){h.failImage(1);await h.flush();}
    if(failure==='이미지 시간 초과'){await h.advance(14000);retryAt=19000;}
    assertRoof(h,'old');assert.equal(h.writes.length,1);
    h.tick(retryAt-1);assert.equal(roofCalls(h).length,2);
    h.setResponse(url=>url.includes('rooftop')?roofBatch('recovered',retryAt,20000):{});
    h.tick(retryAt);await h.flush();assert.equal(roofCalls(h).length,3);
    h.loadImage(h.images.length-1);await h.flush();assertRoof(h,'recovered');
    // 시간 초과된 이미지가 나중에 도착해도 새 광고를 덮어쓰지 않는다.
    if(failure==='이미지 시간 초과'){h.loadImage(1);await h.flush();assertRoof(h,'recovered');}
  });
}

for(const state of ['PENDING','FAILED','EMPTY']){
  test('새 회차가 '+state+'이면 기존 광고를 유지하고 다음 조회 때 다시 확인한다',async()=>{
    const h=setupRoof();
    h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
    h.tick(0);await h.flush();
    h.setResponse(url=>url.includes('rooftop')?{...roofBatch('new',10000,20000),state:state==='EMPTY'?'READY':state,
      ads:state==='EMPTY'?[{decision_id:'empty',ad:null}]:[]}:{});
    h.tick(10000);await h.flush();assertRoof(h,'old');assert.equal(h.writes.length,1);
    const retryAt=state==='PENDING'?10250:20000;
    h.tick(retryAt-1);assert.equal(roofCalls(h).length,2);
    h.setResponse(url=>url.includes('rooftop')?roofBatch('new',retryAt,30000):{});
    h.tick(retryAt);await h.flush();assertRoof(h,'new');
    assert.equal(roofCalls(h).length,3);
  });
}

test('로딩 중 유효 회차가 지난 후보를 표시하지 않고 기존 광고를 유지하며 최신 회차를 조회한다',async()=>{
  const h=setupRoof();
  h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
  h.tick(0);await h.flush();h.holdImages();
  h.setResponse(url=>url.includes('rooftop')?roofBatch('stale',19500,20000):{});
  h.tick(19500);await h.flush();h.setTime(20100);h.loadImage(1);await h.flush();
  assertRoof(h,'old');assert.equal(h.writes.length,1);
  h.setResponse(url=>url.includes('rooftop')?roofBatch('latest',20100,30000):{});
  h.tick(20100);await h.flush();h.loadImage(2);await h.flush();assertRoof(h,'latest');
});

test('잘못된 응답 시각이나 클릭 주소는 기존 광고를 덮어쓰지 않는다',async()=>{
  for(const invalid of ['time','click']){
    const h=setupRoof();h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
    h.tick(0);await h.flush();const batch=roofBatch('bad',10000,20000);
    if(invalid==='time')batch.expires_at='invalid';else batch.ads[0].ad.click_url='javascript:alert(1)';
    h.setResponse(url=>url.includes('rooftop')?batch:{});
    h.tick(10000);await h.flush();assertRoof(h,'old');assert.equal(h.writes.length,1);
    h.setResponse(url=>url.includes('rooftop')?roofBatch('good',15000,20000):{});
    h.tick(15000);await h.flush();assertRoof(h,'good');
  }
});

test('옥상에서 나갔다 돌아와도 유지 중인 같은 결정의 노출을 중복 보고하지 않는다',async()=>{
  const h=setupRoof();h.setResponse(url=>url.includes('rooftop')?roofBatch('old'):{});
  h.tick(0);await h.flush();h.tick(1);h.tick(1001);await h.flush();
  assert.equal(impressions(h,'old').length,1);
  h.tick(11000,{floor:'campus'});assert.equal(roofCalls(h).length,1);
  h.setResponse(url=>url.includes('rooftop')?Promise.reject(Error('offline')):{});
  h.tick(12000);await h.flush();h.tick(13000);
  assertRoof(h,'old');assert.equal(impressions(h,'old').length,1);
});
test('포털 좌우 같은 결정은 표시 두 개와 노출 보고 한 건으로 연결된다',async()=>{
  const h=setup();h.setResponse(url=>url.includes('placements')?{state:'READY',ads:[entry('one'),entry('one')]}:{});
  await h.context.CampusAds.startPortal('approved');await h.flush();
  assert.equal(h.slot.children.length,2);
  await h.frame(0);await h.frame(999);
  assert.equal(h.calls.filter(c=>c.url.includes('impression')).length,0);
  await h.frame(1000);await h.frame(2000);
  assert.equal(h.calls.filter(c=>c.url.includes('impression')).length,1);
  assert.equal(JSON.parse(h.calls[0].options.body).token,'approved');
});
test('이동이 끝난 뒤 도착한 응답은 광고를 표시하거나 보고하지 않는다',async()=>{
  const h=setup();let release;
  h.setResponse(()=>new Promise(resolve=>release=resolve));
  const request=h.context.CampusAds.startPortal('approved');await h.flush();
  h.dialog.open=false;h.listeners['campus:floor-transition-end']();
  release({state:'READY',ads:[entry('late')]});await request;
  assert.equal(h.slot.children.length,0);await h.frame(3000);
  assert.equal(h.calls.length,1);
});
test('좌우 다른 결정은 각각 연속 노출을 보고한다',async()=>{
  const h=setup();h.setResponse(url=>url.includes('placements')?{state:'READY',ads:[entry('left'),entry('right')]}:{});
  await h.context.CampusAds.startPortal('approved');await h.frame(0);await h.frame(1000);
  assert.equal(h.calls.filter(c=>c.url.includes('impression')).length,2);
});
test('옥상 회차가 포털 표시 중 끝나도 포털의 연속 노출 시간은 유지된다',async()=>{
  const h=setup();
  h.setResponse(url=>url.includes('rooftop')?{state:'READY',ads:[entry('roof')],server_time:'2026-10-15T00:00:00.000Z',expires_at:'2026-10-15T00:00:00.500Z'}:
    url.includes('portal')?{state:'READY',ads:[entry('portal')]}:{});
  const renderer={setDisplayImage(){return true;},displayPolygon(){return null;}};
  const tick=(now,floor)=>h.context.CampusAds.tick({now,floor,renderer,camera:{zoom:1,x:0,y:0},canvas:{getBoundingClientRect(){return {left:0,top:0,right:100,bottom:100,width:100,height:100};}},width:100,height:100,blocked:true});
  tick(0,'rooftop');await h.flush();
  await h.context.CampusAds.startPortal('approved');await h.frame(0);
  await h.frame(600);tick(600,'campus');await h.frame(1000);
  assert.equal(h.calls.filter(c=>c.url.includes('/portal/impression/')).length,1);
});
