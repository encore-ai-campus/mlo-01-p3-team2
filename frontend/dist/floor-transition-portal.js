/* Canvas-only teleport effect for the extinguisher/rooftop shortcut. */
(()=>{
 'use strict';
 const clamp=x=>Math.max(0,Math.min(1,x)),ease=x=>{x=clamp(x);return x*x*(3-2*x);};
 function draw(g,{elapsed,avatar,reduced,from,to}){
  g.clearRect(0,0,640,340);
  const phase=clamp(elapsed/2800),time=reduced?0:elapsed/1000;
  function oval(x,y,rx,ry,color,width=2){g.beginPath();g.ellipse(x,y,rx,ry,0,0,Math.PI*2);g.strokeStyle=color;g.lineWidth=width;g.stroke();}
  function portal(x,color){
   g.save();
   const glow=g.createRadialGradient(x,195,12,x,195,112);glow.addColorStop(0,color+'28');glow.addColorStop(.65,color+'12');glow.addColorStop(1,color+'00');g.fillStyle=glow;g.fillRect(x-115,80,230,230);
   g.fillStyle='#d7c4a3';g.beginPath();g.ellipse(x,276,76,17,0,0,Math.PI*2);g.fill();
   g.fillStyle='#f7ecd7';g.beginPath();g.ellipse(x,271,76,17,0,0,Math.PI*2);g.fill();
   oval(x,269,62,11,color+'66',1.2);
   g.fillStyle=color+'13';g.beginPath();g.ellipse(x,194,49,76,0,0,Math.PI*2);g.fill();
   oval(x,194,49,76,color+'aa',3);oval(x,194,42,68,color+'35',1.3);
   g.save();g.translate(x,194);g.scale(.64,1);
   for(let i=0;i<3;i++){const angle=time*(i%2?-.6:.6)+i*2.1;g.beginPath();g.arc(0,0,73,angle,angle+.68);g.strokeStyle=i===1?'#fffdf1':color;g.lineWidth=3;g.lineCap='round';g.stroke();}
   g.restore();
   for(let i=0;i<8;i++){const a=i*Math.PI/4+time*.3,px=x+Math.cos(a)*(64+i%2*8),py=194+Math.sin(a)*92;g.fillStyle=i%2?color+'85':'#b79a6c85';g.beginPath();g.arc(px,py,i%3===0?2.2:1.4,0,Math.PI*2);g.fill();}
   g.restore();
  }
  // A quiet path ties the two portals together without changing simulation positions.
  g.save();g.setLineDash([3,9]);g.strokeStyle='#b8c7b2';g.lineWidth=1.5;g.beginPath();g.moveTo(224,267);g.quadraticCurveTo(320,310,416,267);g.stroke();g.restore();
  portal(176,'#5d9d90');portal(464,'#a595bc');
  g.fillStyle='#968269';g.font='600 12px system-ui,sans-serif';g.textAlign='center';g.fillText(from==='rooftop'?'ROOFTOP':'18F',176,315);g.fillText(to==='rooftop'?'ROOFTOP':'18F',464,315);
  let x,alpha=1,size=1,moving=false;
  if(reduced){x=510;}
  else if(phase<.32){x=104+72*ease(phase/.32);moving=true;alpha=1-ease((phase-.2)/.12);size=1-.3*ease((phase-.2)/.12);}
  else if(phase<.63){x=176;alpha=0;}
  else{x=464+58*ease((phase-.7)/.3);alpha=ease((phase-.63)/.16);size=.7+.3*alpha;moving=phase>.74&&phase<1;}
  if(alpha>0){
   g.save();g.globalAlpha=alpha;g.translate(x,264);g.scale(2.15*size,2.15*size);
   const drawn=window.CampusAvatars?.draw(g,{avatar,dir:'right',moving,walkTime:elapsed/1000},elapsed);
   if(!drawn){g.fillStyle='#4e9b91';g.fillRect(-8,-27,16,22);g.fillStyle='#e5ba91';g.beginPath();g.arc(0,-34,9,0,Math.PI*2);g.fill();}
   g.restore();
  }
  if(!reduced&&phase>.29&&phase<.73){
   const q=ease((phase-.29)/.44),x=176+288*q,y=208-Math.sin(q*Math.PI)*49;
   for(let i=0;i<7;i++){const trail=x-i*9;g.fillStyle=i%2?'#a595bc70':'#5d9d9070';g.beginPath();g.arc(trail,y+i*1.5,Math.max(1,4-i*.45),0,Math.PI*2);g.fill();}
   const glow=g.createRadialGradient(x,y,0,x,y,24);glow.addColorStop(0,'#fffdf1');glow.addColorStop(.3,'#d9e6c9b0');glow.addColorStop(1,'#d9e6c900');g.fillStyle=glow;g.fillRect(x-24,y-24,48,48);
  }
 }
 window.CampusPortalTransition={draw};
})();
