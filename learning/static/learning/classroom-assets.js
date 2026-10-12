/* Procedural classroom furniture. Geometry uses the campus renderer's projection and depth cache. */
(() => {
 'use strict';
 function paint(o,api,z=0){
  if(!o.classroomAsset)return false;
  const {g,p,plane,box,line,ellipse,verticalPanel,shadow}=api,{x,y,w,h,type}=o;
  const timber=['#e3c496','#bb9869','#9d7a52'],metal=['#798d8b','#586d6b','#425653'];
  if(!['desk','monitor','laptop','door-threshold'].includes(type))shadow(o,z);
  if(type==='desk'){
   for(const xx of [x+5,x+w-8])for(const yy of [y+4,y+h-7])box(xx,yy,3,3,z,17,...metal);
   box(x+5,y+h-8,w-10,3,z+9,3,...metal);
   box(x,y,w,h,z+17,4,...timber);
   for(let at=8;at<h;at+=9)line(p(x+3,y+at,z+21.2),p(x+w-3,y+at,z+21.2),'#99774d44',.6);

  }else if(type==='chair'){
   for(const xx of [x+3,x+w-5])for(const yy of [y+3,y+h-5])box(xx,yy,2,2,z,12,...metal);
   box(x,y,w,h,z+12,4,'#7c9fa2','#63878c','#4d7075');
   box(x+1,y+h-5,w-2,4,z+16,17,'#91adb0','#6e9398','#527a80');
   plane(x+3,y+3,w-6,h-9,z+16.4,'#9ab4b2',null);
  }else if(type==='monitor'){
   plane(x+w*.32,y+h*.36,w*.36,h*.24,z+1,'#617b79','#425d5a');
   box(x+w*.45,y+h*.25,4,4,z+1,7,...metal);
   verticalPanel(x,y+3,w,22,z+7,'#2a4148');
   const color=o.contentType==='fill_blank'?'#146c56':'#275879';
   verticalPanel(x+2,y+3,w-4,18,z+9,color);
   for(let i=0;i<4;i++)line(p(x+5,y+3,z+23-i*3),p(x+w-5-i*3,y+3,z+23-i*3),'#bce7d0',.8);
   // Keep every key inside the keyboard case; leave a clear gap to the mouse.
   const keyboardX=x-2,keyboardY=y+h-7,keyboardW=w+2,keyboardH=7;
   plane(keyboardX,keyboardY,keyboardW,keyboardH,z+1.3,'#536965','#304941');
   const gap=1,keyW=(keyboardW-4-7*gap)/8;
   for(let row=0;row<2;row++)for(let col=0;col<8;col++)
    plane(keyboardX+2+col*(keyW+gap),keyboardY+1+row*2.5,keyW,1.5,z+1.6,'#c3d5cd',null);
   plane(keyboardX+8,keyboardY+5,keyboardW-16,1,z+1.6,'#c3d5cd',null);
   const mouseX=keyboardX+keyboardW+4;
   plane(mouseX,keyboardY+.5,4,6,z+1.3,'#8b9f96','#526c63');
   line(p(mouseX+2,keyboardY+1,z+1.6),p(mouseX+2,keyboardY+2.5,z+1.6),'#526c63',.6);
  }else if(type==='board'){
   verticalPanel(x,y+h*.7,w,60,z+14,'#987449');
   verticalPanel(x+5,y+h*.7,w-10,50,z+19,'#1e5747','x',o.text||'Python Learning Room','#f1f2d6');
   box(x-2,y+h-2,w+4,6,z+13,3,...timber);
   plane(x+12,y+h-1,13,3,z+16.3,'#f4f2d9',null);
   box(x+w-29,y+h-2,18,5,z+16,3,'#677e65','#4e6651','#38533e');
  }else if(type==='bookshelf'){
   box(x,y,w,h,z,3,...timber);
   box(x,y,4,h,z+3,57,...timber);box(x+w-4,y,4,h,z+3,57,...timber);
   box(x,y,w,3,z+3,57,'#c7a87b','#b28f61','#97744b');
   const colors=['#638f8b','#cc9d68','#d7d7c0','#a87167','#7897a2','#93a977'];
   for(const level of [4,23,42]){
    for(let at=7,i=0;at<w-7;at+=6,i++){
     const height=12+(i%3)*2;
     verticalPanel(x+at,y+h-3,4,height,z+level,colors[i%colors.length]);
     line(p(x+at+.7,y+h-3,z+level+3),p(x+at+3.3,y+h-3,z+level+3),'#f3ebc3',.6);
    }
    box(x,y,w,h,z+level+17,2,...timber);
   }
  }else if(type==='plant'){
   box(x+w*.25,y+h*.25,w*.5,h*.5,z,14,'#f2e9d3','#cdbf9e','#ab9c7e');
   plane(x+w*.3,y+h*.3,w*.4,h*.4,z+14.2,'#596345',null);
   const cx=x+w/2,cy=y+h/2;
   line(p(cx,cy,z+14),p(cx,cy,z+32),'#60815b',2);
   const q=p(cx,cy,z+31);
   for(let i=0;i<9;i++){const angle=i*Math.PI*2/9;ellipse(q.x+Math.cos(angle)*w*.24,q.y+Math.sin(angle)*h*.16,w*.18,h*.22,['#547f55','#779c66','#92ad78'][i%3]);}
   ellipse(q.x,q.y-4,w*.17,h*.2,'#80a66b');
  }else if(type==='door-post'){
   // Cutaway foreground frame keeps the entering avatar visible.
   box(x,y,w,h,z,20,...timber);box(x-1,y-1,w+2,h+2,z+20,3,...timber);
  }else if(type==='door-threshold'){
   plane(x,y,w,h,z+.4,'#8aab9d','#527f6d');
   for(let at=7;at<w;at+=8)line(p(x+at,y+2,z+.7),p(x+at,y+h-2,z+.7),'#d2e6d6',1);
  }else return false;
  return true;
 }
 function paintFloor({g,P,subject="python"}){
  g.save();g.transform(P.c,P.tilt*P.s,-P.s,P.tilt*P.c,P.offsetX,P.offsetY);
  // Solid side-wall backing closes the cutaway corner below the wall cap.
  g.fillStyle='#b4a387';g.fillRect(10,15,10,495);g.fillRect(620,15,10,495);
  for(const zone of [{x:70,color:'#2775be30',edge:'#3975a5',text:subject==='sql'?'SQL 객관식':'Python 객관식'},{x:390,color:'#21976b30',edge:'#257756',text:'코드 빈칸 채우기'}]){
   g.fillStyle=zone.color;g.fillRect(zone.x,145,200,268);
   g.strokeStyle=zone.edge;g.lineWidth=1;g.strokeRect(zone.x,145,200,268);
   g.font='700 16px "Malgun Gothic",sans-serif';g.textAlign='center';g.textBaseline='middle';g.fillStyle=zone.edge;g.fillText(zone.text,zone.x+100,402,190);
  }
  g.restore();
 }
 // Instructor variant retains the campus sprite's proportions, outlines and shading.
 let instructorSprite=null;
 function drawActor(ctx,actor){
  if(actor.role!=='instructor')return false;
  if(!instructorSprite){
   const image=window.CampusAvatars?.images.get('male-2');
   if(!image?.complete||!image.naturalWidth)return true;
   const sheet=document.createElement('canvas');sheet.width=128;sheet.height=128;
   const g=sheet.getContext('2d');g.drawImage(image,128,0,128,128,0,0,128,128);
   const pixels=g.getImageData(0,0,128,128);
   // Recolor only purple clothing; keep skin, hair, outlines and highlights intact.
   for(let y=67;y<115;y++)for(let x=0;x<128;x++){
    const at=(y*128+x)*4,red=pixels.data[at],green=pixels.data[at+1],blue=pixels.data[at+2];
    if(pixels.data[at+3]&&blue>green*1.15&&red>green*1.08&&blue>red*.92){
     pixels.data[at]=Math.round(red*.43);pixels.data[at+1]=Math.round(green*.7);pixels.data[at+2]=Math.round(blue*.67);
    }
   }
   g.putImageData(pixels,0,0);instructorSprite=sheet;
  }
  ctx.save();ctx.imageSmoothingEnabled=false;
  ctx.drawImage(instructorSprite,-20,-38.75,40,40);
  // Small pixel glasses and a teal lesson notebook distinguish the instructor.
  ctx.strokeStyle='#273641';ctx.lineWidth=.75;
  ctx.strokeRect(-6.5,-23.5,5.5,3.2);ctx.strokeRect(1,-23.5,5.5,3.2);
  ctx.beginPath();ctx.moveTo(-1,-22);ctx.lineTo(1,-22);ctx.stroke();
  ctx.fillStyle='#244f52';ctx.fillRect(7,-15,5,7);
  ctx.fillStyle='#e4ddbf';ctx.fillRect(8,-14,3,5);
  ctx.restore();return true;
 }
 function paintWallCorners(ctx,P){
  // Bridge the taller back wall and side-wall caps without leaving open corners.
  for(const x of [10,620]){
   const top=P.project(x,15,80),bottom=P.project(x+10,15,48);
   ctx.fillStyle='#917656';ctx.fillRect(top.x,top.y,10,bottom.y-top.y+4);
  }
  for(const x of [10,620]){
   const top=P.project(x,450),bottom=P.project(x+10,510);
   ctx.fillStyle='#b4a387';ctx.fillRect(top.x,top.y,bottom.x-top.x,bottom.y-top.y);
   ctx.fillStyle='#917656';ctx.fillRect(top.x,top.y,Math.max(2,(bottom.x-top.x)*.35),bottom.y-top.y);
  }
 }
 window.CampusClassroomAssets={paint,paintFloor,drawActor,paintWallCorners};
})();
