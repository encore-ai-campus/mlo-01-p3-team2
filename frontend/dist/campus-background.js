/* Warm beige campus backdrop, cached once per renderer; decoration only. */
(()=>{
 'use strict';
 function outline(data){
  const rooms=[...data.rooms,data.entrance].filter(r=>r.w>0&&r.h>0);
  const xs=[...new Set(rooms.flatMap(r=>[r.x,r.x+r.w]))].sort((a,b)=>a-b),ys=[...new Set(rooms.flatMap(r=>[r.y,r.y+r.h]))].sort((a,b)=>a-b);
  const filled=ys.slice(0,-1).map((y,j)=>xs.slice(0,-1).map((x,i)=>rooms.some(r=>(x+xs[i+1])/2>=r.x&&(x+xs[i+1])/2<=r.x+r.w&&(y+ys[j+1])/2>=r.y&&(y+ys[j+1])/2<=r.y+r.h)));
  const edges=[];
  for(let j=0;j<ys.length-1;j++)for(let i=0;i<xs.length-1;i++)if(filled[j][i]){
   if(!filled[j][i+1])edges.push({axis:'x',x:xs[i+1],y:ys[j],span:ys[j+1]-ys[j]});
   if(!filled[j+1]?.[i])edges.push({axis:'y',x:xs[i],y:ys[j+1],span:xs[i+1]-xs[i]});
  }
  edges.sort((a,b)=>a.axis.localeCompare(b.axis)||(a.axis==='x'?a.x-b.x||a.y-b.y:a.y-b.y||a.x-b.x));
  const merged=[];
  for(const edge of edges){const last=merged.at(-1);if(last&&last.axis===edge.axis&&(edge.axis==='x'?last.x===edge.x&&Math.abs(last.y+last.span-edge.y)<.01:last.y===edge.y&&Math.abs(last.x+last.span-edge.x)<.01))last.span+=edge.span;else merged.push({...edge});}
  return {rooms,edges:merged.sort((a,b)=>(a.x+a.y)-(b.x+b.y))};
 }

 function create({data,projection:P}){
  if(data.id!=='campus')return null;
  const bounds={x:-1800,y:-1200,w:Math.ceil(P.width+3600),h:Math.ceil(P.height+3100)};
  const scale=Math.min(.65,4096/bounds.w),canvas=document.createElement('canvas');
  canvas.width=Math.ceil(bounds.w*scale);canvas.height=Math.ceil(bounds.h*scale);
  const g=canvas.getContext('2d');g.scale(scale,scale);g.translate(-bounds.x,-bounds.y);
  const sky=g.createLinearGradient(0,bounds.y,0,bounds.y+bounds.h);
  sky.addColorStop(0,'#f7f1e7');sky.addColorStop(.48,'#eee5d6');sky.addColorStop(1,'#dfd0b9');
  g.fillStyle=sky;g.fillRect(bounds.x,bounds.y,bounds.w,bounds.h);
  const point=(x,y,z=0)=>P.project(x,y,z);
  for(let i=-30;i<45;i++)for(const axis of [0,1]){
   const a=axis?point(i*250,-8000,-110):point(-8000,i*250,-110),b=axis?point(i*250,10000,-110):point(10000,i*250,-110);
   g.strokeStyle=i%4===0?'#b59b7426':'#b59b7412';g.lineWidth=i%4===0?2:1.2;g.beginPath();g.moveTo(a.x,a.y);g.lineTo(b.x,b.y);g.stroke();
  }
  const light=g.createRadialGradient(P.width*.44,P.height*.25,150,P.width*.44,P.height*.25,P.width*.82);
  light.addColorStop(0,'#fffaf1a0');light.addColorStop(.7,'#fffaf125');light.addColorStop(1,'#fffaf100');g.fillStyle=light;g.fillRect(bounds.x,bounds.y,bounds.w,bounds.h);
  const O=outline(data),depth=58;
  function poly(points,color){g.beginPath();points.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.closePath();g.fillStyle=color;g.fill();}
  for(const r of O.rooms){
   g.shadowColor='#78634b30';g.shadowBlur=46;g.shadowOffsetY=22;
   poly([point(r.x-12,r.y-12,-depth),point(r.x+r.w+12,r.y-12,-depth),point(r.x+r.w+12,r.y+r.h+12,-depth),point(r.x-12,r.y+r.h+12,-depth)],'#c8b38f');
   g.shadowBlur=0;g.shadowOffsetY=0;
  }
  for(const e of O.edges){
   const x=e.x+(e.axis==='y'?e.span:0),y=e.y+(e.axis==='x'?e.span:0);
   const A=point(e.x,e.y,-2),B=point(x,y,-2),C=point(x,y,-depth),D=point(e.x,e.y,-depth);
   const shade=g.createLinearGradient(0,Math.min(A.y,B.y),0,Math.max(C.y,D.y));shade.addColorStop(0,e.axis==='x'?'#ad9372':'#c8b38f');shade.addColorStop(1,'#c8b38f');poly([A,B,C,D],shade);
   g.strokeStyle='#f7ecd4c0';g.lineWidth=2;g.beginPath();g.moveTo(A.x,A.y);g.lineTo(B.x,B.y);g.stroke();
  }
  return {draw(ctx){ctx.save();ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(canvas,bounds.x,bounds.y,bounds.w,bounds.h);ctx.restore();}};
 }
 window.CampusBackground={create};
})();
