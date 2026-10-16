/* Rooftop plaza: centered exhibition row, fountain court and garden seating. */
(() => {
  'use strict';
  const campus=window.CampusData;
  campus.id='campus';campus.name='18F 캠퍼스';campus.spawn=[campus.entrance.x+campus.entrance.w/2,campus.entrance.y-36];
  const stairs=campus.objects.find(o=>o.type==='stairs');
  Object.assign(stairs,{id:'campus-roof-stairs',name:'옥상으로 올라가기',roomId:'stairs',toFloor:'rooftop',stairDirection:'up',stairSteps:8,stairRise:4,stairRun:52,stairEntrySide:'left',stairRails:false,portalGlow:true,renderHeight:100,arrival:[2325,1565],approach:[stairs.x+stairs.w/2,stairs.y+stairs.h*.12],description:'라운지 쪽 옆문으로 평평한 발판에 들어와 계단 위쪽으로 걸어 올라가거나 가까이에서 E를 누르면 옥상 광장으로 이동합니다.',tags:['옥상 연결','유튜브 · 심리 테스트 · 게임 부스']});
  stairs.portalAnchor=[stairs.x+stairs.w/2,stairs.y+stairs.stairRun*.7];
  const extinguisher=campus.objects.find(o=>o.id==='extinguisher-meeting2');
  const lounge2=campus.rooms.find(r=>r.id==='lounge2');
  const stairRoom=campus.rooms.find(r=>r.id==='stairs');
  Object.assign(stairRoom,{labelX:stairs.x+stairs.w*.13,labelY:stairs.y+stairs.h*.86});
  // This shortcut requires E near the extinguisher; walking past it never transfers.
  Object.assign(extinguisher,{portalGlow:true,portalRadius:18,portalFloorClip:{x:lounge2.x+6,y:lounge2.y+6,w:lounge2.w-12,h:lounge2.h-12},renderHeight:80,toFloor:'rooftop',arrival:[145,1610],confirmTransfer:true,description:'가까이에서 E를 누르면 옥상 왼편 포탈로 이동할지 확인합니다. 예를 누르면 이동합니다.'});
  campus.portals=[{x:stairs.x,y:stairs.y,w:stairs.w,h:stairs.h*.24,objectId:stairs.id}];
  const width=2448,height=1800,rooms=[],objects=[],walls=[];
  const bounds={x:64,y:64,w:2320,h:1672};
  const terrace={x:1044,y:64,w:360,h:1672,axis:'x',levels:8,rise:12,lanes:[[140,285],[900,1005]]};
  const step=terrace.w/terrace.levels,top=terrace.levels*terrace.rise,lowerX=terrace.x+terrace.w;
  const elevationAt=(x,y)=>x<bounds.x||x>bounds.x+bounds.w||y<bounds.y||y>bounds.y+bounds.h?0:x<terrace.x?top:x<lowerX?(terrace.levels-Math.floor((x-terrace.x)/step))*terrace.rise:0;
  const surfaces=[{x:64,y:64,w:terrace.x-64,h:1672,z:top,floor:'roof'}];
  for(let i=0;i<terrace.levels;i++)surfaces.push({x:terrace.x+i*step,y:64,w:step,h:1672,z:(terrace.levels-i)*terrace.rise,floor:'roof',stair:true});
  surfaces.push({x:lowerX,y:64,w:2384-lowerX,h:1672,z:0,floor:'roof'});
  const room=(id,name,x,y,w,h,target,extra={})=>rooms.push({id,name,x,y,w,h,target,floor:'roof',...extra});
  room('roof-plaza','분수 광장',64,64,2320,1672,[1680,1110],{label:false,description:'유튜브·심리 테스트·게임 부스 세 개를 바닥의 긴 방향을 따라 나란히 배치한 광장입니다. 분수 둘레의 원형 포장과 산책로, 벤치·꽃 화단을 갖춘 휴게 광장입니다. 입구 왼편의 광고·행사 게시판을 확인할 수 있습니다.'});
  room('roof-upper','위쪽 휴게 광장',90,100,920,1510,[350,950],{labelX:300,labelY:970,description:'옥상 중앙 계단 위의 휴게 광장입니다. 아래쪽 광장과 길이를 맞췄고 유튜브·심리 테스트·게임 부스를 배치했습니다. 오른쪽 입구로 부스 안에 들어갈 수 있습니다.',tags:['휴게 광장','중앙 계단 연결']});
  room('roof-terrace','중앙 계단형 쉼터',terrace.x,64,terrace.w,1672,[1224,950],{labelX:1160,labelY:590,description:'맵의 1/2 지점에 세로로 길게 놓은 여덟 단 쉼터입니다. 낮은 단과 난간을 따라 두 계단 통로로 오갈 수 있습니다.',tags:['중앙 1/2','세로 배치','낮은 8단 계단']});
  room('festival-youtube','01 유튜브 스튜디오',1425,175,310,400,[1565,530],{labelX:1570,labelY:552,description:'영상 제작을 테마로 꾸민 열린 부스입니다. 카메라·삼각대, 마이크, 영상 편집 화면, 재생 버튼 기념패를 배치했습니다.',tags:['SECTION 01','YouTube','촬영 · 영상 편집']});
  room('festival-instagram','02 심리 테스트 존',1740,175,310,400,[1880,530],{labelX:1885,labelY:552,description:'성격과 기분을 알아보는 심리 테스트 공간입니다. 마음 유형 보드, 질문 키오스크, 감정 카드 진열대를 두고 부스 중앙에서 E를 누르면 심심테스트가 열립니다.',tags:['SECTION 02','심리 테스트','성격 · 감정 유형']});
  room('festival-booth3','03 게임 부스',2055,175,310,400,[2195,530],{labelX:2200,labelY:552,description:'아케이드 기기, 닌텐도 휴대용 콘솔과 스팀 게이밍 PC로 꾸민 게임 부스입니다. 중앙에서 E를 누르면 오목·테트리스·죽림고수·팔라독·솔리테어 등 16가지 게임 카드가 열리고, 선택한 게임을 같은 팝업에서 플레이할 수 있습니다.',tags:['SECTION 03','Nintendo · Steam','아케이드 · 게이밍 PC','오목 · 전쟁시대 · 아빠와 나 · 지뢰찾기']});
  room('roof-stairs','18층 연결 계단',2220,1550,154,174,[2325,1565],{labelX:2300,labelY:1545,description:'계단으로 들어가거나 가까이에서 E를 누르면 18층 캠퍼스로 내려갑니다.'});
  const obj=(type,x,y,w,h,extra={})=>{const o={id:'roof-object-'+objects.length,type,x,y,w,h,...extra};objects.push(o);return o;};
  const tree=(x,y)=>obj('tree',x,y,42,42,{solid:true,renderHeight:105});
  const planter=(x,y,w=100)=>obj('planter',x,y,w,30);
  // The same rear wall runs over both landings and every stair tier.
  walls.push({x1:64,y1:64,x2:2384,y2:64,height:420,topZ:420},
    {x1:2384,y1:64,x2:2384,y2:1736},
    {x1:64,y1:1736,x2:2384,y2:1736},{x1:64,y1:64,x2:64,y2:1736});
  for(const x of [98,2300])for(const y of x===98?[130,1100,1320]:[130,750,1320]){planter(x-8,y+30,63);tree(x,y);}
  for(const y of [520,1590]){planter(750,y,130);obj('terrace-bench',825,y+60,26,70);}
  for(let i=0;i<terrace.levels;i++){
    const x=terrace.x+i*step;
    for(const y of [310,650,1040,1400])obj('terrace-bench',x+11,y,22,y===650?230:240);
    for(const y of [590,1310]){obj('planter',x+10,y,24,74);if(i%2===0)tree(x+2,y+15);}
    if(i%2===1)for(const [y,c] of [[1250,'#e6b451'],[1650,'#8bb5ac']])obj('ottoman',x+11,y,23,23,{color:c});
  }
  for(const lane of terrace.lanes)for(const y of lane)obj('stair-handrail',terrace.x,y,terrace.w,6,{axis:'x',solid:false,renderHeight:135});
  const boothObjectStart=objects.length;
  function booth(x,roomId,platform,color,title){
    const y=200,w=280,h=300,r=rooms.find(r=>r.id===roomId);
    obj('rug',x,y,w,h,{solid:false,color:platform==='youtube'?'#f8e6e6':platform==='psych'?'#eee9f8':platform==='game'?'#e0e7f6':'#ebe9dc'});
    obj('exhibition-booth',x,y,w,h,{name:r.name,roomId,platform,title,color,entrance:'bottom',solid:false,collision:{x:0,y:0,w,h:10},renderHeight:175,description:r.description,tags:r.tags});
    obj('booth-collider',x,y,w,10,{solid:true});
    for(const sx of [x,x+w-10])obj('booth-side',sx,y,10,h,{solid:true,color,renderHeight:70});
  }
  booth(1440,'festival-youtube','youtube','#ed383b','YouTube');
  booth(1755,'festival-instagram','psych','#8171b6','PSYCHOLOGY TEST');
  booth(2070,'festival-booth3','game','#637db9','GAME ARCADE');
  obj('creator-screen',1470,239,133,16,{platform:'youtube',color:'#e63943',solid:true,renderHeight:115});
  obj('camera-tripod',1480,402,44,44,{solid:true,renderHeight:105});
  obj('microphone-stand',1560,436,30,30,{solid:true,renderHeight:105});
  obj('creator-console',1570,280,112,52,{platform:'youtube',solid:true,renderHeight:95});
  obj('creator-award',1640,240,48,36,{solid:true,renderHeight:100});
  obj('stool',1650,438,32,32,{color:'#e95659'});
  obj('psych-test-backdrop',1782,241,160,14,{platform:'psych',solid:true,renderHeight:150});
  obj('psych-type-wheel',1790,405,44,45,{solid:true,renderHeight:125});
  obj('psych-question-kiosk',1980,250,45,45,{solid:true,renderHeight:145});
  obj('psych-mood-cards',1895,380,110,50,{solid:true,renderHeight:75});
  obj('stool',1980,439,32,32,{color:'#9a86c4'});
  obj('game-arcade',2100,251,58,64,{solid:true,color:'#5879b7',renderHeight:145});
  obj('game-arcade',2180,251,58,64,{solid:true,color:'#8467b5',renderHeight:145});
  // Keep a clear route from the open entrance to the central E marker.
  obj('game-brand-sign',2079,206,262,9,{id:'game-brand-sign',solid:false,renderHeight:160});
  obj('game-pc-station',2083,333,76,77,{id:'game-steam-pc',solid:true,renderHeight:120});
  obj('game-console-display',2270,336,66,44,{id:'game-nintendo-display',platform:'nintendo',solid:true,renderHeight:110});
  for(const x of [2172,2240])obj('stool',x,452,28,28,{color:'#7189be'});
  const boothObjects=objects.slice(boothObjectStart);
  obj('fountain',1530,750,300,300,{id:'roof-fountain',name:'광장 분수대',roomId:'roof-plaza',solid:true,renderHeight:185,description:'부스 앞 광장에 놓인 원형 분수대입니다. 분수 둘레의 통로로 이동할 수 있습니다.',tags:['광장 쉼터']});
  obj('plaza-display',2038,1385,24,250,{id:'roof-ad-board',name:'광고 · 행사 게시판',roomId:'roof-plaza',source:'ad',title:'',imageUrl:'',imageOnly:true,displayAxis:'y',screenWidth:300,screenHeight:168,solid:true,renderHeight:230,description:'18층 연결 계단 왼편에서 광고와 행사 안내 이미지를 표시하는 게시판입니다. 게시판을 선택하면 이미지를 크게 볼 수 있습니다.',tags:['광고 이미지','행사 안내']});
  // Walkable paving connects the fountain court, seating and the front entrance.
  obj('plaza-paving',1436,656,488,488,{style:'fountain',solid:false});
  obj('plaza-paving',1930,260,96,1300,{style:'walkway',solid:false});
  obj('plaza-paving',1410,1120,815,88,{style:'walkway',solid:false});
  obj('plaza-paving',1870,1642,405,58,{style:'walkway',solid:false});
  obj('plaza-paving',2030,210,245,300,{style:'patio',solid:false});
  const garden=(x,y,w,h)=>obj('planter',x,y,w,h,{flowers:true,renderHeight:55});
  const seat=(x,y,w,h,backSide='top')=>obj('terrace-bench',x,y,w,h,{backrest:true,backSide,renderHeight:65});
  const lamp=(x,y)=>obj('plaza-lamp',x,y,18,18,{solid:true,collision:{x:6,y:6,w:6,h:6},renderHeight:150});
  // Leave the stair lanes and the paths around the fountain completely open.
  seat(1550,575,210,34);garden(1545,500,220,42);lamp(1495,560);
  seat(1550,1260,210,34,'bottom');garden(1545,1325,220,42);lamp(1495,1305);
  seat(2090,735,34,220,'right');garden(2160,725,42,240);lamp(2095,665);
  seat(2070,250,180,34);seat(2240,340,34,150,'right');
  garden(2060,165,200,40);tree(2078,162);tree(2225,162);
  obj('roundtable',2120,340,70,70,{color:'#f1e4ca'});
  for(const [x,y] of [[2080,354],[2140,435]])obj('stool',x,y,30,30,{color:'#8eac9b'});
  garden(2210,1175,42,210);seat(2140,1190,34,180,'right');lamp(2180,1135);
  for(const [x,y,c] of [[1450,560,'#e35655'],[1765,560,'#c67bca']])obj('balloons',x,y,20,20,{solid:false,color:c,renderHeight:125});
  const down=obj('stairs',2260,1610,100,110,{id:'roof-campus-stairs',name:'18층으로 내려가기',roomId:'roof-stairs',solid:false,toFloor:'campus',stairDirection:'down',stairSteps:8,stairRise:5,renderHeight:70,renderDepth:58,arrival:[2233.5,912],approach:[2310,1700],description:'계단 아래쪽으로 걸어가거나 가까이에서 E를 누르면 18층 캠퍼스로 내려갑니다.',tags:['18층 연결']});
  // Align booth backs on the long floor axis; projection supplies the 45-degree view.
  // Rotate the complete local
  // layout 90 degrees so the open entrances face right, including all colliders.
  const boothLayout=[['festival-youtube',1440,420,300],['festival-instagram',1755,420,760],['festival-booth3',2070,420,1220]];
  for(const [roomId,oldX,newX,newY] of boothLayout){
    const r=rooms.find(r=>r.id===roomId);
    Object.assign(r,{x:newX,y:newY-10,w:290,h:320,target:[newX+286,newY+140],labelX:newX+250,labelY:newY+315});
    for(const o of boothObjects.filter(o=>o.x>=oldX&&o.x+o.w<=oldX+280&&o.y>=200&&o.y+o.h<=500)){
      const local={x:o.x-oldX,y:(o.y-200)*.9,w:o.w,h:o.h*.9,originX:newX,originY:newY,span:280};
      Object.assign(o,{x:newX+local.y,y:newY+280-local.x-local.w,w:local.h,h:local.w,drawing:local,rotation:90,roomId});
      if(o.type==='exhibition-booth'){o.entrance='right';o.collision={x:0,y:0,w:9,h:280};}
    }
  }
  for(const shell of objects.filter(o=>o.type==='exhibition-booth')){
    const cx=shell.x+shell.w/2,cy=shell.y+shell.h/2;
    obj('booth-interaction',cx-12,cy-12,24,24,{id:shell.roomId+'-interaction',name:shell.platform==='youtube'?'유튜브 부스 안내':shell.platform==='psych'?'심리 테스트 존 안내':shell.platform==='game'?'게임 선택':'기본 부스 안내',roomId:shell.roomId,platform:shell.platform,action:'booth',interactionPoint:[cx,cy],solid:false,renderHeight:12});
  }
  const shortcut=obj('floor-portal',105,1570,80,80,{id:'roof-lounge2-portal',name:'18F 라운지 2로 이동',roomId:'roof-upper',toFloor:'campus',arrival:[extinguisher.x+extinguisher.w+18,extinguisher.y+extinguisher.h/2],approach:[145,1610],confirmTransfer:true,solid:false,portalStyle:'compact',portalScale:1.5,portalRadius:12,portalLabel:'18F',renderHeight:80,description:'소화기와 연결된 왕복 포탈입니다. 들어가거나 가까이에서 E를 누르면 18층 라운지 2로 이동할지 확인합니다.',tags:['18층 라운지 2 연결','예 · 아니오']});
  for(const [i,o] of objects.filter(o=>o.type==='balloons').entries()){const [, ,x,y]=boothLayout[i];Object.assign(o,{x:x+285,y:y+170});}
  const rooftop={id:'rooftop',name:'RF 옥상 광장',width,height,padding:140,paddingTop:440,rooms,objects,walls,surfaces,terrace,elevationAt,wallHeight:18,wallColor:'#e8eee8',spawn:[2325,1565],portals:[{x:down.x,y:down.y+78,w:down.w,h:32,objectId:down.id},{x:shortcut.x+14,y:shortcut.y+14,w:52,h:52,objectId:shortcut.id}]};
  window.CampusWorlds={campus,rooftop};
})();
