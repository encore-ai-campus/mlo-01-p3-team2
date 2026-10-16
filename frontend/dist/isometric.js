/* Clockwise 45-degree view. Simulation and networking stay in floor coordinates. */
(() => {
  'use strict';
  function createProjection({width,height,angle=Math.PI/4,tilt=.58,padding=85,paddingTop=padding}) {
    const c=Math.cos(angle),s=Math.sin(angle);
    const vector=(x,y)=>({x:c*x-s*y,y:(s*x+c*y)*tilt});
    const corners=[[0,0],[width,0],[width,height],[0,height]].map(([x,y])=>vector(x,y));
    const minX=Math.min(...corners.map(p=>p.x)),maxX=Math.max(...corners.map(p=>p.x));
    const minY=Math.min(...corners.map(p=>p.y)),maxY=Math.max(...corners.map(p=>p.y));
    const offsetX=padding-minX,offsetY=paddingTop-minY;
    return {
      angle,tilt,c,s,offsetX,offsetY,width:maxX-minX+padding*2,height:maxY-minY+paddingTop+padding,
      vector,
      inverseVector(x,y){return {x:c*x+s*y/tilt,y:-s*x+c*y/tilt};},
      project(x,y,z=0){const p=vector(x,y);return {x:p.x+offsetX,y:p.y+offsetY-z};},
      unproject(x,y){x-=offsetX;y=(y-offsetY)/tilt;return {x:c*x+s*y,y:-s*x+c*y};},
    };
  }
  function create({data:D,font='"Malgun Gothic", system-ui, sans-serif'}) {
    const P=createProjection(D),resolution=1.5;
    const city=D.id==='campus'?window.CampusBackground?.create({data:D,projection:P}):window.CampusRooftopCity?.create({data:D,projection:P});
    const makeCanvas=(w,h)=>{const c=document.createElement('canvas');c.width=Math.ceil(w);c.height=Math.ceil(h);return c;};
    let g;
    const displayImages=new Map();
    const portalMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let drawing=null;
    const p=(x,y,z=0)=>drawing?P.project(drawing.originX+y,drawing.originY+drawing.span-x,z):P.project(x,y,z);
    const drawingVector=(x,y)=>drawing?P.vector(y,-x):P.vector(x,y);
    const groundHeight=(x,y)=>window.CampusStairs?.groundAt(D,x,y)??(D.elevationAt?.(x,y)||0);
    const projectGround=(x,y)=>p(x,y,groundHeight(x,y));
    const projectActor=actor=>p(actor.x,actor.y,Number.isFinite(actor.visualZ)?actor.visualZ:(window.CampusStairs?.heightAt(D,actor.x,actor.y)??groundHeight(actor.x,actor.y)));
    function unprojectGround(x,y) {
      // A screen point on a raised tread must map back to that tread's floor.
      for(const s of [...(D.surfaces||[])].reverse()){
        const q=P.unproject(x,y+s.z);
        if(q.x>=s.x&&q.x<=s.x+s.w&&q.y>=s.y&&q.y<=s.y+s.h)return q;
      }
      return P.unproject(x,y);
    }
    function poly(points,color,stroke='#67584670',width=.65) {
      g.beginPath();points.forEach((q,i)=>i?g.lineTo(q.x,q.y):g.moveTo(q.x,q.y));g.closePath();
      if(color){g.fillStyle=color;g.fill();}if(stroke){g.strokeStyle=stroke;g.lineWidth=width;g.stroke();}
    }
    function line(a,b,color,width=1){g.beginPath();g.moveTo(a.x,a.y);g.lineTo(b.x,b.y);g.strokeStyle=color;g.lineWidth=width;g.stroke();}
    function plane(x,y,w,h,z,color,stroke){poly([p(x,y,z),p(x+w,y,z),p(x+w,y+h,z),p(x,y+h,z)],color,stroke);}
    function box(x,y,w,h,z,height,top='#e2cba2',front='#b49a75',side='#998162') {
      const a=p(x,y,z),b=p(x+w,y,z),c=p(x+w,y+h,z),d=p(x,y+h,z);
      const A=p(x,y,z+height),B=p(x+w,y,z+height),C=p(x+w,y+h,z+height),E=p(x,y+h,z+height);
      if(drawing)poly([a,d,E,A],side);else poly([b,c,C,B],side);poly([d,c,C,E],front);poly([A,B,C,E],top);
    }
    function ellipse(x,y,rx,ry,color){g.beginPath();g.ellipse(x,y,rx,ry,0,0,Math.PI*2);g.fillStyle=color;g.fill();}
    // Contact shadow: anchored at the footprint so objects sit on the floor, spreading slightly toward the viewer.
    function shadow(o,z=0){
      if(!['stool','ottoman'].includes(o.type)){plane(o.x,o.y,o.w+3,o.h+4,z+.2,'#493c3021',null);return;}
      const cx=o.x+o.w/2+1.5,cy=o.y+o.h/2+2;poly(Array.from({length:24},(_,i)=>p(cx+Math.cos(i*Math.PI/12)*(o.w/2+1.5),cy+Math.sin(i*Math.PI/12)*(o.h/2+1.5),z+.2)),'#493c3021',null);
    }
    function label(value,x,y,size=13,fg='#4e5d56',bg='#fffaf0ee',z=0) {
      const q=p(x,y,z);g.font=`600 ${size}px ${font}`;const w=g.measureText(value).width+20;
      g.fillStyle=bg;g.beginPath();g.roundRect(q.x-w/2,q.y-10,w,22,5);g.fill();
      g.fillStyle=fg;g.textAlign='center';g.textBaseline='middle';g.fillText(value,q.x,q.y+1);
    }
    function verticalPanel(x,y,width,height,z,color,axis='x',text=null,textColor='#e7edda') {
      const v=axis==='x'?drawingVector(1,0):drawingVector(0,1),q=p(x,y,z+height);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);g.fillStyle=color;g.fillRect(0,0,width,height);
      if(text){g.save();if(v.x<0){g.translate(width,0);g.scale(-1,1);}g.font=`500 ${Math.min(16,width/7)}px ${font}`;g.fillStyle=textColor;g.textAlign='center';g.textBaseline='middle';g.fillText(text,width/2,height/2,width-8);g.restore();}
      g.restore();
    }
    function stairTreads(o) {
      const f=window.CampusStairs.flightFor(D,o),depth=f.run/f.levels,inset=5;
      const low=Math.min(f.bottom,0),down=o.stairDirection==='down';
      if(!down&&f.run<o.h)plane(o.x+inset,o.y+f.run,o.w-inset*2,o.h-f.run,f.bottom,'#d5ddd5',null);
      g.save();
      if(down) {
        plane(o.x,o.y,o.w,o.h,0,'#617166','#91a195');
        g.beginPath();[p(o.x+inset,o.y),p(o.x+o.w-inset,o.y),p(o.x+o.w-inset,o.y+o.h),p(o.x+inset,o.y+o.h)]
          .forEach((q,i)=>i?g.lineTo(q.x,q.y):g.moveTo(q.x,q.y));g.closePath();g.clip();
        // Recessed side walls make this an opening into the floor below.
        for(const sx of [o.x+inset,o.x+o.w-inset])poly([
          p(sx,o.y,0),p(sx,o.y+o.h,0),p(sx,o.y+o.h,low),p(sx,o.y,low),
        ],sx===o.x+inset?'#a4b3a7':'#879b8e',null);
      }
      for(let i=0;i<f.levels;i++) {
        const sy=o.y+i*depth,z=f.top-i*f.rise;
        box(o.x+inset,sy,o.w-inset*2,depth,low,z-low,'#e6e6dc','#aab6aa','#96a69a');
        plane(o.x+inset+3,sy+depth-2.1,o.w-inset*2-6,1.7,z+.15,'#9aaea080',null);
        line(p(o.x+inset,sy+depth,z+.3),p(o.x+o.w-inset,sy+depth,z+.3),'#fcfaf0',1.2);
      }
      g.restore();
      if(down)for(const sx of [o.x,o.x+o.w-inset])plane(sx,o.y,inset,o.h,.3,'#dddccd','#f5f4e9');
    }
    function stairRail(o,side) {
      const f=window.CampusStairs.flightFor(D,o),sx=side==='left'?o.x+2:o.x+o.w-5;
      const length=window.CampusStairs.railLength(D,o,side);
      if(!length)return;
      const down=o.stairDirection==='down',zAt=at=>down?34:f.top+(f.bottom-f.top)*at*length/f.run+34;
      for(const at of [0,.5,1]) {
        const sy=o.y+length*at,base=down?0:window.CampusStairs.treadHeight(f,sy),height=zAt(at)-base;
        plane(sx-2,sy-2,7,7,base+.2,'#889f90',null);
        box(sx,sy,3,3,base,Math.max(5,height),'#869a8d','#617b6d','#49685a');
      }
      const a=p(sx+1.5,o.y+1.5,zAt(0)),b=p(sx+1.5,o.y+length+1.5,zAt(1));
      line(a,b,'#4b695a',3.2);line({x:a.x,y:a.y-1},{x:b.x,y:b.y-1},'#a3b6a6',.9);
      line(p(sx+1.5,o.y+1.5,zAt(0)-15),p(sx+1.5,o.y+length+1.5,zAt(1)-15),'#718e7d',1.6);
    }
    function portalBase(o,base) {
      const cx=o.x+o.w/2,cy=o.y+o.h/2,q=p(cx,cy,base),center=q.y-54;
      g.save();
      // The ground seal follows the isometric floor; the doorway faces the viewer.
      circlePlane(cx,cy,35,base+.4,'#89d7ee44','#4ba8d392');
      circlePlane(cx,cy,29,base+.6,null,'#d4f9fff0');
      circlePlane(cx,cy,25,base+.6,'#a4e9ff28','#72c6df80');
      for(let i=0;i<8;i++) {
        const angle=i*Math.PI/4,r=p(cx+Math.cos(angle)*31,cy+Math.sin(angle)*31,base+.9);
        poly([{x:r.x,y:r.y-2},{x:r.x+2,y:r.y},{x:r.x,y:r.y+2},{x:r.x-2,y:r.y}],'#e8fcff',null);
      }
      g.save();g.translate(q.x,center);g.scale(47,70);
      const halo=g.createRadialGradient(0,0,.12,0,0,1);
      halo.addColorStop(0,'#58c9ff3d');halo.addColorStop(.5,'#7ddfff26');halo.addColorStop(1,'#92eaff00');
      g.fillStyle=halo;g.beginPath();g.arc(0,0,1,0,Math.PI*2);g.fill();g.restore();
      const pool=g.createLinearGradient(q.x,center-49,q.x,center+49);
      pool.addColorStop(0,'#c7f6ff70');pool.addColorStop(.4,'#74dcff83');pool.addColorStop(.8,'#398bd2a3');pool.addColorStop(1,'#9cefff8c');
      g.beginPath();g.ellipse(q.x,center,28,49,0,0,Math.PI*2);
      g.fillStyle=pool;g.fill();g.shadowColor='#50c8ff';g.shadowBlur=12;
      g.strokeStyle='#328acdd9';g.lineWidth=5.2;g.stroke();
      g.shadowBlur=5;g.strokeStyle='#bceeff';g.lineWidth=2.3;g.stroke();
      g.shadowBlur=0;g.beginPath();g.ellipse(q.x,center,24.5,45.5,0,0,Math.PI*2);
      g.strokeStyle='#edfdffc4';g.lineWidth=1.1;g.stroke();
      // A compact destination tag leaves the blue opening clear.
      g.fillStyle='#226981e6';g.beginPath();g.roundRect(q.x-17,q.y+9,34,16,5);g.fill();
      g.font=`700 10px ${font}`;g.textAlign='center';g.textBaseline='middle';g.fillStyle='#e5fbff';g.fillText('18F',q.x,q.y+17);
      g.restore();
    }
    function portalEnergy(o,base,t=0) {
      const cx=o.x+o.w/2,cy=o.y+o.h/2,q=p(cx,cy,base),center=q.y-54,seconds=t/1000;
      g.save();
      const pulse=(seconds*.6)%1;
      g.globalAlpha=(1-pulse)*.38;
      circlePlane(cx,cy,27+pulse*12,base+.7,null,'#99e8ff');g.globalAlpha=1;
      g.save();g.beginPath();g.ellipse(q.x,center,24,45,0,0,Math.PI*2);g.clip();
      // Two flowing ribbons give the interior a slow, continuous swirl.
      g.lineCap='round';g.shadowColor='#e1faff';g.shadowBlur=3;
      for(let strand=0;strand<2;strand++) {
        g.beginPath();
        for(let i=0;i<=44;i++) {
          const u=i/44,envelope=Math.sqrt(Math.max(0,1-(u*2-1)**2));
          const x=q.x+Math.sin(u*Math.PI*2.5-seconds*1.9+strand*Math.PI)*19*envelope;
          const y=center+(u*2-1)*44;
          if(i)g.lineTo(x,y);else g.moveTo(x,y);
        }
        g.strokeStyle=strand?'#a7efffc2':'#f2fdfff2';g.lineWidth=strand?1.4:2.2;g.stroke();
      }
      for(let i=0;i<5;i++) {
        const u=(seconds*.19+i*.2)%1;
        g.globalAlpha=Math.sin(u*Math.PI)*.72;
        ellipse(q.x+Math.sin(i*2.4+seconds*.65)*15,center+40-u*80,1.1+i%2*.5,1.6,'#f0fcff');
      }
      g.restore();
      g.lineCap='round';g.shadowColor='#bcf5ff';g.shadowBlur=5;
      for(let i=0;i<3;i++) {
        const angle=seconds*.7+i*Math.PI*2/3;
        g.beginPath();g.ellipse(q.x,center,28,49,0,angle,angle+Math.PI*.34);
        g.strokeStyle='#effeffe0';g.lineWidth=2;g.stroke();
      }
      g.shadowBlur=3;
      for(let i=0;i<10;i++) {
        const u=(seconds*.16+i*.113)%1;
        const x=q.x+Math.sin(i*2.37+seconds*.5)*(33+(i%3)*4),y=q.y-6-u*116;
        const size=1.3+(i%3)*.4;
        g.globalAlpha=Math.sin(u*Math.PI)*.82;
        g.fillStyle=i%3?'#eaffff':'#94dfff';g.beginPath();
        g.moveTo(x,y-size*2);g.lineTo(x+size*.55,y-size*.55);g.lineTo(x+size*2,y);
        g.lineTo(x+size*.55,y+size*.55);g.lineTo(x,y+size*2);g.lineTo(x-size*.55,y+size*.55);
        g.lineTo(x-size*2,y);g.lineTo(x-size*.55,y-size*.55);g.closePath();g.fill();
      }
      g.restore();
    }
    function compactPortalBase(o) {
      const cx=o.x+o.w/2,cy=o.y+o.h/2,base=groundHeight(cx,cy),q=p(cx,cy,base);
      const scale=o.portalScale||1;
      g.save();
      // Spill the light onto each actual tread instead of floating a flat seal
      // above several steps or letting it extend onto the rear wall.
      const radius=(o.portalRadius||12)*scale;
      function paintPool(x,y,w,h,z){
        g.save();g.transform(P.c,P.tilt*P.s,-P.s,P.tilt*P.c,P.offsetX,P.offsetY-z);
        g.beginPath();g.rect(x,y,w,h);g.clip();
        if(o.portalFloorClip){const c=o.portalFloorClip;g.beginPath();g.rect(c.x,c.y,c.w,c.h);g.clip();}
        const pool=g.createRadialGradient(cx,cy,0,cx,cy,radius);
        pool.addColorStop(0,'#efffffad');pool.addColorStop(.4,'#b8f8e87a');pool.addColorStop(1,'#a1eae600');
        g.fillStyle=pool;g.fillRect(x,y,w,h);g.restore();
      }
      if(o.stairFlight){
        const flight=window.CampusStairs.flightFor(D,o.stairFlight),step=flight.run/flight.levels;
        for(let i=0;i<flight.levels;i++){
          const start=Math.max(flight.origin+i*step,cy-radius),end=Math.min(flight.origin+(i+1)*step,cy+radius);
          if(end>start)paintPool(cx-radius,start,radius*2,end-start,flight.top-i*flight.rise+.35);
        }
      }else{
        paintPool(cx-radius,cy-radius,radius*2,radius*2,base+.35);
      }
      if(scale!==1){g.translate(q.x,q.y);g.scale(scale,scale);g.translate(-q.x,-q.y);}
      g.save();g.translate(q.x,q.y-9);g.scale(18,17);
      const halo=g.createRadialGradient(0,0,.1,0,0,1);
      halo.addColorStop(0,'#e4ffff72');halo.addColorStop(.45,'#a6eadc36');halo.addColorStop(1,'#9ce5eb00');
      g.fillStyle=halo;g.beginPath();g.arc(0,0,1,0,Math.PI*2);g.fill();g.restore();
      const beam=g.createLinearGradient(q.x,q.y+1,q.x,q.y-24);
      beam.addColorStop(0,'#f7ffffb8');beam.addColorStop(.3,'#ddfff580');beam.addColorStop(.7,'#bceef330');beam.addColorStop(1,'#cffcff00');
      g.fillStyle=beam;g.beginPath();g.moveTo(q.x-4,q.y+1);
      g.bezierCurveTo(q.x-6,q.y-8,q.x-9,q.y-16,q.x-12,q.y-24);
      g.lineTo(q.x+12,q.y-24);g.bezierCurveTo(q.x+9,q.y-16,q.x+6,q.y-8,q.x+4,q.y+1);g.closePath();g.fill();
      if(o.portalLabel){
        g.fillStyle='#226981dc';g.beginPath();g.roundRect(q.x-13,q.y+7,26,12,4);g.fill();
        g.font=`700 8px ${font}`;g.textAlign='center';g.textBaseline='middle';g.fillStyle='#eaffff';g.fillText(o.portalLabel,q.x,q.y+13);
      }
      g.restore();
    }
    function compactPortalEnergy(o,t=0) {
      const cx=o.x+o.w/2,cy=o.y+o.h/2,base=groundHeight(cx,cy),q=p(cx,cy,base),seconds=t/1000;
      const scale=o.portalScale||1;
      const aroundExtinguisher=o.type==='fire-extinguisher',height=aroundExtinguisher?32:22;
      g.save();g.lineCap='round';g.shadowColor='#d6fff0';g.shadowBlur=2;
      if(scale!==1){g.translate(q.x,q.y);g.scale(scale,scale);g.translate(-q.x,-q.y);}
      if(aroundExtinguisher){
        // Leave the red body, handle and white label clear while light moves around it.
        g.beginPath();g.rect(q.x-25,q.y-35,50,48);g.rect(q.x-7.5,q.y-30,15,31);g.clip('evenodd');
      }
      const trail=g.createLinearGradient(q.x,q.y,q.x,q.y-height);
      trail.addColorStop(0,'#f0fffad0');trail.addColorStop(.45,'#eaffffc4');trail.addColorStop(1,'#d8fbff00');
      for(const [strand,side] of (aroundExtinguisher?[-1,1]:[-1,0,1]).entries()){
        const sway=Math.sin(seconds*.9+strand*1.8)*2;
        g.globalAlpha=.36+.09*Math.sin(seconds+strand);
        g.beginPath();g.moveTo(q.x+side*(aroundExtinguisher?10:2),q.y-1);
        g.bezierCurveTo(q.x+side*(aroundExtinguisher?12:3)-sway,q.y-height*.27,q.x+side*(aroundExtinguisher?15:5)+sway,q.y-height*.64,q.x+side*(aroundExtinguisher?17:7)+sway,q.y-height);
        g.strokeStyle=trail;g.lineWidth=.8;g.stroke();
      }
      for(let i=0;i<4;i++){
        const u=(seconds*.22+i*.25)%1,x=q.x+(aroundExtinguisher?(i%2?1:-1)*(10+u*6):Math.sin(i*2.6+seconds*.35)*(1.5+u*7)),y=q.y-2-u*height;
        g.globalAlpha=Math.sin(u*Math.PI)*.7;
        ellipse(x,y,.7,1.1,'#f2ffff');
      }
      g.globalAlpha=.4+.06*Math.sin(seconds*1.2);
      g.shadowBlur=3;ellipse(q.x,q.y-.5,4.5,1.8,'#efffff');g.restore();
    }
    function playdataNoticeboard(width,height) {
      g.save();g.scale(width/510,height/100);
      g.fillStyle='#756b5c';g.fillRect(0,0,510,100);
      const surface=g.createLinearGradient(0,0,510,100);
      surface.addColorStop(0,'#253c35');surface.addColorStop(.5,'#1c302e');surface.addColorStop(1,'#152629');
      g.fillStyle=surface;g.fillRect(4,4,502,92);
      g.strokeStyle='#c1baa5';g.lineWidth=.7;g.strokeRect(2,2,506,96);
      g.save();g.beginPath();g.rect(5,5,500,90);g.clip();
      // Faint, deterministic chalk wipe marks keep the cached panel quiet and textured.
      g.save();g.strokeStyle='#e1eee1';g.globalAlpha=.045;g.lineWidth=.6;
      for(let i=0;i<55;i++){
        const x=9+(i*73)%478,y=9+(i*29)%81;
        g.beginPath();g.moveTo(x,y);g.quadraticCurveTo(x+13,y-1,x+30+(i%5)*3,y+.4);g.stroke();
      }
      g.restore();
      const halo=g.createRadialGradient(325,46,5,325,46,165);
      halo.addColorStop(0,'#b5e4ff15');halo.addColorStop(1,'#b5e4ff00');
      g.fillStyle=halo;g.fillRect(150,8,348,82);

      // The shield, rocket and ribbon echo the illuminated campus badge.
      g.save();g.translate(24,7);g.scale(.96,.85);
      const shield=new Path2D('M50 2 L85 15 Q85 28 96 36 L96 71 Q88 79 83 88 L50 100 L17 88 Q12 79 4 71 L4 36 Q15 28 15 15 Z');
      g.shadowColor='#d2edff';g.shadowBlur=7;g.fillStyle='#edf3ed';g.fill(shield);
      g.shadowBlur=0;g.strokeStyle='#343e3e';g.lineWidth=2;g.stroke(shield);
      g.font='500 6.2px Arial, sans-serif';g.fillStyle='#35413f';g.textAlign='center';g.textBaseline='middle';
      const caption='Coding Educational Institute',radius=37;
      const advances=[...caption].map(letter=>g.measureText(letter).width+.35);
      let angle=-Math.PI/2-advances.reduce((sum,value)=>sum+value,0)/radius/2;
      [...caption].forEach((letter,index)=>{
        const step=advances[index]/radius;angle+=step/2;
        g.save();g.translate(50+Math.cos(angle)*radius,55+Math.sin(angle)*radius);g.rotate(angle+Math.PI/2);g.fillText(letter,0,0);g.restore();angle+=step/2;
      });
      g.strokeStyle='#48514c';g.lineWidth=.8;g.beginPath();g.arc(50,55,28,Math.PI,Math.PI*2);g.stroke();
      g.font='700 6.5px Arial, sans-serif';g.fillText('-2002-',50,34);
      const rocket=new Path2D('M50 39 Q39 50 39 68 L61 68 Q61 50 50 39 Z M42 53 L35 69 L43 69 M58 53 L65 69 L57 69');
      g.strokeStyle='#303a36';g.lineWidth=2.2;g.lineJoin='round';g.stroke(rocket);
      g.beginPath();g.arc(50,54,4.2,0,Math.PI*2);g.stroke();
      g.fillStyle='#29332f';g.fillRect(-2,66,104,16);
      g.font='900 15px "Arial Black", Arial, sans-serif';g.fillStyle='#f6f8f0';g.fillText('PLAYDATA',50,74.6,96);
      g.font='500 7.4px Arial, sans-serif';g.fillStyle='#35413b';g.fillText('Bootcamp',50,90);
      g.beginPath();g.moveTo(31,94);g.lineTo(69,94);g.strokeStyle='#67716b';g.lineWidth=.7;g.stroke();
      g.restore();

      g.strokeStyle='#91b0a155';g.lineWidth=.6;g.beginPath();g.moveTo(139,17);g.lineTo(139,83);g.stroke();
      // Block letter outlines reproduce the triangular A shapes without relying on a local font.
      const glyphs={
        P:[28,'M0 0 H15 Q28 0 28 12 Q28 24 15 24 H9 V36 H0 Z M9 9 V15 H14 Q19 15 19 12 Q19 9 14 9 Z'],
        L:[24,'M0 0 H9 V27 H24 V36 H0 Z'],
        A:[31,'M11 0 H20 L31 36 H21 L18.7 28 H12.3 L10 36 H0 Z M14 21 H17 L15.5 15 Z'],
        Y:[29,'M0 0 H10 L14.5 12 L19 0 H29 L19 23 V36 H10 V23 Z'],
        D:[30,'M0 0 H13 Q30 0 30 18 Q30 36 13 36 H0 Z M9 9 V27 H12 Q20 27 20 18 Q20 9 12 9 Z'],
        T:[28,'M0 0 H28 V9 H19 V36 H9 V9 H0 Z'],
      };
      const letters=[...'PLAYDATA'],gap=3,total=letters.reduce((sum,letter)=>sum+glyphs[letter][0],0)+gap*(letters.length-1);
      g.save();g.translate(158,24);g.scale(319/total,1.23);
      const ink=g.createLinearGradient(0,0,total,36);ink.addColorStop(0,'#185a5a');ink.addColorStop(1,'#243551');
      g.fillStyle=ink;g.strokeStyle='#d8f6fc';g.lineWidth=1.2;g.lineJoin='round';
      let cursor=0;
      for(const letter of letters){
        const [span,outline]=glyphs[letter],shape=new Path2D(outline);
        g.save();g.translate(cursor,0);g.shadowColor='#b1dfff';g.shadowBlur=5;g.stroke(shape);g.shadowBlur=0;g.fill(shape,'evenodd');g.restore();cursor+=span+gap;
      }
      g.restore();
      g.save();g.shadowColor='#c3edff';g.shadowBlur=5;g.strokeStyle='#d8f6fc';g.lineWidth=1.4;
      g.beginPath();g.arc(486,24,4.5,0,Math.PI*2);g.stroke();g.restore();
      g.font=`600 13px ${font}`;g.textAlign='center';g.textBaseline='middle';g.fillStyle='#e3efdf';g.fillText('게시판',320,82);
      g.strokeStyle='#cee0cb99';g.lineWidth=.75;g.beginPath();g.moveTo(298,91);g.quadraticCurveTo(320,92,342,90.8);g.stroke();
      g.restore();
      // A narrow chalk rail finishes the board without drawing the popup's menu cards on its face.
      g.fillStyle='#8c8776';g.fillRect(5,96,500,3);
      g.fillStyle='#dbddcd';g.fillRect(465,94.4,11,1.7);g.fillStyle='#afd8d0';g.fillRect(480,94.4,8,1.7);
      g.fillStyle='#9d8b70';g.fillRect(433,92.8,23,3.2);g.fillStyle='#49594d';g.fillRect(434,92.2,21,1.4);
      g.restore();
    }
    function platformIcon(cx,cy,size,platform) {
      g.save();
      if(platform==='youtube') {
        const w=size*1.45,h=size;
        g.fillStyle='#ff0033';g.beginPath();g.roundRect(cx-w/2,cy-h/2,w,h,size*.22);g.fill();
        poly([{x:cx-size*.14,y:cy-size*.27},{x:cx+size*.3,y:cy},{x:cx-size*.14,y:cy+size*.27}],'#fff',null);
      } else if(platform==='game') {
        const w=size*1.5,h=size*.82;
        g.fillStyle='#e7f4fa';g.beginPath();g.roundRect(cx-w/2,cy-h/2,w,h,size*.23);g.fill();
        g.fillStyle='#486599';g.fillRect(cx-size*.38,cy-size*.07,size*.27,size*.14);g.fillRect(cx-size*.315,cy-size*.135,size*.14,size*.27);
        ellipse(cx+size*.26,cy-size*.085,size*.075,size*.075,'#ed8aa7');ellipse(cx+size*.43,cy+size*.085,size*.075,size*.075,'#e9c46d');
      } else if(platform==='psych') {
        g.fillStyle='#7869a8';g.beginPath();g.roundRect(cx-size*.5,cy-size*.5,size,size,size*.25);g.fill();
        g.strokeStyle='#fff';g.lineWidth=Math.max(1.5,size*.08);g.lineCap='round';
        g.beginPath();g.arc(cx-size*.07,cy,size*.27,-Math.PI*.56,Math.PI*.5);g.stroke();
        g.beginPath();g.arc(cx+size*.07,cy,size*.27,Math.PI*.5,Math.PI*1.56);g.stroke();
        line({x:cx,y:cy-size*.29},{x:cx,y:cy+size*.29},'#fff',Math.max(1.3,size*.065));
        ellipse(cx-size*.12,cy-size*.06,size*.035,size*.035,'#fff');ellipse(cx+size*.12,cy-size*.06,size*.035,size*.035,'#fff');
      } else {
        const gradient=g.createLinearGradient(cx-size/2,cy+size/2,cx+size/2,cy-size/2);
        for(const [stop,color] of [[0,'#ffd467'],[.3,'#f78443'],[.55,'#e9428c'],[.8,'#ad42c5'],[1,'#6453d9']])gradient.addColorStop(stop,color);
        g.fillStyle=gradient;g.beginPath();g.roundRect(cx-size/2,cy-size/2,size,size,size*.24);g.fill();
        g.strokeStyle='#fff';g.lineWidth=size*.09;g.beginPath();g.roundRect(cx-size*.31,cy-size*.31,size*.62,size*.62,size*.18);g.stroke();
        g.beginPath();g.arc(cx,cy,size*.17,0,Math.PI*2);g.stroke();ellipse(cx+size*.21,cy-size*.21,size*.055,size*.055,'#fff');
      }
      g.restore();
    }
    function platformPanel(x,y,width,height,z,platform,text) {
      const v=drawingVector(1,0),q=p(x,y,z+height);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);g.fillStyle='#fffafc';g.fillRect(0,0,width,height);
      platformIcon(text?20:width/2,height/2,Math.min(19,height*.7),platform);
      if(text){g.font=`600 ${Math.min(14,width/9)}px ${font}`;g.fillStyle=platform==='youtube'?'#94302f':'#70437e';g.textAlign='center';g.textBaseline='middle';g.fillText(text,(width+32)/2,height/2,width-45);}
      g.restore();
    }
    function brandBackdrop(x,y,width,height,z,platform,text) {
      const v=drawingVector(1,0),q=p(x,y,z+height);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);
      const gradient=g.createLinearGradient(0,height,width,0);
      const colors=platform==='psych'?['#b7acd9','#8d7bbb','#68598f']:platform==='youtube'?['#e83d45','#c52236','#962633']:platform==='game'?['#6b8fca','#5276b1','#344d88']:['#f0e9d6','#e5dbc2','#c6b993'];
      colors.forEach((color,i)=>gradient.addColorStop(i/2,color));g.fillStyle=gradient;g.fillRect(0,0,width,height);
      if(platform)platformIcon(width*.17,height*.46,Math.min(43,height*.5),platform);
      g.font=`700 ${Math.min(29,width/9)}px ${font}`;g.fillStyle=platform?'#fffaf7':'#5c6254';g.textAlign='center';g.textBaseline='middle';g.fillText(text,width*(platform ? .61 : .5),height*.5,width*(platform ? .64 : .9));
      g.restore();
    }
    function gameController(x,y,width,height,z,color='#eef1f7',playstation=false) {
      const a=drawingVector(1,0),b=drawingVector(0,1),q=p(x,y,z);
      g.save();g.transform(a.x,a.y,b.x,b.y,q.x,q.y);g.scale(width/44,height/25);
      g.beginPath();g.moveTo(11,3);g.bezierCurveTo(4,1,2,10,1,19);g.bezierCurveTo(0,27,9,27,14,17);g.lineTo(30,17);g.bezierCurveTo(35,27,44,27,43,19);g.bezierCurveTo(42,10,40,1,33,3);g.closePath();
      g.fillStyle=color;g.fill();g.strokeStyle='#536783';g.lineWidth=.8;g.stroke();
      g.fillStyle='#27354b';g.fillRect(18,5,9,5);g.fillRect(8,8,8,3);g.fillRect(10.5,5.5,3,8);
      for(const [cx,cy] of [[17,15],[27,15]]){ellipse(cx,cy,3,3,'#33445e');ellipse(cx,cy,1.5,1.5,'#18283a');}
      for(const [cx,cy,c] of [[34,5,'#8ed7c2'],[38,9,'#e996b3'],[34,13,'#72c2ed'],[30,9,'#bbadeb']])ellipse(cx,cy,1.7,1.7,playstation?c:'#edb875');
      line({x:17,y:3},{x:27,y:3},'#7aa6ef',1.4);g.restore();
    }
    function steamScreen(x,y,width,height,z) {
      const v=drawingVector(1,0),q=p(x,y,z+height);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);g.fillStyle='#162d45';g.fillRect(0,0,width,height);
      const cx=width/2,cy=height*.43,r=Math.min(width,height)*.27;
      ellipse(cx,cy,r,r,'#264d6c');
      line({x:cx-r*.9,y:cy+r*.5},{x:cx-r*.15,y:cy+r*.76},'#f0f8ff',r*.23);
      line({x:cx-r*.18,y:cy+r*.48},{x:cx+r*.47,y:cy-r*.32},'#f0f8ff',r*.28);
      for(const [dx,dy,radius] of [[-.18,.53,.3],[.5,-.39,.4]]){g.beginPath();g.arc(cx+dx*r,cy+dy*r,radius*r,0,Math.PI*2);g.strokeStyle='#f0f8ff';g.lineWidth=r*.13;g.stroke();}
      g.font=`700 ${Math.min(9,width/6)}px ${font}`;g.fillStyle='#f0f8ff';g.textAlign='center';g.textBaseline='middle';g.fillText('STEAM',cx,height*.84,width-7);g.restore();
    }
    function handheldConsole(x,y,width,z) {
      const v=drawingVector(1,0),q=p(x,y,z+28);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);
      g.fillStyle='#253247';g.beginPath();g.roundRect(0,0,width,28,5);g.fill();
      g.fillStyle='#22bbd1';g.beginPath();g.roundRect(0,0,9,28,4);g.fill();g.fillStyle='#f26766';g.beginPath();g.roundRect(width-9,0,9,28,4);g.fill();
      g.fillStyle='#93d9eb';g.fillRect(11,4,width-22,19);g.fillStyle='#718bd4';g.fillRect(11,16,width-22,7);g.fillStyle='#97cf7c';g.fillRect(11,19,width-22,4);
      ellipse(width*.52,10,3,3,'#fff2bd');ellipse(4.5,8,2.4,2.4,'#34445c');ellipse(width-4.5,20,2.4,2.4,'#34445c');
      for(const [cx,cy] of [[3,18],[6,18],[4.5,16],[4.5,20],[width-6,8],[width-3,8],[width-4.5,6],[width-4.5,10]])ellipse(cx,cy,.8,.8,'#34445c');
      g.restore();
    }
    function circlePlane(cx,cy,r,z,color,stroke) {
      poly(Array.from({length:40},(_,i)=>p(cx+Math.cos(i*Math.PI/20)*r,cy+Math.sin(i*Math.PI/20)*r,z)),color,stroke);
    }
    function cylinder(cx,cy,r,z,height,top,side) {
      for(let i=0;i<40;i++){
        const a=i*Math.PI/20,b=(i+1)*Math.PI/20;
        poly([p(cx+Math.cos(a)*r,cy+Math.sin(a)*r,z),p(cx+Math.cos(b)*r,cy+Math.sin(b)*r,z),p(cx+Math.cos(b)*r,cy+Math.sin(b)*r,z+height),p(cx+Math.cos(a)*r,cy+Math.sin(a)*r,z+height)],side,null);
      }
      circlePlane(cx,cy,r,z+height,top,'#78958a70');
    }
    function leg(x,y,z=0,height=16){box(x,y,3,3,z,height,'#d2bb92','#aa916b','#8a7254');}
    function furniture(o,base=0) {
      if(!o.drawing){paintFurniture(o,base);return;}
      const previous=drawing;drawing=o.drawing;
      try{paintFurniture({...o,...o.drawing,drawing:null},base);}finally{drawing=previous;}
    }
    function paintFurniture(o,base=0) {
      if(D.paintFurniture?.(o,{g,p,plane,box,line,ellipse,verticalPanel,shadow},base)){
        for(const child of o.children||[])furniture(child,base+21);
        return;
      }
      if(D.id==='rooftop'&&window.CampusBoothAssets?.paint(o,{g,p,plane,box,line,ellipse,poly,verticalPanel,drawingVector,platformIcon,circlePlane,font},base)){
        for(const child of o.children||[])furniture(child,base+21);
        return;
      }
      const {x,y,w,h,type}=o,c=o.color;
      if(!o.mounted&&!window.CampusDoors.isDoor(o)&&!['monitor','laptop','notebook','festival-banner','stair-handrail','stair-rail','stairs','glass-door','floor-portal'].includes(type))shadow(o,base);
      if(['desk','coffee','roundtable'].includes(type)) {
        for(const [lx,ly] of [[x+3,y+3],[x+w-6,y+3],[x+3,y+h-6],[x+w-6,y+h-6]])leg(lx,ly,base,17);
        box(x,y,w,h,base+17,4,c||(['coffee','roundtable'].includes(type)?'#f8f5e9':'#e4c99b'),'#bea37c','#a48a63');
        if(!c||c.startsWith('#e'))for(let yy=y+9;yy<y+h;yy+=15)line(p(x+3,yy,base+21.2),p(x+w-3,yy,base+21.2),'#a9885740',.7);
        if(o.powered)for(let i=0;i<4;i++) {
          const sx=h>w?x+3:x+8+i*(w-26)/3,sy=h>w?y+12+i*(h-30)/3:y+3;
          plane(sx,sy,8,12,base+21.5,'#faf9f0','#b7aa92');
          const a=p(sx+4,sy+4,base+22),b=p(sx+4,sy+9,base+22);ellipse(a.x,a.y,1,1,'#54615b');ellipse(b.x,b.y,1,1,'#54615b');
        }
      } else if(type==='chair') {
        for(const [lx,ly] of [[x+3,y+3],[x+w-5,y+3],[x+3,y+h-5],[x+w-5,y+h-5]])box(lx,ly,2,2,base,9,'#627270','#505f61','#3f4e51');
        box(x,y,w,h,base+9,4,c||'#758e91','#61787c','#4e6367');
        const back=o.dir==='up'?{x,y:y+h-4,w,h:4}:o.dir==='down'?{x,y,w,h:4}:o.dir==='left'?{x:x+w-4,y,w:4,h}:{x,y,w:4,h};
        box(back.x,back.y,back.w,back.h,base+12,13,c||'#7f9393','#647c80','#526b6f');
      } else if(['stool','ottoman'].includes(type)) {
        const q=p(x+w/2,y+h/2,base),rx=(w+h)/4,ry=rx*P.tilt;// the projected floor circle, so the seat stays inside its footprint
        g.fillStyle=c||'#b89b70';g.fillRect(q.x-rx,q.y-13,rx*2,13);ellipse(q.x,q.y,rx,ry,c||'#b89b70');
        ellipse(q.x,q.y-13,rx,ry,c||'#b89b70');ellipse(q.x-2,q.y-15,rx*.65,ry*.65,'#ffffff16');
      } else if(['sofa','bench'].includes(type)) {
        box(x,y,w,h,base+2,12,c||'#9a9e9c','#838989','#6d7776');
        const back=o.dir==='up'?{x,y:y+h-6,w,h:6}:o.dir==='down'?{x,y,w,h:6}:o.dir==='right'?{x,y,w:6,h}:{x:x+w-6,y,w:6,h};
        box(back.x,back.y,back.w,back.h,base+13,12,'#b2b6b1','#969e99','#7c8583');
        const count=o.seats||Math.max(2,Math.round(w/34));
        for(let i=0;i<count;i++)box(x+5+i*(w-10)/count,y+5,(w-10)/count-2,h-10,base+13,4,c||'#a7aba5','#8b9690','#7a8781');
        for(const ax of [x,x+w-6])box(ax,y,6,h,base+12,7,'#aeb4ac','#929b95','#7b8980');
      } else if(['counter','bar','cabinet'].includes(type)) {
        box(x,y,w,h,base,24,'#f3eddd','#d2c3a7','#b4a58a');box(x-1,y-1,w+2,h+2,base+24,3,c||'#f6f0e4','#d6c6a7','#bcae92');
        for(let xx=x+30;xx<x+w;xx+=38)line(p(xx,y+h,base+3),p(xx,y+h,base+23),'#9c8b7377',.8);
      } else if(['monitor','laptop','notebook'].includes(type)) {
        if(type==='notebook'){plane(x,y,w,h,base+1,'#f2f4e5','#a3ae9e');line(p(x+w/2,y,base+2),p(x+w/2,y+h,base+2),'#b6c3aa');}
        else {
          plane(x,y+h*.45,w,h*.55,base+1,type==='laptop'?'#c4d0c9':'#738785','#70847e');
          const vertical=o.orientation==='vertical',sw=vertical?h:w,axis=vertical?'y':'x';
          const sy=vertical?y:y+h*.15,sx=vertical?x+w*.3:x;
          verticalPanel(sx,sy,sw,11,base+3,'#30464b',axis);
          const v=axis==='x'?{x:sw-4,y:0}:{x:0,y:sw-4};
          verticalPanel(sx+(axis==='x'?2:0),sy+(axis==='y'?2:0),sw-4,7,base+5,'#8bb9b5',axis);
          line(p(sx,sy,base+2),p(sx+v.x,sy+v.y,base+2),'#516b68',1.2);
        }
      } else if(type==='wall-sign') {
        verticalPanel(x,y,w,22,base+9,'#897355','x');
        verticalPanel(x+3,y,w-6,18,base+11,'#f3eddd','x',o.text,'#28554e');
      } else if(type==='board'||type==='tv') {
        const axis=w>h?'x':'y',span=Math.max(w,h),sx=axis==='x'?x:x+w*.5,sy=axis==='x'?y+h*.65:y;
        if(type==='tv'){box(x+w*.3,y+h*.3,w*.4,h*.4,base,3,'#708983','#556c65','#40554e');}
        const bottom=base+(type==='board'?(o.mountHeight??10):12),height=type==='board'?25:29;
        verticalPanel(sx,sy,span,height,bottom,type==='board'?'#30483d':'#293f43',axis);
        verticalPanel(sx+(axis==='x'?4:0),sy+(axis==='y'?4:0),span-8,height-7,bottom+4,type==='board'?'#567565':'#266166',axis);
        line(p(sx,sy,bottom),p(sx+(axis==='x'?span:0),sy+(axis==='y'?span:0),bottom),'#a9b5a1',2);
      } else if(type==='noticeboard') {
        if(o.mounted){
          const height=o.panelHeight||29,bottom=o.mountHeight??6;
          const v=drawingVector(1,0),q=p(x,y+h,base+bottom+height);
          g.save();g.transform(v.x,v.y,0,1,q.x,q.y);
          playdataNoticeboard(w,height);g.restore();
        }else{
          const foot=footprint(o),bx=foot.x,by=foot.y+foot.h*.5,span=foot.w;
          for(const lx of [bx+4,bx+span-8]){box(lx,by-4,5,9,0,51,'#dcb77c','#b99158','#976c3e');box(lx-4,by-6,13,13,0,4,'#d5b075','#b58b4f','#97713e');}
          verticalPanel(bx,by,span,56,13,'#d8b47b');verticalPanel(bx+7,by,span-14,43,19,'#263a32','x','playdata');
          line(p(bx+12,by,28),p(bx+span-12,by,28),'#bdcbb8',.8);
        }
      } else if(type==='pillar') {
        box(x,y,w,h,base,57,'#f7f2e4','#e0d6bd','#c8bea5');box(x,y,w,h,base+44,6,'#8c7256','#927557','#796147');
      } else if(['bookshelf','bookshelf-side'].includes(type)) {
        const height=o.bookcaseHeight||23,levels=o.bookcaseHeight?3:1;
        box(x,y,w,h,base,height,'#f5f2e6','#d2b589','#baa079');
        const colors=['#769a9a','#d59e60','#f1eee2','#b96559','#607c87','#99aa7e'];
        const axis=w>h?'x':'y',span=axis==='x'?w:h;
        const sx=axis==='x'?x:x+w,sy=axis==='x'?y+h:y;
        if(levels>1)verticalPanel(sx,sy,span,height-5,base+2,'#8d7c63',axis);
        for(let level=0;level<levels;level++){
          const shelf=levels>1?base+3+level*(height-9)/levels:base+2;
          if(levels>1)verticalPanel(sx,sy,span,2,shelf,'#f5f2e6',axis);
          for(let at=4,i=0;at<span-4;at+=6,i++) {
            const xx=axis==='x'?x+at:x+w,yy=axis==='x'?y+h:y+at;
            verticalPanel(xx,yy,4,levels>1?13-i%3:14,shelf+2,colors[(i+level*2)%colors.length],axis);
          }
        }
        if(levels>1)for(const at of [0,span-3]){
          verticalPanel(sx+(axis==='x'?at:0),sy+(axis==='y'?at:0),3,height,base,'#f5f2e6',axis);
        }
        box(x,y,w,h,base+height,3,'#f6f4e8','#d8d2c1','#c3bba8');
      } else if(['water','coffee-machine','printer','bin','box'].includes(type)) {
        const height=type==='printer'?36:type==='water'?30:type==='box'?18:24;
        const color=type==='coffee-machine'?'#56655d':type==='bin'?(c||'#8b9c82'):type==='box'?'#c6a379':'#e6ede2';
        box(x,y,w,h,base,height,color,type==='box'?'#b58e5f':'#bbc8b8',type==='box'?'#997045':'#99ad9e');
        if(type!=='box') {
          verticalPanel(x+3,y+h,w-6,Math.min(12,height*.45),base+height*.28,type==='bin'?(c||'#739078'):'#34574f');
          plane(x+3,y+3,w-6,h*.32,base+height+.5,type==='bin'?'#edf2e5':'#b4d2c8',null);
        }
        if(type==='coffee-machine')verticalPanel(x+w*.35,y+h,8,7,base+3,'#f5f0db');
        if(type==='printer')box(x-2,y-2,w+4,h*.65,base+height,5,'#f4f5e9','#bfcdc0','#9aae9d');
      } else if(type==='plant') {
        box(x+w*.3,y+h*.3,w*.4,h*.4,base,14,'#eee7d2','#d4c7a6','#b7ac8d');
        const q=p(x+w/2,y+h/2,base+23);
        for(let i=0;i<8;i++){const a=i*Math.PI/4;ellipse(q.x+Math.cos(a)*w*.19,q.y+Math.sin(a)*h*.12-4,w*.15,h*.2,['#547f55','#779c66','#92ad78'][i%3]);}
      } else if(type==='fire-extinguisher') {
        if(o.portalGlow)compactPortalBase(o);
        const q=p(x+w/2,y+h/2),bw=13;
        g.fillStyle='#ce3c31';g.strokeStyle='#872e26';g.lineWidth=1;g.beginPath();g.roundRect(q.x-bw/2,q.y-26,bw,25,4);g.fill();g.stroke();
        g.fillStyle='#f5eee0';g.fillRect(q.x-4,q.y-19,8,8);line({x:q.x-4,y:q.y-28},{x:q.x+5,y:q.y-28},'#3f4a47',3);
        line({x:q.x+5,y:q.y-26},{x:q.x+8,y:q.y-10},'#3c4844',2);
      } else if(type==='terrace-bench') {
        const seatZ=o.backrest?20:6;
        if(h>w)for(const ly of [y+12,y+h-20])box(x+3,ly,w-6,8,base,seatZ,'#cdd0c4','#afb5a6','#989f92');
        else for(const lx of [x+12,x+w-20])box(lx,y+3,8,h-6,base,seatZ,'#cdd0c4','#afb5a6','#989f92');
        box(x,y,w,h,base+seatZ,5,'#e7c99a','#bd9f73','#a38a65');
        if(h>w)for(let xx=x+6;xx<x+w;xx+=7)line(p(xx,y+3,base+seatZ+5.2),p(xx,y+h-3,base+seatZ+5.2),'#9c78474a',.65);
        else for(let yy=y+6;yy<y+h;yy+=7)line(p(x+3,yy,base+seatZ+5.2),p(x+w-3,yy,base+seatZ+5.2),'#9c78474a',.65);
        if(o.backrest){const bx=h>w?(o.backSide==='right'?x+w-5:x):x,by=h>w?y:(o.backSide==='bottom'?y+h-5:y);box(bx,by,h>w?5:w,h>w?h:5,base+seatZ+5,19,'#e2c292','#b5966d','#957951');}
      } else if(type==='planter') {
        box(x,y,w,h,base,13,'#edf0e4','#d2dacb','#b6c1af');plane(x+4,y+4,w-8,h-8,base+13.5,'#62765a',null);
        const vertical=h>w,span=vertical?h:w;
        for(let at=7,i=0;at<span-4;at+=8,i++){const q=p(vertical?x+w/2:x+at,vertical?y+at:y+h/2,base+19);ellipse(q.x,q.y,5,5,['#87ac67','#a2bc79','#6d995c'][i%3]);}
        if(o.flowers)for(let at=12,i=0;at<span-8;at+=24,i++){
          const q=p(vertical?x+w/2:x+at,vertical?y+at:y+h/2,base+23),color=['#d09cba','#f1cc79','#b6a1d2'][i%3];
          for(let k=0;k<5;k++){const angle=k*Math.PI*2/5;ellipse(q.x+Math.cos(angle)*3,q.y+Math.sin(angle)*3,2.5,2.5,color);}ellipse(q.x,q.y,1.8,1.8,'#fff4c5');
        }
      } else if(type==='plaza-lamp') {
        const cx=x+w/2,cy=y+h/2;
        box(cx-6,cy-6,12,12,base,5,'#91a299','#74897e','#60786a');
        box(cx-3,cy-3,6,6,base+5,106,'#617a70','#4b655b','#39554b');
        box(cx-11,cy-11,22,22,base+110,4,'#91a398','#647e70','#526c5e');
        box(cx-9,cy-9,18,18,base+114,18,'#fff4cd','#f0dda8','#e2cf9b');
        for(const dx of [-10,7])for(const dy of [-10,7])box(cx+dx,cy+dy,3,3,base+114,19,'#61796e','#4e685b','#3a564a');
        box(cx-13,cy-13,26,26,base+133,5,'#789283','#536f60','#3b594d');
      } else if(type==='tree') {
        box(x+w*.42,y+h*.42,7,7,base,57,'#aa865f','#93714c','#795b3e');
        const q=p(x+w/2,y+h/2,base+69);
        for(const [dx,dy,rx,ry,c] of [[-16,0,19,15,'#719e62'],[16,0,19,15,'#8fb475'],[0,-18,20,18,'#93b77e'],[0,10,18,13,'#6b985e'],[-9,-11,12,12,'#a1c386']])ellipse(q.x+dx,q.y+dy,rx,ry,c);
      } else if(type==='exhibition-booth') {
        box(x,y,w,10,base,118,c||'#a7b7a5','#d8ddd3','#b8c4b2');
        brandBackdrop(x+18,y+11,w-36,84,base+24,o.platform,o.title);
      } else if(type==='booth-side') {
        box(x,y,w,h,base,45,'#f8f5ee','#d6d9cf','#bcc7b8');box(x+1,y+h-9,w-2,9,base,48,c||'#a7b7a5','#c5caba','#a5b49e');
      } else if(type==='creator-screen') {
        for(const xx of [x+16,x+w-22])box(xx,y+5,6,10,base,39,'#526466','#405358','#2e4146');
        verticalPanel(x,y+h,w,70,base+35,'#293b44');verticalPanel(x+6,y+h,w-12,58,base+41,'#f8edef');
        platformPanel(x+12,y+h,w-24,31,base+56,o.platform,'VIDEO / LIVE');
      } else if(type==='game-arcade') {
        box(x,y,w,h,base,56,c,'#465573','#33435d');box(x+2,y+5,w-4,h*.42,base+56,50,c,'#3e4c6b','#2b3c55');
        verticalPanel(x+8,y+h*.42,w-16,36,base+64,'#192e46');
        platformPanel(x+12,y+h*.42,w-24,24,base+71,'game','');
        box(x-1,y+h*.43,w+2,h*.38,base+54,7,'#c7d8ee','#6c88b5','#496595');
        const q=p(x+w*.3,y+h*.64,base+66);ellipse(q.x,q.y,6,3,'#213f61');line(q,{x:q.x,y:q.y-10},'#deebf7',2);ellipse(q.x,q.y-11,4,4,'#d85484');
        for(const [dx,dy,color] of [[.62,.58,'#f0c15d'],[.78,.66,'#ed879f']]){const b=p(x+w*dx,y+h*dy,base+64);ellipse(b.x,b.y,4,3,color);}
        verticalPanel(x+2,y+h,w-4,18,base+100,'#d4e5f6','x','ARCADE','#35577f');
      } else if(type==='game-gomoku-table') {
        for(const [dx,dy] of [[5,5],[w-9,5],[5,h-9],[w-9,h-9]])box(x+dx,y+dy,4,4,base,34,'#c7a273','#a98355','#896c47');
        box(x,y,w,h,base+34,7,'#e9c38d','#c59c69','#a68054');
        for(let i=0;i<7;i++){const dx=7+i*(w-14)/6,dy=7+i*(h-14)/6;line(p(x+dx,y+7,base+42),p(x+dx,y+h-7,base+42),'#a2794f',.8);line(p(x+7,y+dy,base+42),p(x+w-7,y+dy,base+42),'#a2794f',.8);}
        for(const [i,j,color] of [[1,1,'#2c3740'],[2,2,'#2c3740'],[3,3,'#2c3740'],[3,2,'#fffaf1'],[4,3,'#fffaf1']])circlePlane(x+7+i*(w-14)/6,y+7+j*(h-14)/6,3.5,base+43,color,'#877956');
      } else if(type==='game-brand-sign') {
        for(const dx of [5,w-9])box(x+dx,y+2,4,5,base+115,18,'#d9e3eb','#adc0d5','#839dbb');
        verticalPanel(x,y+h,w,25,base+114,'#253a58');
        const span=w/2;
        for(const [i,text,color] of [[0,'Nintendo','#d85760'],[1,'STEAM','#253d55']])verticalPanel(x+3+i*span,y+h,span-6,18,base+117,color,'x',text,'#fff8f5');
      } else if(type==='game-pc-station') {
        for(const [dx,dy] of [[4,4],[w-8,4],[4,h-8],[w-8,h-8]])box(x+dx,y+dy,4,4,base,32,'#7996b9','#527296','#3a5276');
        box(x,y,w,h,base+32,5,'#334c6d','#233c5b','#192d49');box(x+2,y+h-3,w-4,2,base+35,2,'#80d8ed','#76bfd9','#598daa');
        box(x+27,y+8,14,8,base+37,7,'#6c849f','#4b688c','#30486c');
        verticalPanel(x+6,y+17,w-31,44,base+43,'#0e2036');steamScreen(x+9,y+17,w-37,37,base+47);
        box(x+w-22,y+7,18,29,base+37,44,'#34455c','#1d2b42','#122239');
        verticalPanel(x+w-21,y+36,16,39,base+39,'#14253b');
        for(const dz of [48,62,75]){const q=p(x+w-13,y+36,base+dz);ellipse(q.x,q.y,4.3,4.3,'#7899ed');ellipse(q.x,q.y,2.4,2.4,'#23374e');}
        plane(x+8,y+h-24,43,14,base+38,'#182a40','#728ba8');
        for(let i=0;i<8;i++)for(let j=0;j<3;j++)plane(x+11+i*4.5,y+h-22+j*3.5,2.6,1.8,base+38.2,j===0?'#7cd4dd':'#a3b0e0',null);
        box(x+w-18,y+h-19,9,12,base+37,3,'#acc3de','#6e8cb4','#4b6a95');
        verticalPanel(x+3,y+h,w-6,15,base+10,'#274b67','x','STEAM PC','#e9faff');
      } else if(type==='game-console-display') {
        const nintendo=o.platform==='nintendo';
        box(x,y,w,h,base,32,nintendo?'#f2c7c3':'#cad8ee',nintendo?'#c98482':'#92aace',nintendo?'#ab666c':'#6c87b1');
        box(x,y,w,h,base+32,4,nintendo?'#fff1e9':'#f3f7ff',nintendo?'#efad9f':'#b5c6e2',nintendo?'#d1837d':'#8aa5cf');
        if(nintendo){
          box(x+w-24,y+5,18,10,base+36,18,'#3b4b62','#23364e','#142a42');
          handheldConsole(x+6,y+21,w-12,base+44);
          gameController(x+9,y+h-18,29,16,base+38,'#44566c');
          verticalPanel(x+3,y+h,w-6,15,base+10,'#d95e63','x','Nintendo','#fff9f1');
        }else{
          verticalPanel(x+4,y+18,29,29,base+43,'#233455');verticalPanel(x+7,y+18,23,22,base+47,'#7894d5','x','PS','#eef4ff');
          const sx=x+w-28;
          box(sx+4,y+5,14,17,base+36,66,'#263b5a','#182842','#112038');
          box(sx,y+3,4,21,base+36,73,'#f8fcff','#e2eaf7','#a2b7d7');box(sx+18,y+3,4,21,base+36,77,'#ffffff','#e4edf9','#afc4e4');
          line(p(sx+6,y+23,base+40),p(sx+6,y+23,base+100),'#6baaff',1.7);
          gameController(x+5,y+h-21,35,20,base+38,'#eef3fc',true);
          verticalPanel(x+3,y+h,w-6,15,base+10,'#4f75b4','x','PS5','#fffaff');
        }
      } else if(type==='game-controller-shelf') {
        box(x,y,w,h,base,12,'#567493','#3c5576','#2d4160');
        for(const dx of [0,w-4])box(x+dx,y+2,4,h-4,base+12,35,'#b9cce4','#8aa4c7','#6988b2');
        box(x,y,w,h,base+44,5,'#e4edf6','#a4bad4','#7996bd');
        for(const [i,color] of [[0,'#dc6570'],[1,'#5981ba'],[2,'#354f70'],[3,'#846ba9']])box(x+8+i*10,y+9,8,17,base+12,24,color,color,'#456084');
        gameController(x+5,y+h-21,29,17,base+50,'#273b58');gameController(x+29,y+h-25,28,17,base+50,'#f2f3f8',true);
        const q=p(x+11,y+12,base+52);
        line(q,{x:q.x,y:q.y-17},'#7088a9',2);ellipse(q.x,q.y,8,3,'#536c8e');
        g.beginPath();g.arc(q.x,q.y-19,10,Math.PI,Math.PI*2);g.strokeStyle='#3b4e70';g.lineWidth=4;g.stroke();
        for(const dx of [-10,6]){g.fillStyle='#7598d8';g.beginPath();g.roundRect(q.x+dx,q.y-20,5,13,2);g.fill();}
        verticalPanel(x+3,y+h,w-6,14,base+17,'#456b98','x','PAD & GEAR','#f6faff');
      } else if(type==='camera-tripod') {
        const cx=x+w/2,cy=y+h/2,top=p(cx,cy,base+62);
        for(const [dx,dy] of [[-24,16],[24,16],[0,-20]])line(top,p(cx+dx,cy+dy,base+2),'#425458',4);
        line(top,p(cx,cy,base+80),'#53676a',5);box(cx-17,cy-11,34,22,base+74,22,'#3e4f55','#263b44','#1b303a');
        const lens=p(cx+14,cy+12,base+85);ellipse(lens.x,lens.y,12,12,'#24313b');ellipse(lens.x,lens.y,7,7,'#84bfc7');ellipse(lens.x-2,lens.y-3,3,3,'#eaf9f6');
      } else if(type==='microphone-stand') {
        const q=p(x+w/2,y+h/2,base);ellipse(q.x,q.y,16,6,'#394d52');line(q,{x:q.x,y:q.y-77},'#4b6268',4);
        line({x:q.x,y:q.y-77},{x:q.x+16,y:q.y-89},'#41565f',4);ellipse(q.x+17,q.y-90,10,7,'#293d47');
        g.beginPath();g.moveTo(q.x+17,q.y-86);g.bezierCurveTo(q.x+35,q.y-50,q.x-6,q.y-35,q.x+8,q.y);g.strokeStyle='#607074';g.lineWidth=1.5;g.stroke();
      } else if(type==='creator-console') {
        for(const [dx,dy] of [[5,5],[w-10,5],[5,h-10],[w-10,h-10]])box(x+dx,y+dy,5,5,base,30,'#e5c6bd','#b99b95','#967c78');
        box(x,y,w,h,base+30,6,'#f6e3e4','#dcadb2','#b88992');
        verticalPanel(x+8,y+16,w*.62,43,base+38,'#2c414a');platformPanel(x+12,y+16,w*.62-8,30,base+44,o.platform,'');
        plane(x+18,y+h-22,w*.5,13,base+37,'#6a7880',null);box(x+w-26,y+15,18,28,base+37,31,'#5c7078','#394e5b','#293e48');
      } else if(type==='creator-award') {
        box(x,y,w,h,base,22,'#f2ded5','#d5baaf','#b89b96');verticalPanel(x+3,y+h,w-6,69,base+23,'#d8b05a');
        const q=p(x+w/2,y+h,base+60);platformIcon(q.x,q.y,28,'youtube');
      } else if(type==='psych-test-backdrop') {
        for(const xx of [x+5,x+w-11])box(xx,y+2,6,6,base,24,'#c9bfdf','#9d91bb','#81769e');
        box(x+8,y+3,w-16,h-4,base+24,8,'#e5def2','#bdb0d6','#9b8bb6');
        brandBackdrop(x+13,y+h-2,w-26,104,base+30,'psych','MIND TEST');
        verticalPanel(x+13,y+h-2,w-26,17,base+13,'#fffaf4','x','마음 유형 연구소','#645987');
      } else if(type==='psych-type-wheel') {
        box(x+4,y+8,w-8,h-12,base,18,'#b7a7cd','#927fa9','#78688e');
        verticalPanel(x+2,y+h-3,w-4,79,base+18,'#fbf8ff');
        const q=p(x+w/2,y+h-3,base+57),r=22;
        g.beginPath();g.arc(q.x,q.y,r,-Math.PI,0);g.lineTo(q.x+r,q.y);g.lineTo(q.x-r,q.y);g.closePath();
        const wheel=['#e9a99f','#e8c67b','#a6c8a3','#9bbad8','#c1a5d4'];
        wheel.forEach((color,i)=>{g.beginPath();g.moveTo(q.x,q.y);g.arc(q.x,q.y,r,Math.PI+i*Math.PI/wheel.length,Math.PI+(i+1)*Math.PI/wheel.length);g.closePath();g.fillStyle=color;g.fill();});
        g.strokeStyle='#fff';g.lineWidth=2;g.beginPath();g.moveTo(q.x,q.y);g.lineTo(q.x+2,q.y-r+3);g.stroke();ellipse(q.x,q.y,3.5,3.5,'#6f618a');
        verticalPanel(x+3,y+h,w-6,13,base+5,'#716391','x','MOOD TYPE','#fffaf4');
      } else if(type==='psych-question-kiosk') {
        box(x+3,y+5,w-6,h-10,base,16,'#bbaed0','#9788ad','#796b8e');
        verticalPanel(x+1,y+h,w-2,72,base+22,'#514a69');
        verticalPanel(x+5,y+h,w-10,59,base+29,'#fbfaff');
        verticalPanel(x+9,y+h-5,w-18,13,base+37,'#8273ac','x','Q. 01','#fff');
        for(let i=0;i<3;i++)verticalPanel(x+9,y+h-19-i*12,w-18,7,base+37,['#ebc7c3','#d8c8e9','#c2dfd0'][i]);
        box(x+w*.35,y+h-7,w*.3,7,base+18,25,'#9f90b6','#83739a','#6e6183');
      } else if(type==='psych-mood-cards') {
        box(x,y,w,h,base,11,'#bba98f','#987f65','#79654f');
        box(x+3,y+2,w-6,h-4,base+11,8,'#f7f2ea','#d6c9b6','#b2a18c');
        const colors=['#e5b3a8','#e6cf92','#a9c7b1','#a8b9d6'];
        for(let i=0;i<4;i++){
          const px=x+7+i*24,cardW=19;
          verticalPanel(px,y+h,cardW,33,base+20,colors[i]);
          const q=p(px+cardW/2,y+h,base+37);
          ellipse(q.x-3,q.y-2,1.25,1.6,'#5d5871');ellipse(q.x+3,q.y-2,1.25,1.6,'#5d5871');
          g.beginPath();g.arc(q.x,q.y+2,3.5,i%2?0:Math.PI,Math.PI*(i%2?1:2));g.strokeStyle='#665d74';g.lineWidth=1;g.stroke();
        }
      } else if(type==='photo-backdrop') {
        for(const xx of [x,x+w-7])box(xx,y,7,h,base,133,'#eadbef','#c9a8d2','#ac8ebc');
        brandBackdrop(x+5,y+h,w-10,125,base+7,'instagram','PHOTO');
      } else if(type==='ring-light') {
        const q=p(x+w/2,y+h/2,base),top={x:q.x,y:q.y-92};
        for(const dx of [-20,20])line({x:q.x,y:q.y-38},{x:q.x+dx,y:q.y+3},'#776d89',3);line(q,{x:q.x,y:q.y-70},'#877295',4);
        g.beginPath();g.arc(top.x,top.y,23,0,Math.PI*2);g.strokeStyle='#d09edc';g.lineWidth=9;g.stroke();g.strokeStyle='#fff9e8';g.lineWidth=5;g.stroke();
        g.fillStyle='#826690';g.fillRect(q.x-8,q.y-76,16,22);
      } else if(type==='phone-podium') {
        box(x,y,w,h,base,19,'#eeddf3','#cba2d8','#af87bd');const q=p(x+w/2,y+h/2,base+135),pw=49,ph=108;
        g.fillStyle='#6a527f';g.beginPath();g.roundRect(q.x-pw/2,q.y,pw,ph,8);g.fill();g.fillStyle='#fff9fa';g.beginPath();g.roundRect(q.x-pw/2+4,q.y+7,pw-8,ph-14,4);g.fill();
        platformIcon(q.x-8,q.y+20,11,'instagram');g.fillStyle='#baa0c1';g.fillRect(q.x+2,q.y+17,14,4);
        const colors=['#cd94c5','#e7b58b','#91bba8','#a89dcc'];
        for(let i=0;i<4;i++){g.fillStyle=colors[i];g.fillRect(q.x-18+(i%2)*20,q.y+34+Math.floor(i/2)*26,17,23);}
        g.fillStyle='#c693bf';g.fillRect(q.x-16,q.y+92,25,3);
      } else if(type==='photo-display') {
        box(x,y,w,h,base,28,'#f0e3f1','#d1b3d7','#b597c0');
        const slot=(w-14)/3,pw=Math.min(34,slot-3);
        for(let i=0;i<3;i++){const xx=x+7+i*slot;verticalPanel(xx,y+h,pw,40,base+29,'#fffaf4');verticalPanel(xx+4,y+h,pw-8,25,base+39,['#cc9dc4','#e6b694','#95bcad'][i]);}
      } else if(type==='fountain') {
        const cx=x+w/2,cy=y+h/2,r=Math.min(w,h)/2;
        cylinder(cx,cy,r,base,16,'#d9e1d6','#a3b4a8');cylinder(cx,cy,r-13,base+16,11,'#eef1e2','#b7c5b5');
        circlePlane(cx,cy,r-27,base+27,'#75c4d2','#4e9cac');
        for(const rr of [48,81,110])circlePlane(cx,cy,rr,base+27.4,null,'#c8f1ebaa');
        cylinder(cx,cy,23,base+27,46,'#e0e8d6','#a4baa9');cylinder(cx,cy,59,base+69,7,'#dce5d5','#adc4b2');circlePlane(cx,cy,48,base+76,'#a4dce0',null);
      } else if(type==='wall-poster') {
        const image=displayImages.get(o.id);
        if(image){
          const height=o.posterHeight||w*image.height/image.width;
          const q=p(x,y,base+(o.posterBottom||0)+height),v=drawingVector(1,0);
          g.save();g.transform(v.x,v.y,0,1,q.x,q.y);
          g.fillStyle='#d5c3a5';g.fillRect(-3,-3,w+6,height+6);
          g.drawImage(image,0,0,w,height);g.restore();
        }
      } else if(type==='plaza-display') {
        const image=displayImages.get(o.id),imageOnly=o.imageOnly===true;
        const centre=p(x+w/2,y+h/2,base),sw=o.screenWidth||250;
        const sh=imageOnly&&image?sw*image.height/image.width:o.screenHeight||150;
        const titleHeight=imageOnly?0:26,frame=imageOnly?3:7;
        // The panel follows the floor axis; a positive screen-X vector keeps images readable.
        const v=o.displayAxis==='y'?P.vector(0,-1):{x:1,y:0};
        g.save();g.transform(v.x,v.y,0,1,centre.x,centre.y);
        const q={x:0,y:0},left=-sw/2,top=-44-sh-titleHeight;
        for(const dx of [-sw*.32,sw*.32]){g.fillStyle='#596d68';g.fillRect(q.x+dx-4,q.y-50,8,50);ellipse(q.x+dx,q.y,14,4,'#87968b');}
        g.fillStyle='#344b46';g.beginPath();g.roundRect(left-frame,top-frame,sw+frame*2,sh+titleHeight+frame*2,frame);g.fill();
        if(!imageOnly){
          g.fillStyle=o.source==='menu'?'#e7d1a0':'#5e9784';g.fillRect(left,top,sw,titleHeight);
          g.font=`700 15px ${font}`;g.fillStyle=o.source==='menu'?'#5b533e':'#fffaf0';g.textAlign='center';g.textBaseline='middle';g.fillText(o.title,q.x,top+13,sw-14);
        }
        const iy=top+titleHeight;g.fillStyle=imageOnly?'#071326':'#fffdf6';g.fillRect(left,iy,sw,sh);
        if(image){const inset=imageOnly?0:4,scale=Math.min((sw-inset*2)/image.width,(sh-inset*2)/image.height),iw=image.width*scale,ih=image.height*scale;g.drawImage(image,q.x-iw/2,iy+(sh-ih)/2,iw,ih);}
        else if(!imageOnly){g.fillStyle=o.source==='menu'?'#f2ead6':'#e0eee5';g.fillRect(left+9,iy+9,sw-18,sh-18);g.font=`700 24px ${font}`;g.fillStyle='#47695b';g.fillText(o.source==='menu'?'구내식당':'PLAYDATA',q.x,iy+sh*.4);g.font=`500 14px ${font}`;g.fillText(o.source==='menu'?'오늘의 식단 사진':'광고 · 행사 안내 이미지',q.x,iy+sh*.65);}
        g.restore();
      } else if(type==='festival-booth') {
        for(const lx of [x+4,x+w-9])for(const ly of [y+4,y+h-9])box(lx,ly,5,5,base,72,'#efe9da','#c5bca9','#aaa08c');
        box(x,y+h-25,w,25,base,30,o.platform?'#fff5f7':'#f5ebd8',o.platform?(o.platform==='youtube'?'#eaa3a2':'#d6b3e1'):'#d8c7a4',o.platform?'#c8afc6':'#bea980');
        box(x-7,y-6,w+14,h+12,base+74,7,c,'#b8a894','#9b9385');
        for(let xx=x-7,i=0;xx<x+w+7;xx+=28,i++)plane(xx,y-6,Math.min(28,x+w+7-xx),h+12,base+81.2,i%2?'#fff8e7':c,null);
        if(o.platform) {
          platformPanel(x-7,y+h+6,w+14,24,base+55,o.platform,o.title);
          for(let i=0;i<3;i++) {
            box(x+24+i*61,y+h-20,39,8,base+31,17,'#fff5f7','#f2e5ef','#c8afc6');
            platformPanel(x+26+i*61,y+h-12,35,14,base+33,o.platform,'');
          }
        } else {
          verticalPanel(x-7,y+h+6,w+14,14,base+60,c,'x',o.title);
          for(let i=0;i<4;i++)box(x+18+i*45,y+h-18,17,13,base+31,8,['#e6c58e','#9cbb90','#cc896b','#f1e4c8'][i]);
        }
      } else if(type==='festival-stage') {
        const vertical=o.axis==='y',span=vertical?h:w,depth=vertical?w:h;
        const pos=(u,v)=>({x:x+(vertical?v:u),y:y+(vertical?u:v)}),at=(u,v,z)=>{const q=pos(u,v);return p(q.x,q.y,z);};
        const block=(u,v,a,b,z,height,top,front,side)=>{const q=pos(u,v);box(q.x,q.y,vertical?b:a,vertical?a:b,z,height,top,front,side);};
        box(x,y,w,h,base,17,'#d4b78b','#ac9069','#907957');
        for(let v=12;v<depth;v+=18)line(at(4,v,base+17.5),at(span-4,v,base+17.5),'#9c784747',.8);
        const backdrop=pos(40,18);verticalPanel(backdrop.x,backdrop.y,span-80,77,base+27,'#496e66',vertical?'y':'x','PLAYDATA FESTIVAL');
        for(const u of [14,span-22])block(u,8,8,10,base+17,115,'#647571','#52665f','#40574f');
        line(at(18,13,base+130),at(span-18,13,base+130),'#72827b',5);
        for(let i=1;i<7;i++){const q=at(i*span/7,18,base+119);ellipse(q.x,q.y,6,5,['#f3c477','#9ec6bd','#cca8d0'][i%3]);}
        const mic=at(span*.52,depth*.7,base+17);ellipse(mic.x,mic.y,10,4,'#52615d');line(mic,{x:mic.x,y:mic.y-38},'#586964',3);ellipse(mic.x+3,mic.y-40,5,3,'#3c504a');
        block(span*.22,depth*.45,45,32,base+17,28,'#cca788','#ad8666','#907152');
        const drum=at(span*.25,depth*.48,base+47);ellipse(drum.x,drum.y,19,9,'#f4ebd7');
        for(const u of [span*.2,span*.31]){const q=at(u,depth*.38,base+54);line({x:q.x,y:q.y+22},q,'#75837b',2);ellipse(q.x,q.y,14,5,'#dbc280');}
      } else if(type==='speaker') {
        box(x,y,w,h,base,79,'#40524e','#354943','#2a3d37');
        const q=p(x+w*.5,y+h,base+40);ellipse(q.x,q.y,13,18,'#1f342c');ellipse(q.x,q.y,6,8,'#4d6557');
      } else if(type==='festival-banner') {
        const vertical=o.axis==='y',span=vertical?h:w,pos=u=>({x:x+(vertical?0:u),y:y+(vertical?u:0)});
        for(const u of [0,span]){const q=pos(u);box(q.x,q.y,5,5,base,109,'#9f8c6b','#8f7c5b','#78664c');}
        const a=pos(0),b=pos(span);line(p(a.x,a.y,base+106),p(b.x,b.y,base+106),'#7e897b',1.2);
        for(let i=0;i<24;i++){const a=pos((i+.5)*span/24),q=p(a.x,a.y,base+91);ellipse(q.x,q.y,3,4,i%2?'#edbd65':'#8ab1a4');}
        const q=pos(span*.27);verticalPanel(q.x,q.y,span*.46,32,base+77,'#f2dfac',vertical?'y':'x',o.text,'#4e6657');
      } else if(type==='stair-handrail') {
        const horizontal=o.axis==='x',span=horizontal?w:h,pos=at=>({x:x+(horizontal?at:0),y:y+(horizontal?0:at)});
        const a=pos(0),b=pos(span),top=groundHeight(a.x,a.y),bottom=groundHeight(b.x,b.y);
        const rail=at=>top+(bottom-top)*Math.max(0,Math.min(1,at/span))+34;
        for(let i=0;i<=4;i++) {
          const at=span*i/4,q=pos(at),z=groundHeight(q.x,q.y);
          plane(q.x-2,q.y-2,7,7,z+.2,'#8ea391',null);
          box(q.x,q.y,3,3,z,Math.max(7,rail(at)-z),'#819888','#5b7867','#486855');
        }
        for(const [height,width,color] of [[0,3.2,'#496857'],[-16,1.6,'#7e9985']]) {
          const start=pos(-12),end=pos(span+12);
          line(p(start.x+1.5,start.y+1.5,rail(0)+height),p(a.x+1.5,a.y+1.5,rail(0)+height),color,width);
          line(p(a.x+1.5,a.y+1.5,rail(0)+height),p(b.x+1.5,b.y+1.5,rail(span)+height),color,width);
          line(p(b.x+1.5,b.y+1.5,rail(span)+height),p(end.x+1.5,end.y+1.5,rail(span)+height),color,width);
        }
        line(p(a.x+1.5,a.y+1.5,rail(0)+1),p(b.x+1.5,b.y+1.5,rail(span)+1),'#b8c7b3',.8);
      } else if(type==='photo-frame') {
        for(const lx of [x,x+w-7])box(lx,y,7,h,base,76,c||'#deccaa',c?'#b477aa':'#bdaa88',c?'#985f8f':'#a59473');
        if(o.platform)platformPanel(x,y,w,26,base+60,o.platform,'Instagram');
        else verticalPanel(x,y,w,17,base+63,'#729f96','x','PLAYDATA');
      } else if(type==='balloons') {
        const q=p(x+w/2,y+h/2,base+8);
        for(const [dx,dy,col] of [[-8,-66,c],[11,-72,'#edc55a'],[0,-83,'#bb9ecc']]){line(q,{x:q.x+dx,y:q.y+dy},'#a6a18c',.8);ellipse(q.x+dx,q.y+dy,8,11,col);}
      } else if(type==='booth-interaction') {
        const cx=x+w/2,cy=y+h/2,color=o.platform==='youtube'?'#dc5965':o.platform==='psych'?'#786aa9':o.platform==='game'?'#607ab4':'#6b9b84';
        circlePlane(cx,cy,21,base+1,'#fff9eac9',color);circlePlane(cx,cy,17,base+1.2,null,color);
        const q=p(cx,cy,base+3);g.save();g.font=`700 14px ${font}`;g.textAlign='center';g.textBaseline='middle';g.fillStyle=color;g.fillText('E',q.x,q.y);g.restore();
      } else if(type==='floor-portal') {
        if(o.portalStyle==='compact')compactPortalBase(o);else portalBase(o,base);
      } else if(type==='stairs') {
        stairTreads(o);stairRail(o,'left');stairRail(o,'right');
      } else if(type==='stair-rail') {
        stairRail(o.stairFlight,o.side);
      } else if(window.CampusDoors.isDoor(o)) {
        const opening=window.CampusDoors.leaf(o,false),leaf=window.CampusDoors.leaf(o),height=46;
        const along=t=>({x:leaf.start.x+leaf.dx*t,y:leaf.start.y+leaf.dy*t});
        const a=leaf.start,b=leaf.end;
        poly([p(a.x,a.y,base+2),p(b.x,b.y,base+2),p(b.x,b.y,base+height),p(a.x,a.y,base+height)],o.type==='sliding-door'?'#c6d7ceaa':'#9bcfd169','#739e9d',1.4);
        if(o.type==='sliding-door'){
          const track=window.CampusDoors.leaf(o,true);
          line(p(opening.start.x,opening.start.y,base+49),p(track.end.x,track.end.y,base+49),'#8ca59a',3.5);
          line(p(opening.start.x,opening.start.y,base+1),p(track.end.x,track.end.y,base+1),'#a9bdb3',1.4);
        }
        for(const point of [opening.start,opening.end])line(p(point.x,point.y,base),p(point.x,point.y,base+49),'#9cadab',2.5);
        line(p(opening.start.x,opening.start.y,base+49),p(opening.end.x,opening.end.y,base+49),'#c2d3cf',3);
        for(const point of [a,b])line(p(point.x,point.y,base+2),p(point.x,point.y,base+height),'#688d8c',1.8);
        for(const z of [2,height])line(p(a.x,a.y,base+z),p(b.x,b.y,base+z),'#92b9b6',2);
        const l=along(.12),r=along(.88),handle=along(.82);
        poly([p(l.x,l.y,base+19),p(r.x,r.y,base+19),p(r.x,r.y,base+27),p(l.x,l.y,base+27)],'#e4f3ee8c',null);
        line(p(l.x,l.y,base+7),p(r.x,r.y,base+39),'#f6fffdaf',1);
        line(p(handle.x,handle.y,base+15),p(handle.x,handle.y,base+30),'#425e60',3);
        for(const z of [10,36])line(p(a.x,a.y,base+z-2),p(a.x,a.y,base+z+2),'#4e7374',3);
      } else if(type==='glass-wall'||type==='sliding-door') {
        const span=type==='sliding-door'?Math.min(w,28):Math.max(w,h),axis=w>=h?'x':'y';
        const sx=type==='sliding-door'?x-span:x,sy=y+(axis==='x'?h*.5:0);
        verticalPanel(sx,sy,span,43,2,'#9bcfd166',axis);
        const end={x:sx+(axis==='x'?span:0),y:sy+(axis==='y'?span:0)};
        line(p(sx,sy,0),p(sx,sy,46),'#789f9b',2);line(p(end.x,end.y,0),p(end.x,end.y,46),'#789f9b',2);
        line(p(sx,sy,45),p(end.x,end.y,45),'#b6dcd1',3);line(p(sx,sy,8),p(end.x,end.y,37),'#f5fffcaa',1);
      } else if(type==='woodwall') {
        box(x,y,w,h,0,26,'#b99667','#a67e52','#8b6540');
      }
      for(const child of o.children||[])furniture(child,base+(type==='counter'||type==='bar'?27:21));
    }
    function footprint(o){if(window.CampusDoors.isDoor(o))return window.CampusDoors.footprint(o);return o.collision?{x:o.x+o.collision.x,y:o.y+o.collision.y,w:o.collision.w,h:o.collision.h}:o;}
    const supportTypes=new Set(['desk','counter','bar','coffee','roundtable']);
    const supportedTypes=new Set(['monitor','laptop','notebook','water','coffee-machine','bin']);
    const objects=D.objects.map(o=>({...o,children:[]})),attached=new Set();
    for(const o of objects.filter(o=>supportedTypes.has(o.type))) {
      const support=objects.find(s=>supportTypes.has(s.type)&&o.x+o.w/2>=s.x&&o.x+o.w/2<=s.x+s.w&&o.y+o.h/2>=s.y&&o.y+o.h/2<=s.y+s.h);
      if(support){support.children.push(o);attached.add(o.id);}
    }
    // Items on one tabletop are painted back to front, not in the order the map lists them.
    for(const o of objects)o.children.sort((a,b)=>a.x+a.w/2+a.y+a.h/2-(b.x+b.w/2+b.y+b.h/2));
    const floorCanvas=makeCanvas(P.width*resolution,P.height*resolution);g=floorCanvas.getContext('2d');g.scale(resolution,resolution);
    const floors=D.surfaces||[...D.rooms,...(D.entrance?[D.entrance]:[])];
    const floorColors={wood:'#e3cda8',class:'#ebeade',hall:'#f2ede2',office:'#e3e6dc',meeting:'#dfc8a5',stone:'#d5ddd5',orange:'#f2d9c2',yellow:'#f4e9be',roof:'#eeeade'};
    for(const r of floors){const inset=D.surfaces?0:4;box(r.x-inset,r.y-inset,r.w+inset*2,r.h+inset*2,D.surfaces?-10:-7,D.surfaces?(r.z||0)+10:7,D.surfaces?'#e9e6da':'#d3c7b2',D.surfaces?'#cccabe':'#bcac92',D.surfaces?'#b5bcb1':'#a79980');}
    for(const r of floors) {
      g.save();g.transform(P.c,P.tilt*P.s,-P.s,P.tilt*P.c,P.offsetX,P.offsetY-(r.z||0));
      g.save();g.beginPath();g.rect(r.x,r.y,r.w,r.h);g.clip();g.fillStyle=r.stair?'#e8e6dc':floorColors[r.floor]||'#e6eadf';g.fillRect(r.x,r.y,r.w,r.h);
      const wood=['wood','meeting','orange','yellow'].includes(r.floor),tile=wood?24:40;
      g.strokeStyle=wood?'#a0804730':'#788b7e20';g.lineWidth=.65;
      for(let yy=r.y;yy<r.y+r.h;yy+=tile){g.beginPath();g.moveTo(r.x,yy);g.lineTo(r.x+r.w,yy);g.stroke();}
      if(wood)for(let yy=r.y,i=0;yy<r.y+r.h;yy+=tile,i++)for(let xx=r.x+(i%3)*33;xx<r.x+r.w;xx+=115){g.beginPath();g.moveTo(xx,yy);g.lineTo(xx,yy+tile);g.stroke();}
      else if(!r.stair)for(let xx=r.x;xx<r.x+r.w;xx+=tile){g.beginPath();g.moveTo(xx,r.y);g.lineTo(xx,r.y+r.h);g.stroke();}
      g.restore();
      g.restore();
    }
    for(const r of floors.filter(r=>r.stair)) {
      const edge=r.x+r.w,next=Math.max(0,r.z-(D.terrace?.rise||12));
      poly([p(edge,r.y,r.z),p(edge,r.y+r.h,r.z),p(edge,r.y+r.h,next),p(edge,r.y,next)],'#b3bdac',null);
      line(p(edge,r.y,r.z+.4),p(edge,r.y+r.h,r.z+.4),'#fffcef',1.6);
      line(p(edge,r.y,next+.5),p(edge,r.y+r.h,next+.5),'#758e7438',.8);
      for(const [start,end] of D.terrace?.lanes||[])plane(edge-3,start+6,2,end-start-12,r.z+.2,'#9aaa9480',null);
    }
    for(const o of D.objects.filter(o=>o.type==='stairs'))stairTreads(o);
    for(const o of D.objects.filter(o=>o.type==='rug')){g.save();g.transform(P.c,P.tilt*P.s,-P.s,P.tilt*P.c,P.offsetX,P.offsetY-groundHeight(o.x,o.y));g.fillStyle=o.color||'#d3dbc4';g.fillRect(o.x,o.y,o.w,o.h);g.strokeStyle='#fff6dc88';g.strokeRect(o.x+5,o.y+5,o.w-10,o.h-10);g.restore();}
    if(D.id==='rooftop')window.CampusBoothAssets?.paintFloor(D,{g,p,plane,line,groundHeight});
    for(const o of D.objects.filter(o=>o.type==='plaza-paving')){
      g.save();g.transform(P.c,P.tilt*P.s,-P.s,P.tilt*P.c,P.offsetX,P.offsetY-groundHeight(o.x,o.y));
      if(o.style==='fountain'){
        const cx=o.x+o.w/2,cy=o.y+o.h/2,r=Math.min(o.w,o.h)/2;
        for(const [radius,color] of [[r,'#b9c9bc'],[r-7,'#e2ddca'],[r-19,'#f1ecdf']]){g.beginPath();g.arc(cx,cy,radius,0,Math.PI*2);g.fillStyle=color;g.fill();}
        g.strokeStyle='#b6bfae';g.lineWidth=1.6;
        for(const radius of [r-19,r-31,175]){g.beginPath();g.arc(cx,cy,radius,0,Math.PI*2);g.stroke();}
        for(let i=0;i<32;i++){const a=i*Math.PI/16;g.beginPath();g.moveTo(cx+Math.cos(a)*(r-31),cy+Math.sin(a)*(r-31));g.lineTo(cx+Math.cos(a)*(r-7),cy+Math.sin(a)*(r-7));g.stroke();}
      }else{
        g.fillStyle=o.style==='patio'?'#e7decc':'#dbe2d7';g.fillRect(o.x,o.y,o.w,o.h);
        g.strokeStyle='#b8c3b3';g.lineWidth=1.6;g.strokeRect(o.x+3,o.y+3,o.w-6,o.h-6);
        g.strokeStyle='#f7f6e9';g.lineWidth=.8;
        for(let xx=o.x+26;xx<o.x+o.w;xx+=26){g.beginPath();g.moveTo(xx,o.y+5);g.lineTo(xx,o.y+o.h-5);g.stroke();}
        for(let yy=o.y+26;yy<o.y+o.h;yy+=26){g.beginPath();g.moveTo(o.x+5,yy);g.lineTo(o.x+o.w-5,yy);g.stroke();}
      }
      g.restore();
    }
    D.paintFloor?.({g,P});
    function cacheSprite(o,paint,isWall=false) {
      const r=footprint(o),area=window.CampusDoors.isDoor(o)?window.CampusDoors.bounds(o):o,corners=[[area.x-12,area.y-12],[area.x+area.w+12,area.y-12],[area.x+area.w+12,area.y+area.h+12],[area.x-12,area.y+area.h+12]].map(([x,y])=>p(x,y));
      const b={x:Math.floor(Math.min(...corners.map(q=>q.x))-7),y:Math.floor(Math.min(...corners.map(q=>q.y))-groundHeight(o.x+o.w/2,o.y+o.h/2)-(o.renderHeight||110))};
      b.w=Math.ceil(Math.max(...corners.map(q=>q.x))-b.x+7);b.h=Math.ceil(Math.max(...corners.map(q=>q.y))-b.y+10+(o.renderDepth||0));
      if(o.type==='plaza-display') {
        const q=projectGround(o.x+o.w/2,o.y+o.h/2),sw=o.screenWidth||250,v=o.displayAxis==='y'?P.vector(0,-1):{x:1,y:0};
        const half=(sw/2+16),spreadX=Math.abs(v.x)*half,spreadY=Math.abs(v.y)*half;
        const image=displayImages.get(o.id),height=Math.max(o.renderHeight||230,o.imageOnly&&image?44+sw*image.height/image.width+8:0);
        b.x=Math.floor(q.x-spreadX-10);b.y=Math.floor(q.y-spreadY-height);
        b.w=Math.ceil(spreadX*2+20);b.h=Math.ceil(spreadY*2+height+14);
      }
      const canvas=makeCanvas(b.w*2,b.h*2);g=canvas.getContext('2d',{willReadFrequently:Boolean(o.name)});g.scale(2,2);g.translate(-b.x,-b.y);paint();
      return {o,r,b,canvas,isWall,depth:isWall&&D.backdropWalls&&((o.x<=15&&o.w<=10)||(o.y<=15&&o.h<=10))?-Infinity:p(r.x+r.w/2,r.y+r.h/2).y};
    }
    const sprites=[];
    for(const o of objects.filter(o=>!attached.has(o.id)&&!['rug','plaza-paving','floor-arrow','booth-collider'].includes(o.type))) {
      if(o.type==='stairs') {
        if(o.portalGlow){
          const center=o.portalAnchor||o.approach||[o.x+o.w/2,o.y+o.h*.12];
          const glow={type:'stair-portal',id:o.id+'-glow',x:center[0]-20,y:center[1]-20,w:40,h:40,renderHeight:80,solid:false,stairFlight:o};
          sprites.push(cacheSprite(glow,()=>compactPortalBase(glow)));
        }
        // Treads belong to the floor; only each side rail can overlap a walker.
        for(const side of ['left','right']) {
          const length=window.CampusStairs.railLength(D,o,side);
          if(!length)continue;
          const rail={type:'stair-rail',id:o.id+'-'+side,x:side==='left'?o.x:o.x+o.w-6,y:o.y,w:6,h:length,
            stairFlight:o,side,renderHeight:o.renderHeight,renderDepth:o.renderDepth};
          sprites.push(cacheSprite(rail,()=>furniture(rail)));
        }
      } else sprites.push(cacheSprite(o,()=>furniture(o,groundHeight(o.x+o.w/2,o.y+o.h/2))));
    }
    const wallTop=w=>w.topZ??w.height??D.wallHeight??35;
    // An end that butts into an equal or taller wall stops at its face, so the caps meet flush.
    // At an L corner only the y-axis wall gives way; otherwise both would paint a face inside the other.
    const wallReach=(wall,x,y)=>{const alongY=wall.x1===wall.x2,inside=(a,b,v,open)=>open?v>Math.min(a,b)&&v<Math.max(a,b):v>=Math.min(a,b)&&v<=Math.max(a,b);
      return D.walls.some(w=>w!==wall&&wallTop(w)>=wallTop(wall)&&(w.y1===w.y2?y===w.y1&&inside(w.x1,w.x2,x,!alongY):x===w.x1&&inside(w.y1,w.y2,y,true)))?-5:5;};
    // Segments only exist for depth sorting: paint them without their own end outlines so a wall reads as one piece.
    function wallBox(x,y,w,h,z,height,[top,front,side],alongX,first,last) {
      const a=p(x,y,z),b=p(x+w,y,z),c=p(x+w,y+h,z),d=p(x,y+h,z),A=p(x,y,z+height),B=p(x+w,y,z+height),C=p(x+w,y+h,z+height),E=p(x,y+h,z+height);
      poly([b,c,C,B],side,side,.8);poly([d,c,C,E],front,front,.8);poly([A,B,C,E],top,top,.8);
      const ink='#67584670',edge=(m,n)=>line(m,n,ink,.65);
      if(alongX){edge(A,B);edge(E,C);edge(d,c);if(first){edge(A,E);edge(d,E);}if(last){edge(b,c);edge(c,C);edge(b,B);}}
      else{edge(A,E);edge(B,C);edge(b,c);if(first){edge(A,B);edge(b,B);}if(last){edge(d,c);edge(c,C);edge(d,E);}}
    }
    for(const wall of D.walls) {
      const dx=wall.x2-wall.x1,dy=wall.y2-wall.y1,cuts=new Set([0,1]);
      const alongX=dy===0,len=Math.hypot(dx,dy),ux=dx/len,uy=dy/len,reach=[wallReach(wall,wall.x1,wall.y1),wallReach(wall,wall.x2,wall.y2)];
      // Split at terrain boundaries so wall feet meet each tread exactly.
      if(Number.isFinite(wall.topZ))for(const surface of D.surfaces||[]){
        const edges=dy===0?[surface.x,surface.x+surface.w]:dx===0?[surface.y,surface.y+surface.h]:[];
        for(const edge of edges){const at=dy===0?(edge-wall.x1)/dx:(edge-wall.y1)/dy;if(at>0&&at<1)cuts.add(at);}
      }
      const bands=[...cuts].sort((a,b)=>a-b);
      for(let band=1;band<bands.length;band++){
        const start=bands[band-1],end=bands[band],steps=D.continuousWalls?1:Math.ceil(Math.hypot(dx,dy)*(end-start)/72);
        for(let i=0;i<steps;i++){
          const a=start+(end-start)*i/steps,b=start+(end-start)*(i+1)/steps;
          const x1=wall.x1+dx*a,y1=wall.y1+dy*a,x2=wall.x1+dx*b,y2=wall.y1+dy*b;
          const z=groundHeight((x1+x2)/2,(y1+y2)/2),h=Number.isFinite(wall.topZ)?wall.topZ-z:wall.height??D.wallHeight??35;
          // Inner cuts overlap by half a unit only, enough to hide anti-aliasing hairlines.
          const e1=a===0?reach[0]:.5,e2=b===1?reach[1]:.5,X1=x1-ux*e1,Y1=y1-uy*e1,X2=x2+ux*e2,Y2=y2+uy*e2;
          const fx=alongX?0:5,fy=alongX?5:0,forward=ux+uy>0,first=forward?a===0:b===1,last=forward?b===1:a===0;
          const o={type:'wall',x:Math.min(X1,X2)-fx,y:Math.min(Y1,Y2)-fy,w:Math.abs(X2-X1)+fx*2,h:Math.abs(Y2-Y1)+fy*2,renderHeight:h+14,occludes:wall.occludes};
          const ends=[first&&reach[forward?0:1]>0,last&&reach[forward?1:0]>0],trim=first?0:.5,foot={x:o.x+(alongX?trim:0),y:o.y+(alongX?0:trim),w:o.w-(alongX?trim+(last?0:3.5):0),h:o.h-(alongX?0:trim+(last?0:4.5))};
          const body=[wall.color||D.wallColor||'#eee5d0',D.wallColor?'#cad5ca':'#c8b99a',D.wallColor?'#b5c3b5':'#b4a387'],cap=[D.wallColor?'#e7eee3':'#8d775b',D.wallColor?'#c9d4c3':'#917656',D.wallColor?'#b2c2ab':'#786449'];
          sprites.push(cacheSprite(o,()=>{if(D.wallShadows!==false)shadow(foot,z);wallBox(o.x,o.y,o.w,o.h,z,h,body,alongX,...ends);wallBox(o.x,o.y,o.w,o.h,z+h,4,cap,alongX,...ends);},true));
        }
      }
    }
    // Correct only explicitly marked long fixtures; retain the existing ordering elsewhere.
    const overlaps=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
    // Resolve the short wall -> fixture -> foreground chain without changing unrelated sprites.
    for(let pass=0;pass<3;pass++){
    for(const sprite of sprites.filter(s=>s.o.inFrontOfWalls))for(const wall of sprites.filter(s=>s.isWall)){
      const a=sprite.r,b=wall.r;
      const behind=(b.x+b.w<=a.x&&a.y<b.y+b.h&&a.y+a.h>b.y)||(b.y+b.h<=a.y&&a.x<b.x+b.w&&a.x+a.w>b.x);
      if(behind&&overlaps(sprite.b,wall.b))sprite.depth=Math.max(sprite.depth,wall.depth+.01);
    }
    // Tables and seats in front of a corrected fixture must still stay in front of it.
    for(const back of sprites.filter(s=>s.o.inFrontOfWalls))for(const front of sprites.filter(s=>!s.isWall&&s!==back)){
      const a=front.r,b=back.r;
      const ahead=(a.x>=b.x+b.w&&a.y<b.y+b.h&&a.y+a.h>b.y)||(a.y>=b.y+b.h&&a.x<b.x+b.w&&a.x+a.w>b.x);
      if(ahead&&overlaps(front.b,back.b))front.depth=Math.max(front.depth,back.depth+.01);
    }
    for(const sprite of sprites.filter(s=>s.o.occludes))for(const id of sprite.o.occludes){
      const behind=sprites.find(s=>s.o.id===id);
      if(behind)sprite.depth=Math.max(sprite.depth,behind.depth+.01);
    }
    }
    function orderSlidingLeaves(){
      for(const leaf of sprites.filter(s=>s.o.type==='sliding-door'&&s.o.interactiveDoor&&s.o.open)){
        for(const wall of sprites.filter(s=>s.isWall))if(overlaps(leaf.r,wall.r))leaf.depth=Math.max(leaf.depth,wall.depth+.02);
      }
    }
    orderSlidingLeaves();
    // Draw mounted panels after every supporting wall segment so the wall cannot cover half of a wide board.
    for(const sprite of sprites.filter(s=>s.o.mounted))for(const support of sprites.filter(s=>s.isWall)){
      const a=sprite.r,b=support.r;
      if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)sprite.depth=Math.max(sprite.depth,support.depth+.01);
    }
    // Centre depth alone misorders long or touching props, letting a prop cover one that stands in front of it.
    // Keep depth order as the tie-break, but draw a sprite after every overlapping sprite whose footprint lies
    // wholly behind it, and after anything it explicitly occludes.
    function orderSprites(){
      sprites.sort((a,b)=>a.depth-b.depth);
      const n=sprites.length,next=sprites.map(()=>[]),need=new Array(n).fill(0),index=new Map(sprites.map((s,i)=>[s.o.id,i]));
      const edge=(i,j)=>{next[i].push(j);need[j]++;};
      const behind=(A,B)=>(B.x>=A.x+A.w&&B.y<A.y+A.h&&B.y+B.h>A.y)||(B.y>=A.y+A.h&&B.x<A.x+A.w&&B.x+B.w>A.x);
      for(let i=0;i<n;i++)for(let j=0;j<n;j++)if(i!==j&&overlaps(sprites[i].b,sprites[j].b)&&behind(sprites[i].r,sprites[j].r))edge(i,j);
      sprites.forEach((s,j)=>{for(const id of s.o.occludes||[])if(index.has(id))edge(index.get(id),j);});
      // ponytail: O(n²) pairs and an O(n) scan per pick; fine for a few hundred sprites, use a heap if maps grow.
      const done=new Array(n).fill(false),order=[];
      for(let k=0;k<n;k++){
        let pick=-1;for(let i=0;i<n;i++)if(!done[i]&&need[i]===0){pick=i;break;}
        if(pick<0)pick=done.indexOf(false);// a cycle: fall back to depth order
        done[pick]=true;order.push(sprites[pick]);for(const j of next[pick])need[j]--;
      }
      sprites.splice(0,n,...order);
    }
    orderSprites();
    const hitSprites=objects.filter(o=>o.name).map(o=>sprites.find(s=>s.o.id===o.id)||cacheSprite(o,()=>{
      furniture(o,groundHeight(o.x,o.y)+27);
      if(o.portalGlow){const glow=sprites.find(s=>s.o.id===o.id+'-glow');if(glow)compactPortalBase(glow.o);}
    })).sort((a,b)=>b.depth-a.depth);
    function hitTest(x,y) {
      for(const s of hitSprites){const b=s.b;if(x<b.x||y<b.y||x>=b.x+b.w||y>=b.y+b.h)continue;
        const alpha=s.canvas.getContext('2d').getImageData(Math.floor((x-b.x)*2),Math.floor((y-b.y)*2),1,1).data[3];
        if(alpha>60)return D.objects.find(o=>o.id===s.o.id);
      }
      return null;
    }
    const labels=[];
    for(const r of D.rooms) {
      if(r.label===false)continue;
      const isClass=r.floor==='class';
      const x=r.labelX??r.x+r.w/2,y=r.labelY??r.y+9;
      labels.push({value:r.name,x,y,z:groundHeight(x,y)+48,size:r.id.startsWith('festival')?18:r.id.startsWith('lounge')?17:isClass?14:12});
    }
    function drawLabels(ctx,actors=[]){g=ctx;for(const a of labels){const q=p(a.x,a.y,a.z);if(actors.some(actor=>{const b=projectActor(actor);return Math.abs(q.x-b.x)<70&&q.y>b.y-53&&q.y<b.y+12;}))continue;label(a.value,a.x,a.y,a.size,'#4e5d56','#fffaf0ee',a.z);}}
    // Water is rendered per frame; the stone basin remains in the sprite cache.
    function fountainWater(o,t=0){
      const base=groundHeight(o.x+o.w/2,o.y+o.h/2),cx=o.x+o.w/2,cy=o.y+o.h/2;
      const seconds=portalMotion?.matches?0:(Number.isFinite(t)?t/1000:0);
      const centre=p(cx,cy,base+84),pulse=Math.sin(seconds*2.1);
      g.save();g.lineCap='round';
      for(let i=0;i<4;i++){
        const phase=(seconds*.28+i/4)%1,limit=Math.min(o.w,o.h)/2-29;
        g.globalAlpha=(1-phase)*.48;g.lineWidth=1.2;
        circlePlane(cx,cy,65+Math.max(0,limit-65)*phase,base+27.5,null,'#defcff');
      }
      g.globalAlpha=1;
      for(const [i,[dx,dy]] of [[-65,-22],[65,-22],[-50,26],[50,26]].entries()){
        const wave=Math.sin(seconds*2.4+i*.9),end={x:centre.x+dx,y:centre.y+60+dy};
        const a={x:centre.x+dx*.35,y:centre.y-62-wave*3},b={x:centre.x+dx*.92,y:centre.y-56-wave*3};
        g.beginPath();g.moveTo(centre.x,centre.y);g.bezierCurveTo(a.x,a.y,b.x,b.y,end.x,end.y);
        g.strokeStyle='#e5ffffbb';g.lineWidth=4+wave*.3;g.stroke();
        for(let drop=0;drop<4;drop++){
          const u=(seconds*.7+drop/4+i*.17)%1,v=1-u;
          ellipse(v*v*v*centre.x+3*v*v*u*a.x+3*v*u*u*b.x+u*u*u*end.x,
            v*v*v*centre.y+3*v*v*u*a.y+3*v*u*u*b.y+u*u*u*end.y,1.6,2.7,'#f4ffffee');
        }
        const splash=(seconds*1.2+i*.23)%1;
        g.globalAlpha=1-splash;
        g.beginPath();g.ellipse(end.x,end.y,5+splash*11,1.5+splash*3,0,0,Math.PI*2);
        g.strokeStyle='#deffff';g.lineWidth=1;g.stroke();g.globalAlpha=1;
        ellipse(end.x,end.y,9+wave,2.8,'#d6ffff88');
      }
      const top={x:centre.x,y:centre.y-58-pulse*3};
      line(centre,top,'#d8ffffcc',5);
      for(let i=0;i<5;i++){
        const u=(seconds*1.1+i/5)%1;
        ellipse(centre.x,centre.y+(top.y-centre.y)*u,1.6,2.6,'#ffffffed');
      }
      ellipse(top.x,top.y-1,4.5,3.6,'#f4ffff');g.restore();
    }
    function drawSprite(ctx,s,alpha=1){ctx.globalAlpha=alpha;ctx.drawImage(s.canvas,s.b.x,s.b.y,s.b.w,s.b.h);ctx.globalAlpha=1;}
    const scene=makeCanvas(P.width*resolution,P.height*resolution),sg=scene.getContext('2d');
    function repaintScene(){sg.setTransform(1,0,0,1,0,0);sg.clearRect(0,0,scene.width,scene.height);sg.setTransform(resolution,0,0,resolution,0,0);city?.draw(sg);sg.drawImage(floorCanvas,0,0,P.width,P.height);for(const s of sprites){drawSprite(sg,s);if(s.o.type==='fountain'){g=sg;fountainWater(s.o,0);}if(s.o.type==='floor-portal'){g=sg;if(s.o.portalStyle==='compact')compactPortalEnergy(s.o);else portalEnergy(s.o,groundHeight(s.o.x+s.o.w/2,s.o.y+s.o.h/2));}else if(s.o.type==='stair-portal'||(s.o.type==='fire-extinguisher'&&s.o.portalGlow)){g=sg;compactPortalEnergy(s.o);}}for(const sprite of sprites.filter(sprite=>sprite.o.type==='wall-sign'))drawSprite(sg,sprite);drawLabels(sg);}
    repaintScene();
    function setDisplayImage(id,image){const s=sprites.find(s=>s.o.id===id&&(s.o.type==='plaza-display'||s.o.type==='wall-poster'));if(!s)return false;const depth=s.depth;displayImages.set(id,image);Object.assign(s,cacheSprite(s.o,()=>furniture(s.o,groundHeight(s.o.x+s.o.w/2,s.o.y+s.o.h/2))));s.depth=depth;repaintScene();return true;}
    function setDoorState(id,open){
      const door=D.objects.find(o=>o.id===id&&window.CampusDoors.isDoor(o)),sprite=sprites.find(s=>s.o.id===id);
      if(!door||!sprite||typeof open!=='boolean')return false;
      door.open=sprite.o.open=open;Object.assign(sprite,cacheSprite(sprite.o,()=>furniture(sprite.o,groundHeight(door.x,door.y))));
      orderSlidingLeaves();
      orderSprites();hitSprites.sort((a,b)=>b.depth-a.depth);repaintScene();return true;
    }
    function drawActor(ctx,actor,t,zoom,labelText,self) {
      const q=projectActor(actor);ctx.save();ctx.translate(q.x,q.y);
      const jumpHeight=window.CampusJump?.height(actor,t)||0,jumpScale=window.CampusJump?.squash(actor,t)||1;
      ctx.fillStyle=jumpHeight?'#304d4028':'#304d4038';ctx.beginPath();ctx.ellipse(0,1,7-jumpHeight*.025,2.8-jumpHeight*.008,0,0,Math.PI*2);ctx.fill();
      ctx.translate(0,-jumpHeight);ctx.scale(1/jumpScale,jumpScale);
      ctx.translate(0,-(actor.stairMotion?.lift||0));ctx.rotate(actor.stairMotion?.lean||0);
      window.CampusPoke?.react(ctx,actor,t,P);window.CampusPoke?.draw(ctx,actor,t,P,true);
      const poked=window.CampusPoke?.pose(actor,t)||actor,body=window.CampusJump?.pose(poked,t)||poked;
      ctx.save();if(actor.seated){ctx.beginPath();ctx.rect(-22,-45,44,34);ctx.clip();}
      if(!D.drawActor?.(ctx,body,t)&&!window.CampusAvatars?.draw(ctx,body,t)){
        ctx.fillStyle=actor.color||'#4e9b91';ctx.fillRect(-5,-21,10,18);
        ctx.fillStyle='#e9bc98';ctx.fillRect(-5,-30,10,9);
      }
      ctx.restore();
      window.CampusPoke?.draw(ctx,actor,t,P,false);window.CampusPoke?.contact(ctx,actor,t,P);
      ctx.restore();
      if(labelText)drawName(ctx,actor,zoom,labelText,self,t);
    }
    // Draw names above the scenery so a pillar cannot cover another user's name.
    function drawName(ctx,actor,zoom,labelText,self,t=performance.now()) {
      const q=projectActor(actor),scale=1/Math.max(zoom,.55);ctx.save();ctx.translate(q.x,q.y-(window.CampusJump?.height(actor,t)||0)-(window.CampusAvatars?.size||40)-12*scale);ctx.scale(scale,scale);ctx.font=`600 11px ${font}`;const w=Math.min(155,ctx.measureText(labelText).width+16);ctx.fillStyle='#ffffffec';ctx.beginPath();ctx.roundRect(-w/2,-9,w,18,5);ctx.fill();ctx.fillStyle=self?'#256b59':'#3e5764';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(labelText,0,0,w-8);ctx.restore();
    }
    // Sorting actors into the sprite list with a pairwise rule is not transitive, so a long prop could end up in
    // front of someone standing behind it. Instead slot each actor right after the last sprite on screen with it
    // that lies behind it, judged at the prop's floor point nearest the actor rather than at its centre.
    function placeActors(visible,actors){
      const clamp=(v,a,b)=>Math.min(Math.max(v,a),b);
      const slots=actors.map(actor=>{
        const q=projectActor(actor),area={x:q.x-14,y:q.y-50,w:28,h:54},depth=p(actor.x,actor.y).y;let at=0;
        visible.forEach((s,i)=>{
          if(!overlaps(s.b,area))return;
          const r=s.r,inside=actor.x>=r.x&&actor.x<=r.x+r.w&&actor.y>=r.y&&actor.y<=r.y+r.h;
          if(inside?s.depth<=depth:p(clamp(actor.x,r.x,r.x+r.w),clamp(actor.y,r.y,r.y+r.h)).y<depth)at=i+1;
        });
        return {actor,at,depth};
      }).sort((a,b)=>a.at-b.at||a.depth-b.depth);
      const entities=[];let k=0;
      visible.forEach((s,i)=>{while(k<slots.length&&slots[k].at===i)entities.push(slots[k++]);entities.push(s);});
      while(k<slots.length)entities.push(slots[k++]);
      return entities;
    }
    function draw(ctx,{camera,actors,t=0,path=[],hover,nearby,viewportWidth,viewportHeight,showNicknames=true,floorOverlay}) {
      city?.draw(ctx);
      ctx.drawImage(floorCanvas,0,0,P.width,P.height);
      g=ctx;
      floorOverlay?.(ctx,P);
      if(path.length){ctx.strokeStyle='#2586789c';ctx.lineWidth=1.5/camera.zoom;ctx.setLineDash([4/camera.zoom,5/camera.zoom]);ctx.beginPath();let q=projectGround(actors[0].x,actors[0].y);ctx.moveTo(q.x,q.y);for(const a of path){q=projectGround(a.x,a.y);ctx.lineTo(q.x,q.y);}ctx.stroke();ctx.setLineDash([]);}
      const focused=hover||nearby;if(focused&&focused.type!=='stairs'&&focused.type!=='floor-portal'){const r=footprint(focused);plane(r.x-3,r.y-3,r.w+6,r.h+6,groundHeight(r.x+r.w/2,r.y+r.h/2)+.5,'#37a29022','#258876');}
      const visible=sprites.filter(s=>{const b=s.b;return b.x*camera.zoom+camera.x<viewportWidth&&b.y*camera.zoom+camera.y<viewportHeight&&(b.x+b.w)*camera.zoom+camera.x>0&&(b.y+b.h)*camera.zoom+camera.y>0;});
      const entities=placeActors(visible,actors);
      for(const e of entities){
        if(e.actor){drawActor(ctx,e.actor,t,camera.zoom);continue;}
        const blocked=e.isWall&&actors.some(a=>{const q=projectActor(a),b=e.b;return q.x>b.x+10&&q.x<b.x+b.w-10&&q.y>b.y+55&&q.y<b.y+b.h+7&&q.y<e.depth+20;});
        drawSprite(ctx,e,blocked ? .27 : 1);
        if(e.o.type==='fountain')fountainWater(e.o,t);
        if(e.o.type==='floor-portal'){g=ctx;if(e.o.portalStyle==='compact')compactPortalEnergy(e.o,portalMotion?.matches?0:t);else portalEnergy(e.o,groundHeight(e.o.x+e.o.w/2,e.o.y+e.o.h/2),portalMotion?.matches?0:t);}
        else if(e.o.type==='stair-portal'||(e.o.type==='fire-extinguisher'&&e.o.portalGlow)){g=ctx;compactPortalEnergy(e.o,portalMotion?.matches?0:t);}
      }
      for(const sprite of visible.filter(sprite=>sprite.o.type==='wall-sign'))drawSprite(ctx,sprite);
      drawLabels(ctx,actors);
      for(const actor of actors)if(actor===actors[0]||(showNicknames&&actor.nickname))drawName(ctx,actor,camera.zoom,actor===actors[0]?'나':actor.nickname,actor===actors[0],t);
    }
    // 확대·카메라 이동 전 광고 이미지의 실제 사각형을 투영한다. 테두리는 포함하지 않는다.
    function displayPolygon(id){
      const o=D.objects.find(o=>o.id===id),image=displayImages.get(id);
      if(!o||!image)return null;
      const q=projectGround(o.x+o.w/2,o.y+o.h/2),sw=o.screenWidth||250;
      const sh=o.imageOnly?sw*image.height/image.width:o.screenHeight||150;
      const v=o.displayAxis==='y'?P.vector(0,-1):{x:1,y:0};
      return [[-sw/2,-44-sh],[sw/2,-44-sh],[sw/2,-44],[-sw/2,-44]].map(([x,y])=>({x:q.x+v.x*x,y:q.y+v.y*x+y}));
    }
    return {projection:P,scene,draw,footprint,drawActor,hitTest,projectGround,projectActor,unprojectGround,setDisplayImage,setDoorState,displayPolygon};
  }
  window.CampusIsometric={createProjection,create};
})();
