/* Decorative city below the rooftop. Shares its projection, never simulation coordinates. */
(() => {
  'use strict';
  const GROUND_Z=-940,GRID=700,ROAD=100,FOG='#ecf0eb';
  const overlap=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
  function random(x,y,seed=0){const n=Math.sin(x*127.1+y*311.7+seed*74.7)*43758.5453;return n-Math.floor(n);}
  function model(data){
    const surfaces=data.surfaces||[],roof={
      x:Math.min(...surfaces.map(s=>s.x)),y:Math.min(...surfaces.map(s=>s.y)),
      w:Math.max(...surfaces.map(s=>s.x+s.w))-Math.min(...surfaces.map(s=>s.x)),
      h:Math.max(...surfaces.map(s=>s.y+s.h))-Math.min(...surfaces.map(s=>s.y)),
    };
    const margin={x:roof.x-65,y:roof.y-65,w:roof.w+130,h:roof.h+130};
    const buildings=[],parks=[],trees=[],cars=[],extent={x:-4200,y:-4200,w:10500,h:10500};
    for(let ix=-6;ix<9;ix++)for(let iy=-6;iy<9;iy++){
      const x=ix*GRID+ROAD/2+20,y=iy*GRID+ROAD/2+20,park=random(ix,iy,7)<.16;
      if(park){
        const p={x:x+18,y:y+18,w:GRID-ROAD-76,h:GRID-ROAD-76};
        if(!overlap(p,margin))parks.push(p);
      }else for(let part=0;part<2;part++){
        const distance=Math.hypot(x-1200,y-900),shrink=1-.32*Math.min(1,distance/6500);
        const w=(205+random(ix,iy,part+3)*55)*shrink,h=(375+random(ix,iy,part+9)*65)*shrink;
        const b={x:x+part*285+random(ix,iy,part+2)*18,y:y+35+random(ix,iy,part+6)*34,
          w,h,z:GROUND_Z,height:(95+random(ix,iy,part+1)*125)*shrink,variant:random(ix,iy,part+5)};
        if(!overlap(b,margin))buildings.push(b);
      }
      for(let edge=0;edge<2;edge++)for(let n=0;n<5;n++){
        const t={x:edge?x+GRID-ROAD-25:x+30+n*112,y:edge?y+30+n*112:y+GRID-ROAD-25};
        if(!overlap({x:t.x-22,y:t.y-22,w:44,h:44},margin))trees.push(t);
      }
      for(let axis=0;axis<2;axis++)if(random(ix,iy,axis+20)>.35){
        const car={x:ix*GRID+(axis?25:120+random(ix,iy,23)*420),
          y:iy*GRID+(axis?110+random(ix,iy,25)*410:-25),axis,color:random(ix,iy,26)};
        if(!overlap({x:car.x-12,y:car.y-20,w:30,h:40},margin))cars.push(car);
      }
    }
    return {roof,extent,buildings,parks,trees,cars,groundZ:GROUND_Z};
  }
  function create({data,projection:P}){
    if(data.id!=='rooftop'||!data.surfaces?.length)return null;
    const M=model(data),E=M.extent;
    const corners=[[E.x,E.y],[E.x+E.w,E.y],[E.x+E.w,E.y+E.h],[E.x,E.y+E.h]].map(([x,y])=>P.project(x,y,GROUND_Z));
    const bounds={x:Math.floor(Math.min(...corners.map(p=>p.x))-100),y:Math.floor(Math.min(...corners.map(p=>p.y))-300)};
    bounds.w=Math.ceil(Math.max(...corners.map(p=>p.x))-bounds.x+100);
    bounds.h=Math.ceil(Math.max(...corners.map(p=>p.y))-bounds.y+200);
    // Distant scenery stays softer than the roof and is cached once, not redrawn each frame.
    const scale=Math.min(.5,4096/bounds.w,4096/bounds.h),canvas=document.createElement('canvas');
    canvas.width=Math.ceil(bounds.w*scale);canvas.height=Math.ceil(bounds.h*scale);
    const g=canvas.getContext('2d');g.scale(scale,scale);g.translate(-bounds.x,-bounds.y);
    const p=(x,y,z=GROUND_Z)=>P.project(x,y,z);
    function tint(hex,amount=.3){
      const color=hex.replace('#',''),fog=FOG.slice(1);
      return '#'+[0,2,4].map(i=>Math.round(parseInt(color.slice(i,i+2),16)*(1-amount)+parseInt(fog.slice(i,i+2),16)*amount).toString(16).padStart(2,'0')).join('');
    }
    function haze(x,y){return Math.min(.8,.26+Math.hypot(x-1200,y-900)/10000);}
    function poly(points,color,stroke=null,width=.8){
      g.beginPath();points.forEach((q,i)=>i?g.lineTo(q.x,q.y):g.moveTo(q.x,q.y));g.closePath();
      if(color){g.fillStyle=color;g.fill();}if(stroke){g.strokeStyle=stroke;g.lineWidth=width;g.stroke();}
    }
    function plane(x,y,w,h,z,color,stroke=null){poly([p(x,y,z),p(x+w,y,z),p(x+w,y+h,z),p(x,y+h,z)],color,stroke);}
    function box(x,y,w,h,z,height,top,front,side,fog=.3){
      poly([p(x+w,y,z),p(x+w,y+h,z),p(x+w,y+h,z+height),p(x+w,y,z+height)],tint(side,fog));
      poly([p(x,y+h,z),p(x+w,y+h,z),p(x+w,y+h,z+height),p(x,y+h,z+height)],tint(front,fog));
      plane(x,y,w,h,z+height,tint(top,fog),tint('#acb9b6',Math.min(.9,fog+.3)));
    }
    function tree(x,y,fog=.3,size=23){
      const q=p(x,y,GROUND_Z+34),foot=p(x,y,GROUND_Z);
      g.strokeStyle=tint('#a5ac9d',fog);g.lineWidth=5;g.beginPath();g.moveTo(foot.x,foot.y);g.lineTo(q.x,q.y-10);g.stroke();
      for(const [dx,dy,r,color] of [[-12,-6,size*.74,'#b3c3a9'],[12,-5,size*.8,'#a5bda5'],[0,-20,size,'#bdccb4']]){
        g.beginPath();g.ellipse(q.x+dx,q.y+dy,r,r*.78,0,0,Math.PI*2);g.fillStyle=tint(color,fog);g.fill();
      }
    }
    g.fillStyle=FOG;g.fillRect(bounds.x,bounds.y,bounds.w,bounds.h);
    plane(E.x,E.y,E.w,E.h,GROUND_Z,FOG);
    for(let i=-6;i<=9;i++){
      for(const axis of [0,1]){
        const x=axis?i*GRID-ROAD/2-13:E.x,y=axis?E.y:i*GRID-ROAD/2-13;
        plane(x,y,axis?ROAD+26:E.w,axis?E.h:ROAD+26,GROUND_Z,tint('#e1e8e3',.35));
        plane(x+(axis?13:0),y+(axis?0:13),axis?ROAD:E.w,axis?E.h:ROAD,GROUND_Z+.1,tint('#bdced8',.38));
        for(let at=-6;at<9;at++)for(let dash=0;dash<5;dash++){
          const v=at*GRID+100+dash*115;
          plane(axis?i*GRID-1:v,axis?v:i*GRID-1,axis?2:42,axis?42:2,GROUND_Z+.2,'#edf1ed');
        }
      }
    }
    for(let ix=-6;ix<9;ix++)for(let iy=-6;iy<9;iy++)for(let n=0;n<6;n++){
      plane(ix*GRID-44+n*15,iy*GRID+58,8,55,GROUND_Z+.3,'#edf1ec');
      plane(ix*GRID+58,iy*GRID-44+n*15,55,8,GROUND_Z+.3,'#edf1ec');
    }
    for(const park of M.parks){
      const fog=haze(park.x,park.y);
      plane(park.x,park.y,park.w,park.h,GROUND_Z+.3,tint('#cdd8bd',fog));
      plane(park.x+park.w*.47,park.y,26,park.h,GROUND_Z+.5,tint('#efe9d9',fog));
      plane(park.x,park.y+park.h*.47,park.w,26,GROUND_Z+.5,tint('#efe9d9',fog));
      for(let n=0;n<8;n++){
        const x=park.x+48+random(n,park.x,11)*(park.w-96),y=park.y+48+random(n,park.y,12)*(park.h-96);
        if(Math.abs(x-(park.x+park.w/2))>30&&Math.abs(y-(park.y+park.h/2))>30)M.trees.push({x,y});
      }
    }
    for(const car of M.cars){
      const fog=haze(car.x,car.y),w=car.axis?17:34,h=car.axis?34:17;
      const color=car.color<.2?'#ddd19f':car.color<.48?'#99b6c5':car.color<.73?'#f6f6ee':'#bcc7c5';
      box(car.x,car.y,w,h,GROUND_Z+1,9,color,'#b6c3c8','#a8b8be',fog);
      plane(car.x+3,car.y+3,w-6,h-6,GROUND_Z+10,tint('#c3d3dc',fog));
    }
    const entities=[...M.buildings.map(b=>({kind:'building',...b})),...M.trees.map(t=>({kind:'tree',...t}))]
      .sort((a,b)=>(a.x+a.y)-(b.x+b.y));
    for(const e of entities){
      const fog=haze(e.x,e.y);
      if(e.kind==='tree'){tree(e.x,e.y,fog);continue;}
      box(e.x+8,e.y+9,e.w,e.h,GROUND_Z,1,'#d2d9d5','#d2d9d5','#d2d9d5',Math.min(.9,fog+.15));
      box(e.x,e.y,e.w,e.h,e.z,e.height,'#eee9dd','#d7d4c6','#c6d0d0',fog);
      const z=e.z+e.height;
      plane(e.x+11,e.y+11,e.w-22,e.h-22,z+.2,tint('#e4e5df',fog));
      for(let row=0;row<Math.floor(e.height/29)-1;row++){
        const base=e.z+14+row*29;
        for(let x=16;x<e.w-14;x+=38)poly([p(e.x+x,e.y+e.h+.2,base),p(e.x+x+17,e.y+e.h+.2,base),p(e.x+x+17,e.y+e.h+.2,base+14),p(e.x+x,e.y+e.h+.2,base+14)],tint('#b9cbd4',fog));
        for(let y=18;y<e.h-15;y+=43)poly([p(e.x+e.w+.2,e.y+y,base),p(e.x+e.w+.2,e.y+y+18,base),p(e.x+e.w+.2,e.y+y+18,base+14),p(e.x+e.w+.2,e.y+y,base+14)],tint('#afc4d1',fog));
      }
      box(e.x+e.w*.22,e.y+e.h*.2,e.w*.3,e.h*.21,z,16,'#f0eee6','#d2d7d4','#c6d1d4',fog);
      if(e.variant>.4)box(e.x+e.w*.6,e.y+e.h*.62,e.w*.2,e.h*.15,z,10,'#e9edeb','#c8d4d5','#c0cdd1',fog);
    }
    // Two visible outer faces belong to our building, far above neighboring rooftops.
    const roof=M.roof,bottom=GROUND_Z+30,xEnd=roof.x+roof.w,yEnd=roof.y+roof.h;
    function facade(a,b,topA,topB,shade){
      const A=p(a.x,a.y,topA),B=p(b.x,b.y,topB),C=p(b.x,b.y,bottom),D=p(a.x,a.y,bottom);
      g.save();poly([A,B,C,D],null);g.clip();
      const gradient=g.createLinearGradient(0,Math.min(A.y,B.y),0,Math.max(C.y,D.y));
      gradient.addColorStop(0,shade);gradient.addColorStop(.45,'#d9dcd6');gradient.addColorStop(.82,'#e3eae7');gradient.addColorStop(1,FOG);
      g.fillStyle=gradient;g.fillRect(Math.min(A.x,B.x)-2,Math.min(A.y,B.y)-2,Math.abs(A.x-B.x)+4,Math.max(C.y,D.y)-Math.min(A.y,B.y)+4);
      const span=Math.hypot(b.x-a.x,b.y-a.y),count=Math.ceil(span/100);
      for(let i=0;i<count;i++){
        const t=(i+.08)/count,u=(i+.57)/count;
        const x=a.x+(b.x-a.x)*t,y=a.y+(b.y-a.y)*t,xx=a.x+(b.x-a.x)*u,yy=a.y+(b.y-a.y)*u;
        poly([p(x,y,Math.min(topA,topB)-100),p(xx,yy,Math.min(topA,topB)-100),p(xx,yy,bottom+70),p(x,y,bottom+70)],'#bdc9cd25');
        poly([p(x,y,Math.min(topA,topB)),p(x+1,y,Math.min(topA,topB)),p(x+1,y,bottom),p(x,y,bottom)],'#b8c0b532');
      }
      const mist=g.createLinearGradient(0,Math.min(A.y,B.y)+150,0,Math.max(C.y,D.y));
      mist.addColorStop(0,'#ecf0eb00');mist.addColorStop(.55,'#ecf0eb08');mist.addColorStop(1,FOG);
      g.fillStyle=mist;g.fillRect(Math.min(A.x,B.x)-2,Math.min(A.y,B.y),Math.abs(A.x-B.x)+4,Math.max(C.y,D.y)-Math.min(A.y,B.y)+4);
      g.restore();
    }
    facade({x:xEnd,y:roof.y},{x:xEnd,y:yEnd},-10,-10,'#d1d5cc');
    const bands=data.surfaces.slice().sort((a,b)=>a.x-b.x);
    for(const band of bands)facade({x:band.x,y:yEnd},{x:band.x+band.w,y:yEnd},-10,-10,'#d9d7c9');
    return {model:M,bounds,canvas,draw(ctx){ctx.save();ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(canvas,bounds.x,bounds.y,bounds.w,bounds.h);ctx.restore();}};
  }
  window.CampusRooftopCity={model,create};
})();
