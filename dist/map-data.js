/* Base geometry follows playdata.png; the left wing is enlarged to match the main classrooms. */
window.CampusData = (() => {
  const width=1632, height=820, layoutShiftX=72, rooms=[], walls=[], objects=[];
  const entrance={id:'main-entrance',name:'외부 출입구',x:1230,y:631,w:61,h:76,floor:'stone',target:[1255,678]};
  const room=(id,name,x,y,w,h,floor,target,extra={})=>rooms.push({id,name,x,y,w,h,floor,target,...extra});
  room('left-top','강의실 7',20,24,300,243,'class',[289,182],{front:'bottom',description:'강의실 3·4와 비슷한 크기로 넓힌 강의실입니다. 학생 책상을 4열·3줄로 배치했고, 강의 전면은 1·2번과 같은 아래쪽 방향입니다.'});
  room('left-middle','강의실 6',20,267,300,243,'class',[289,379],{front:'bottom',description:'강의실 3·4와 비슷한 크기로 넓힌 강의실입니다. 학생 책상을 4열·3줄로 배치했고, 강의 전면은 1·2번과 같은 아래쪽 방향입니다.'});
  room('left-bottom','강의실 5',20,510,300,243,'class',[289,589],{front:'bottom',description:'강의실 3·4와 비슷한 크기로 넓힌 강의실입니다. 학생 책상을 4열·3줄로 배치했고, 강의 전면은 1·2번과 같은 아래쪽 방향입니다.'});
  room('lounge2','라운지 2',248,24,208,607,'wood',[278,332],{photo:'assets/lounge2.png',description:'창가의 긴 탁자 중앙선에 맞춰 위쪽에 PC 연결용 TV를 놓았습니다. 오른쪽 벽면 바 테이블, 맨 위 오른쪽 끝의 정수기와 분리수거함, 아래쪽 두 회의공간이 있습니다.',tags:['긴 탁자 위쪽 중앙 TV','벽면 바 테이블','오른쪽 끝 정수기']});
  room('class4','강의실 4',456,24,313,243,'class',[496,243],{front:'bottom',boardInsetLeft:74,description:'강의실 1·2와 같은 방향으로, 아래쪽에 강의 전면과 강사 책상이 있습니다. 출입문은 중앙 복도의 왼쪽 끝에 있습니다.'});
  room('class3','강의실 3',769,24,298,243,'class',[1027,243],{front:'bottom',boardInsetRight:73,description:'강의실 1·2와 같은 방향으로, 아래쪽에 강의 전면과 강사 책상이 있습니다. 출입문은 중앙 복도의 오른쪽 끝에 있습니다.'});
  room('corridor','복도',456,267,611,102,'hall',[758,322]);
  room('class2','강의실 2',456,369,313,262,'class',[496,393],{front:'bottom',description:'강의 전면이 건물 바깥쪽인 아래쪽 벽을 향하도록 책상과 의자를 뒤집었습니다. 출입문은 중앙 복도의 왼쪽 끝에 있습니다.'});
  room('class1','강의실 1',769,369,298,262,'class',[1027,393],{front:'bottom',description:'강의 전면이 건물 바깥쪽인 아래쪽 벽을 향하도록 책상과 의자를 뒤집었습니다. 출입문은 중앙 복도의 오른쪽 끝에 있습니다.'});
  room('lounge1','라운지 1',1067,24,332,607,'wood',[1190,437],{photo:'assets/lounge1.png',description:'중앙 통로를 비워 둔 라운지입니다. 오른쪽에는 세로로 배치한 콘센트 작업 탁자와 네 좌석이 있습니다. 브라운 벽 쪽에는 마주보는 소파와 흰 탁자, 원형 스툴이 있고, 아래쪽 외벽의 유리 출입문과 두 좌석의 안내 데스크로 이어집니다. 위쪽 회의 탁자와 TV, 노트북용 긴 탁자, 프린터와 휴게 설비도 이용할 수 있습니다.',tags:['콘센트 작업 탁자','중앙 통로','마주보는 소파','외부 유리 출입문']});
  room('office','직원실',1399,26,117,321,'office',[1416,304]);
  room('meeting','회의실',1399,347,117,198,'meeting',[1417,501]);
  room('stairs','계단',1399,545,117,86,'stone',[1417,603]);
  room('consult-b','상담실 B',1297,631,55,87,'orange',[1310,699],{photo:'assets/consult.png',description:'사진의 주황색 벽을 반영한 상담실 B입니다. 작은 상담 테이블, 의자, PC 모니터를 배치했습니다.',tags:['주황색 벽','상담 테이블','PC 모니터']});
  room('consult-a','상담실 A',1352,631,48,87,'yellow',[1365,699],{photo:'assets/consult.png',description:'사진의 노란색 벽을 반영한 상담실 A입니다. 상담 테이블과 의자, PC 모니터가 있는 밝은 공간입니다.',tags:['노란색 벽','상담 테이블','PC 모니터']});
  room('meeting-l2-a','회의공간 1',315,425,141,106,'meeting',[332,496]);
  room('meeting-l2-b','회의공간 2',315,531,141,100,'meeting',[332,602]);
  room('storage','창고',1290,24,109,60,'stone',[1337,66]);
  const wall=(x1,y1,x2,y2,color,extra={})=>walls.push({x1,y1,x2,y2,color,...extra});
  const vertical=(x,a,b,doors=[],color)=>{let p=a;for(const [s,e] of doors){wall(x,p,x,s,color);p=e;}wall(x,p,x,b,color);};
  const horizontal=(y,a,b,doors=[],color)=>{let p=a;for(const [s,e] of doors){wall(p,y,s,y,color);p=e;}wall(p,y,b,y,color);};
  // A higher rear wall supports the large board in the merged classroom.
  wall(20,24,456,24);wall(456,24,1067,24,undefined,{height:124});wall(1067,24,1399,24);
  wall(1399,26,1516,26);wall(1516,26,1516,631);wall(20,24,20,753);
  horizontal(753,20,248);horizontal(631,248,1297,[[1210,1297]]);horizontal(631,1297,1352,[[1304,1335]]);horizontal(631,1352,1400,[[1360,1391]]);wall(1400,631,1516,631);
  vertical(248,24,753,[[146,184],[344,382],[554,592]]);wall(20,267,248,267);wall(20,510,248,510);
  vertical(456,24,631,[[267,369]]);wall(769,369,769,631);
  horizontal(267,456,1067,[[475,518],[1006,1049]]);horizontal(369,456,1067,[[475,518],[1006,1049]]);
  vertical(1067,24,631,[[267,369]]);vertical(1399,26,631,[[287,323],[485,520],[577,609]]);
  wall(1399,347,1516,347);wall(1399,545,1516,545);
  // Remove only the partition in front of the printer, keeping the storage doorway.
  horizontal(84,1067,1399,[[1234,1307],[1320,1353]]);wall(1290,24,1290,72);
  wall(278,24,278,68);wall(278,68,456,68);
  vertical(315,425,631,[[463,501],[565,603]]);wall(315,425,456,425);wall(315,531,456,531);
  wall(1297,631,1297,718,'#bd7656');wall(1352,631,1352,718,'#dbb446');wall(1400,631,1400,718,'#dfc053');wall(1297,718,1400,718);
  const obj=(type,x,y,w,h,extra={})=>{objects.push({id:'object-'+objects.length,type,x,y,w,h,...extra});return objects[objects.length-1];};
  const chair=(x,y,dir='down',color='#748b8b')=>obj('chair',x,y,14,16,{dir,color});
  const plant=(x,y,s=22)=>obj('plant',x,y,s,s);
  const tv=(x,y,w=58,h=17,roomId='lounge1',extra={})=>obj('tv',x,y,w,h,{name:'회의용 TV',roomId,description:'회의 테이블 위쪽의 PC 연결용 TV입니다. 발표와 팀 회의를 위한 공간입니다.',tags:['PC 연결','회의 · 발표'],...extra});
  const desk=(x,y,w,h,extra={})=>obj('desk',x,y,w,h,extra);
  const teaching=(r,columns,rows)=>{
    const usableW=r.w-62, deskW=Math.min(52,(usableW-(columns-1)*12)/columns), gapX=(usableW-columns*deskW)/(columns-1||1);
    const flipped=r.front==='bottom';
    const place=(type,x,y,w,h,extra={})=>obj(type,r.x+x,r.y+(flipped?r.h-y-h:y),w,h,{roomId:r.id,...extra});
    const boardLeft=r.boardInsetLeft||40,boardRight=r.boardInsetRight||40;
    place('board',boardLeft,16,r.w-boardLeft-boardRight,12,{front:r.front||'top'});
    place('desk',36,41,44,19,{teacher:true});place('laptop',42,43,15,12,{solid:false});
    for(let j=0;j<rows;j++) for(let i=0;i<columns;i++){
      const x=25+i*(deskW+gapX),y=83+j*45;
      place('desk',x,y,deskW,20,{color:'#fafbf6'});place('chair',x+deskW*.5-7,y+24,14,16,{dir:flipped?'down':'up',color:'#738991'});place('monitor',x+deskW*.5-7,y+2,14,10,{solid:false});
    }
    place('plant',r.id.startsWith('left-')?12:r.w-38,35,20,20);
  };
  for(const r of rooms.filter(r=>r.floor==='class'))teaching(r,r.w>250?4:3,r.h>220?3:2);
  obj('counter',283,31,164,27);obj('water',422,33,21,29,{name:'정수기',roomId:'lounge2',description:'라운지 2 맨 위 휴게 설비의 오른쪽 끝에 있는 정수기입니다.',tags:['오른쪽 끝','정수기']});
  for(let i=0;i<3;i++)obj('bin',328+i*28,35,21,24,{color:['#647779','#65a195','#cca966'][i],name:'분리수거함',roomId:'lounge2'});
  desk(318,120,58,128,{color:'#e1c395',name:'공용 회의 테이블',roomId:'lounge2'});
  tv(314.5,89,65,20,'lounge2',{name:'긴 탁자 PC 연결 TV',description:'라운지 2 위쪽 긴 탁자의 중앙선에 맞춰 배치한 PC 연결용 TV입니다.'});
  for(let i=0;i<4;i++){chair(296,124+i*32,'right','#b8915d');chair(384,124+i*32,'left','#b8915d');}
  obj('laptop',336,131,18,14,{solid:false});obj('notebook',337,199,18,13,{solid:false});
  obj('bar',426,78,24,182,{name:'벽면 바 테이블',roomId:'lounge2'});for(let i=0;i<5;i++)obj('stool',405,91+i*33,16,18,{color:'#bb996a'});
  plant(265,90,22);plant(265,258,24);obj('rug',280,305,150,76,{solid:false,color:'#d1d8c6'});plant(405,389,27);
  for(const yy of [425,531]){
    desk(350,yy+36,57,29,{color:'#dfc199'});
    chair(356,yy+17,'down');chair(384,yy+17,'down');chair(356,yy+68,'up');chair(384,yy+68,'up');
    tv(432,yy+35,14,34,'lounge2');obj('laptop',370,yy+39,17,13,{solid:false});
  }
  // Attach the extinguisher to the classroom 5 wall, clear of the doorway.
  obj('fire-extinguisher',253,608,16,22,{id:'extinguisher-meeting2',name:'소화기 · 옥상 이동',roomId:'lounge2',description:'강의실 5 쪽 벽면에 붙인 소화기입니다. 가까이에서 E를 누르면 옥상 맵 왼쪽 끝으로 이동합니다.',tags:['강의실 5 벽면','E · 옥상 이동']});
  obj('counter',1074,32,171,36);obj('water',1081,35,24,33,{name:'정수기',roomId:'lounge1',description:'라운지 1 맨 위에 있습니다. 오른쪽에는 커피머신과 분리수거함이 이어집니다.',tags:['정수기','휴게 설비']});
  obj('coffee-machine',1115,38,25,28,{name:'커피머신',roomId:'lounge1',description:'라운지 1 정수기 바로 옆에 놓인 커피머신입니다. 오른쪽의 분리수거함을 함께 이용할 수 있습니다.',tags:['정수기 옆','커피']});
  for(let i=0;i<3;i++)obj('bin',1150+i*31,40,25,26,{color:['#647779','#65a195','#cca966'][i],name:'분리수거함',roomId:'lounge1',description:'커피머신 옆의 세 분리수거함입니다. 오른쪽에는 사무용 프린터와 창고가 있습니다.'});
  obj('printer',1247,31,35,41,{name:'대형 사무용 프린터',roomId:'lounge1',description:'분리수거함과 창고 사이에 놓인 대형 사무용 복합기입니다. 스캔 덮개, 조작 화면, 출력 트레이와 용지함이 있는 형태로 배치했습니다.',tags:['분리수거함과 창고 사이','사무용 복합기']});
  obj('cabinet',1299,35,30,15);obj('cabinet',1365,36,24,35);obj('box',1304,55,21,19);obj('box',1367,64,19,12);
  desk(1125,110,158,30,{color:'#e1c598',name:'노트북용 긴 탁자',roomId:'lounge1',description:'기존 대형 TV 자리를 긴 탁자로 바꾸고, 탁자 위에 노트북 한 대를 놓았습니다.',tags:['긴 탁자','노트북 1대']});obj('laptop',1192,113,24,19,{solid:false,roomId:'lounge1'});
  [1088,1165,1241].forEach((x,i)=>{desk(x,175,37,81,{color:'#f5f3e9',name:`팀 회의 탁자 ${i+1}`,roomId:'lounge1'});tv(x-6,156,49,17,'lounge1',{name:`PC 연결 TV · ${i+1}번 탁자`,description:`라운지 1의 ${i+1}번 회의 탁자에 배치한 PC 연결용 TV입니다. 세 탁자에 한 대씩 놓았습니다.`});for(let j=0;j<2;j++){chair(x-19,184+j*39,'right','#657f88');chair(x+42,184+j*39,'left','#657f88');}});
  obj('laptop',1097,181,17,14,{solid:false});obj('notebook',1174,216,18,13,{solid:false});obj('laptop',1250,184,17,14,{solid:false});
  obj('noticeboard',1210,285,68,74,{id:'lounge1-noticeboard',name:'PLAYDATA 안내 게시판',roomId:'lounge1',photo:false,collision:{x:2,y:64,w:64,h:11},description:'두 기둥 사이 통로를 막지 않도록 중앙 위쪽으로 옮긴 이동식 칠판입니다. 아래 받침만 바닥을 차지하므로 칠판 뒤쪽으로 지나갈 수 있습니다. 사진처럼 나무 테두리와 받침대를 두고, 검은 칠판에 playdata를 적었습니다.',tags:['아래 받침','뒤쪽 통행','playdata']});
  desk(1306,276,28,115,{id:'lounge1-worktable',color:'#e1c598',powered:true,name:'콘센트 작업 탁자',roomId:'lounge1',photo:false,description:'라운지 1 오른쪽에 세로로 배치한 긴 작업 탁자입니다. 탁자를 따라 콘센트 네 곳과 오른쪽의 네 좌석을 두어 노트북 작업을 할 수 있는 공간으로 표현했습니다.',tags:['세로 작업 탁자','콘센트 4곳','작업 좌석 4개']});
  for(let i=0;i<4;i++)Object.assign(chair(1343,288+i*27,'left','#657f88'),{roomId:'lounge1',workSeat:true});
  obj('laptop',1319,296,14,20,{orientation:'vertical',solid:false,roomId:'lounge1'});obj('laptop',1319,354,14,20,{orientation:'vertical',solid:false,roomId:'lounge1'});
  // Move the right pillar and its bookshelves as one group, leaving a working area above.
  for(const [x,y] of [[1144,374],[1300,400]]){obj('pillar',x,y,40,40,{roomId:'lounge1'});obj('bookshelf',x-7,y-9,54,15,{name:'기둥 책장',roomId:'lounge1',photo:'assets/books.png',description:'라운지 1의 두 기둥에 사진 속 흰 프레임과 나무 선반의 책장을 반영했습니다. 색색의 책들이 둘러진 작은 도서 공간입니다.',tags:['기둥 주변 책장','흰 프레임','나무 선반']});obj('bookshelf',x-7,y+39,54,15,{name:'기둥 책장',roomId:'lounge1',photo:'assets/books.png'});obj('bookshelf-side',x+38,y+2,14,35,{name:'기둥 책장',roomId:'lounge1',photo:'assets/books.png'});}
  // Rotate the photographed seating group so its wood wall follows classroom 1's side.
  obj('rug',1094,452,135,170,{solid:false,color:'#eadcc3'});obj('woodwall',1073,454,14,172,{name:'브라운 벽',roomId:'lounge1',photo:'assets/lounge1.png',description:'강의실 1 옆면에 붙어 있는 브라운색 벽입니다. 흰 탁자와 원형 스툴을 벽을 따라 배치했습니다.'});
  obj('sofa',1133,593,79,27,{dir:'up',color:'#a6a5a0',name:'소파 라운지',roomId:'lounge1',photo:'assets/lounge1.png'});obj('sofa',1149,449,64,25,{dir:'down',seats:2,color:'#949a98',name:'2칸 소파',roomId:'lounge1',description:'위쪽으로 옮겨 아래 소파와 마주보도록 배치한 2칸 소파입니다.'});
  obj('coffee',1175,533,26,50);obj('coffee',1169,477,24,39);
  for(const [x,y,c] of [[1120,549,'#899e9c'],[1122,503,'#d9b65f'],[1123,461,'#8753a0']])obj('ottoman',x,y,25,25,{color:c});
  for(const y of [573,514,456])obj('roundtable',1094,y,18,27);
  obj('bookshelf-side',1216,585,13,37,{name:'라운지 책장',roomId:'lounge1',photo:'assets/books.png'});
  // The glass entrance belongs to the outside wall, between the seating rug and reception.
  obj('glass-wall',1210,630,28,3,{orientation:'horizontal',entrance:true});obj('glass-wall',1272,630,25,3,{orientation:'horizontal',entrance:true});
  obj('sliding-door',1238,626,34,12,{orientation:'horizontal',solid:false,name:'외부 유리 출입문',roomId:'lounge1',description:'휴게 공간과 안내 데스크 사이의 아래쪽 외벽에 있는 유리 슬라이딩 출입문입니다. 문이 열린 가운데 통로를 지나 바깥 출입구와 라운지를 오갈 수 있습니다.',tags:['외부 출입구','유리 슬라이딩 문']});
  desk(1275,538,24,86,{color:'#e0c197',name:'안내 데스크',roomId:'lounge1',description:'외부 유리 출입문 오른쪽의 안내 데스크입니다. 직원 좌석 두 개가 있습니다.',tags:['안내','직원 좌석 2개']});obj('monitor',1279,548,16,12,{solid:false});
  for(const y of [551,592])Object.assign(chair(1307,y,'left'),{roomId:'lounge1',reception:true});
  for(let i=0;i<4;i++){desk(1444,66+i*53,58,26,{color:'#eee9d9'});chair(1463,95+i*53,'up');obj('monitor',1461,69+i*53,21,13,{solid:false});}
  obj('cabinet',1410,41,21,86);plant(1479,296,23);
  desk(1440,386,41,91,{color:'#d8bd98'});for(let i=0;i<3;i++){chair(1421,391+i*30,'right');chair(1486,391+i*30,'left');}tv(1430,360,58,14,'meeting');plant(1479,509,21);
  obj('stairs',1407,553,100,70,{solid:false});
  for(const [x,id] of [[1297,'consult-b'],[1352,'consult-a']]){desk(x+24,654,20,28,{oval:true,name:'상담 테이블',roomId:id});obj('monitor',x+26,650,15,11,{solid:false});chair(x+1,656,'right','#aaa797');chair(x+24,690,'up','#aaa797');}
  obj('fire-extinguisher',761,280,16,22,{id:'extinguisher-corridor',name:'소화기',roomId:'corridor',description:'복도 위쪽, 통합 강의실 앞 벽면에 배치한 소화기입니다.',tags:['소화기','통합 강의실 앞']});
  obj('floor-arrow',530,305,28,16,{solid:false});obj('floor-arrow',972,305,28,16,{solid:false});
  // Hinged glass leaves open into their classrooms, keeping the corridor clear.
  for(const [roomId,x,y,w,h,orientation,swing] of [
    ['class4',475,264,43,6,'horizontal',-1],['class3',1006,264,43,6,'horizontal',-1],
    ['class2',475,366,43,6,'horizontal',1],['class1',1006,366,43,6,'horizontal',1],
    ['left-top',245,146,6,38,'vertical',-1],['left-middle',245,344,6,38,'vertical',-1],
    ['left-bottom',245,554,6,38,'vertical',-1],
  ])obj('glass-door',x,y,w,h,{id:'door-'+roomId,roomId,orientation,swing,open:false,name:rooms.find(r=>r.id===roomId).name+' 유리문'});
  // Merge after generating fixtures so other furniture and shared door IDs stay stable.
  const combinedClassroomIds=new Set(['class3','class4']);
  const combinedIndex=rooms.findIndex(r=>r.id==='class4');
  rooms.splice(combinedIndex,2,{id:'class3-4',name:'강의실 3·4',x:456,y:24,w:611,h:243,floor:'class',target:[758,145],label:false,info:false});
  for(const o of objects)if(o.type==='glass-door'&&combinedClassroomIds.has(o.roomId)){
    o.name='통합 강의실 '+(o.roomId==='class4'?'왼쪽':'오른쪽')+' 유리문';
    o.roomId='class3-4';
  }
  // A wall-mounted board sits on the inner face of the long rear wall.
  obj('noticeboard',591.5,27,340,1,{id:'class3-4-noticeboard',name:'PLAYDATA 대형 게시판',roomId:'class3-4',mounted:true,solid:false,panelHeight:100,mountHeight:12,renderHeight:132,description:'통합 강의실의 긴 벽 가운데에 달린 대형 게시판입니다. 가까이서 E를 누르거나 클릭하면 구내식당 메뉴·엔코아 타임 카드를 선택할 수 있습니다.'});
  // Leave clearance from the wall's visible thickness so the entire freestanding bookcase stays in front.
  obj('bookshelf-side',1084,389,18,48,{id:'lounge1-corridor-bookshelf',name:'벽면 책장',roomId:'lounge1',bookcaseHeight:58,photo:false,description:'라운지 1에서 복도로 들어가기 전 왼쪽 벽 앞에 놓인 책장입니다. 옆 휴식 공간과 복도 입구 사이의 벽면에 배치했습니다.'});
  // Keep the lounge and main wing proportions while making room for the wider classrooms.
  for(const r of rooms)if(!r.id.startsWith('left-')){r.x+=layoutShiftX;r.target[0]+=layoutShiftX;}
  entrance.x+=layoutShiftX;entrance.target[0]+=layoutShiftX;
  for(const o of objects)if(o.type==='glass-door'||!o.roomId?.startsWith('left-'))o.x+=layoutShiftX;
  for(const w of walls){if(w.x1>=248)w.x1+=layoutShiftX;if(w.x2>=248)w.x2+=layoutShiftX;}
  // The world grows; the avatar and interaction range keep their existing size.
  const spaceScale=1.5;
  for(const r of [...rooms,entrance]){for(const key of ['x','y','w','h'])r[key]*=spaceScale;r.target=r.target.map(v=>v*spaceScale);}
  for(const o of objects){for(const key of ['x','y','w','h'])o[key]*=spaceScale;if(o.collision)for(const key of ['x','y','w','h'])o.collision[key]*=spaceScale;}
  for(const w of walls)for(const key of ['x1','y1','x2','y2'])w[key]*=spaceScale;
  return {width:width*spaceScale,height:height*spaceScale,layoutShiftX:layoutShiftX*spaceScale,spaceScale,rooms,walls,objects:objects.filter(o=>!combinedClassroomIds.has(o.roomId)&&(o.roomId!=='lounge1'||(o.type!=='pillar'&&o.name!=='기둥 책장'&&o.id!=='lounge1-noticeboard'))),entrance};
})();
