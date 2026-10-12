/* Independent local map; class.png is a design reference, never a game background. */
(() => {
 'use strict';
 const objects=[], add=(id,type,x,y,w,h,extra={})=>objects.push({id,type,x,y,w,h,classroomAsset:true,...extra});
 add('python-board','board',210,28,220,12,{});
 add('teacher-desk','desk',270,83,100,42);
 add('teacher-laptop','laptop',305,94,30,20);
 for(const [column,baseX] of [[0,80],[1,400]])for(const [row,y] of [[0,170],[1,300]])for(const [seat,offset] of [[0,0],[1,100]]){
  const x=baseX+offset,prefix=`student-${column}-${row}${seat?'-second':''}`;
  add(prefix,'desk',x,y,70,36);
  const learning=row===0&&seat===0;
  add(learning?(column?'python_fill_blank':'python_multiple_choice'):prefix+'-monitor','monitor',x+20,y+6,27,16,
   {name:column?'코드 빈칸 채우기':'Python 객관식',action:'learning',contentType:column?'fill_blank':'multiple_choice',interactionPoint:[x+35,y+48]});
  add(prefix+'-chair','chair',x+22,y+58,23,22,{dir:'up'});
 }
 add('entry-threshold','door-threshold',280,493,80,12);
 add('entry-left-post','door-post',274,493,6,12);
 add('entry-right-post','door-post',360,493,6,12);
 add('books-left','bookshelf',30,30,95,22);
 add('books-right','bookshelf',515,30,95,22);
 for(const [i,x,y] of [[0,30,78],[1,580,78],[2,30,450],[3,580,450]])add('plant-'+i,'plant',x,y,28,28);
 const residents=[{id:'classroom-instructor',role:'instructor',x:385,y:115,dir:'down',moving:false,walkTime:0,visualZ:0}];
 for(const [id,avatar] of [['student-0-0-chair','female-2'],['student-0-1-second-chair','male-2'],['student-1-0-second-chair','female-1'],['student-1-1-chair','male-1']]){
  const chair=objects.find(o=>o.id===id);
  residents.push({id:'resident-'+id,avatar,x:chair.x+chair.w/2,y:chair.y+chair.h/2,dir:'up',moving:false,walkTime:0,visualZ:8,seated:true});
 }
 const data={id:'python-classroom',subject:'python',name:'Python 학습교실',width:640,height:520,wallHeight:48,backdropWalls:true,continuousWalls:true,wallShadows:false,
 angle:0,tilt:.9,padding:15,paddingTop:95,viewBounds:{x:25,y:16,w:620,h:542},
 paintFloor:window.CampusClassroomAssets?.paintFloor,
  rooms:[{id:'python-room',x:15,y:15,w:610,h:490,floor:'wood',name:'Python 학습교실',label:false}],
  walls:[{x1:15,y1:15,x2:625,y2:15,height:80},{x1:15,y1:15,x2:15,y2:505},
   {x1:625,y1:15,x2:625,y2:505,height:48},{x1:15,y1:505,x2:280,y2:505,height:12},{x1:360,y1:505,x2:625,y2:505,height:12}],
  drawActor:window.CampusClassroomAssets?.drawActor,paintFurniture:window.CampusClassroomAssets?.paint,objects,residents,spawn:[320,455],exit:{id:'classroom-exit',name:'메타버스로 나가기',interactionPoint:[320,480]},portals:[]};
 const solids=new Set(['desk','chair','bookshelf','plant','board','door-post']);
 function walkable(x,y,radius=7){
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<23||x>617||y<23||y>493)return false;
  return !objects.filter(o=>solids.has(o.type)).some(o=>x>o.x-radius&&x<o.x+o.w+radius&&y>o.y-radius&&y<o.y+o.h+radius);
 }
 function move(actor,dx,dy){
  const steps=Math.max(1,Math.ceil(Math.hypot(dx,dy)/3));let changed=false;
  for(let i=0;i<steps;i++){
   if(walkable(actor.x+dx/steps,actor.y)){actor.x+=dx/steps;changed=true;}
   if(walkable(actor.x,actor.y+dy/steps)){actor.y+=dy/steps;changed=true;}
  }
  actor.moving=changed;return changed;
 }
 // Match the two painted floor rectangles exactly, using local map coordinates.
 function interaction(mapData,actor){
  if(Math.hypot(actor.x-mapData.exit.interactionPoint[0],actor.y-mapData.exit.interactionPoint[1])<35)return mapData.exit;
  const type=actor.y>=145&&actor.y<=413?(actor.x>=70&&actor.x<=270?'multiple_choice':actor.x>=390&&actor.x<=590?'fill_blank':null):null;
  if(!type)return null;
  return mapData.objects.filter(o=>o.action==='learning'&&o.contentType===type)
   .sort((a,b)=>Math.hypot(actor.x-a.interactionPoint[0],actor.y-a.interactionPoint[1])-Math.hypot(actor.x-b.interactionPoint[0],actor.y-b.interactionPoint[1]))[0]||null;
 }
 function nearby(actor){return interaction(data,actor);}
 function forSubject(subject){
  if(subject==='python')return {data,walkable,move,nearby};
  const sqlData={...data,id:'sql-classroom',subject:'sql',name:'SQL 학습교실',rooms:data.rooms.map(r=>({...r,name:'SQL 학습교실'})),objects:objects.map(o=>({...o,interactionPoint:o.interactionPoint?.slice()})),residents:residents.map(a=>({...a}))};
  for(const o of sqlData.objects){
   if(o.type==='board')o.text='SQL Learning Room';
   if(o.action==='learning'){o.id=o.id.startsWith('python_')?o.id.replace('python_','sql_'):'sql_'+o.id;o.name=o.contentType==='multiple_choice'?'SQL 객관식':'SQL 코드 빈칸 채우기';}
  }
  sqlData.paintFloor=api=>window.CampusClassroomAssets.paintFloor({...api,subject:'sql'});
  const sqlNearby=actor=>interaction(sqlData,actor);
  return {data:sqlData,walkable,move,nearby:sqlNearby};
 }
 window.CampusClassroomMap={data,walkable,move,nearby,forSubject};
})();
