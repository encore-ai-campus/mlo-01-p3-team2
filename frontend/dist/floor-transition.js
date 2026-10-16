/* Route-aware stair and portal animation during the existing three-second floor transfer. */
(() => {
  'use strict';
  const DURATION_MS=3000;
  const floorName=id=>id==='rooftop'?'옥상':'18층';
  function animate(dialog,{from,to,avatar,kind}){
    const canvas=document.getElementById('floorTransitionCanvas'),g=canvas?.getContext('2d');
    const up=to==='rooftop',start=performance.now(),reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const label=document.getElementById('floorTransitionLabel'),bar=document.getElementById('floorTransitionProgress');
    document.getElementById('floorTransitionFrom').textContent=floorName(from);
    document.getElementById('floorTransitionTo').textContent=floorName(to);
    label.textContent=kind==='portal'?(up?'포탈로 옥상 이동 중':'포탈로 18층 이동 중'):(up?'옥상으로 올라가는 중':'18층으로 내려가는 중');
    document.getElementById('floorTransitionSubtitle').textContent=kind==='portal'?'포탈을 통해 다른 공간으로 순간이동하고 있어요':'계단을 따라 다음 공간으로 이동하고 있어요';
    dialog.setAttribute('aria-label',label.textContent);
    let frame=0,stopped=false,waiting=false;
    function draw(t){
      if(stopped)return;
      const elapsed=Math.max(0,t-start),travel=Math.min(1,Math.max(0,(elapsed-180)/2450));
      bar.style.transform=`scaleX(${Math.min(.94,elapsed/DURATION_MS*.94)})`;
      if(elapsed>=DURATION_MS&&!waiting){waiting=true;label.textContent='도착할 공간을 준비하고 있어요';}
      if(g&&kind==='portal'){window.CampusPortalTransition.draw(g,{elapsed,avatar,reduced,from,to});}
      else if(g){
        g.clearRect(0,0,640,340);
        const poly=(points,color,stroke)=>{g.beginPath();points.forEach(([x,y],i)=>i?g.lineTo(x,y):g.moveTo(x,y));g.closePath();g.fillStyle=color;g.fill();if(stroke){g.strokeStyle=stroke;g.lineWidth=1.4;g.stroke();}};
        // An airy window and a quiet landing keep the stairs readable at small sizes.
        g.fillStyle='#e6ecdf';g.beginPath();g.roundRect(280,24,146,130,[65,65,8,8]);g.fill();
        g.fillStyle='#f9f6eb';g.fillRect(350,26,5,127);g.fillRect(282,91,142,4);
        g.fillStyle='#d1dbc880';g.beginPath();g.arc(405,47,25,0,Math.PI*2);g.fill();
        g.save();g.translate(318,298);g.scale(1,.16);const shadow=g.createRadialGradient(0,0,0,0,0,245);shadow.addColorStop(0,'#91785430');shadow.addColorStop(1,'#91785400');g.fillStyle=shadow;g.beginPath();g.arc(0,0,245,0,Math.PI*2);g.fill();g.restore();
        // The stair face rises to the right; the avatar reverses direction on descent.
        const left=122,base=278,tread=47,rise=19,count=7;
        const outline=[[left-46,base],[left-46,base+18],[left+count*tread+52,base+18],[left+count*tread+52,base-count*rise]];
        for(let i=count-1;i>=0;i--)outline.push([left+(i+1)*tread,base-(i+1)*rise],[left+i*tread,base-(i+1)*rise],[left+i*tread,base-i*rise]);
        poly(outline,'#c9b28c','#b49b74');
        for(let i=0;i<count;i++){
          const x=left+i*tread,y=base-(i+1)*rise;
          poly([[x,y],[x+tread,y],[x+tread+12,y-8],[x+12,y-8]],'#f6ead2','#d6c29f');
          g.strokeStyle='#ae936b55';g.beginPath();g.moveTo(x,y+rise);g.lineTo(x+tread,y+rise);g.stroke();
        }
        poly([[left-46,base],[left,base],[left+12,base-8],[left-34,base-8]],'#f6ead2','#d6c29f');
        poly([[left+count*tread,base-count*rise],[left+count*tread+52,base-count*rise],[left+count*tread+64,base-count*rise-8],[left+count*tread+12,base-count*rise-8]],'#f6ead2','#d6c29f');
        // Back rail is drawn before the character, leaving the walking silhouette clear.
        g.strokeStyle='#b09a76';g.lineWidth=3;g.lineCap='round';
        for(const i of [0,2,4,6]){const x=left+i*tread+19,y=base-i*rise-13;g.beginPath();g.moveTo(x,y);g.lineTo(x,y-53);g.stroke();}
        g.beginPath();g.moveTo(left+19,base-66);g.lineTo(left+6*tread+19,base-6*rise-66);g.stroke();
        const position=reduced?3.5:(up?travel:1-travel)*8;
        const step=Math.min(7,Math.floor(position)),fraction=position-step;
        const smooth=fraction*fraction*(3-2*fraction);
        const x=left-22+position*tread,y=base-Math.min(7,step+smooth)*rise-7-(reduced?0:Math.sin(fraction*Math.PI)*5);
        g.save();g.translate(x,y);g.scale(2.15,2.15);
        const drawn=window.CampusAvatars?.draw(g,{avatar,dir:up?'right':'left',moving:!reduced&&travel<1,walkTime:elapsed/1000},t);
        if(!drawn){g.fillStyle='#4e9b91';g.beginPath();g.roundRect(-8,-28,16,21,4);g.fill();g.fillStyle='#e5ba91';g.beginPath();g.arc(0,-34,9,0,Math.PI*2);g.fill();g.fillStyle='#4b4b43';g.fillRect(-7,-8,5,8);g.fillRect(2,-8,5,8);}
        g.restore();
        g.fillStyle='#978160';g.font='600 12px system-ui,sans-serif';g.textAlign='center';g.fillText('18F',86,319);g.fillText('ROOFTOP',504,187);
      }
      frame=requestAnimationFrame(draw);
    }
    draw(start);
    return ()=>{stopped=true;cancelAnimationFrame(frame);bar.style.transform='scaleX(0)';};
  }
  window.CampusFloorTransition={
    DURATION_MS,
    kindFor:objectId=>['extinguisher-meeting2','roof-lounge2-portal'].includes(objectId)?'portal':'stairs',
    create({onStart=()=>{},onFinish=()=>{},isCancelled=()=>window.CampusSession?.ending}={}){
      const dialog=document.getElementById('floorTransitionDialog');
      let blocking=false;
      dialog.addEventListener('cancel',event=>event.preventDefault());
      async function run(commit,{from='campus',to='rooftop',avatar='male-1',kind='stairs'}={}){
        if(blocking||isCancelled())return false;
        blocking=true;let stop=()=>{};
        try{
          onStart();stop=animate(dialog,{from,to,avatar,kind});
          dialog.showModal();dialog.focus({preventScroll:true});
          await new Promise(resolve=>setTimeout(resolve,DURATION_MS));
          if(isCancelled())return false;
          const result=await commit();
          // Reveal only after the destination has painted.
          await new Promise(resolve=>requestAnimationFrame(resolve));
          return result;
        }finally{
          stop();if(dialog.open)dialog.close();blocking=false;onFinish();
          window.dispatchEvent(new Event('campus:floor-transition-end'));
        }
      }
      return {run,get blocking(){return blocking;},durationMs:DURATION_MS};
    },
  };
})();
