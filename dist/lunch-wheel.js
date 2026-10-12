/* A personal lunch picker; the final slice and the displayed result always agree. */
(() => {
  'use strict';
  const OPTIONS=Object.freeze(['한식','일식','양식','중식','분식','패스트푸드','베트남음식','구내식당']);
  const COLORS=['#f3d0b6','#c9e4d9','#d9d6ec','#f1dfb8','#ebcbd5','#d0e0ed','#d7e4be','#eee5c4'];
  const SVG_NS='http://www.w3.org/2000/svg',FULL_TURN=360,SLICE=FULL_TURN/OPTIONS.length;
  const normalize=angle=>((angle%FULL_TURN)+FULL_TURN)%FULL_TURN;
  function randomUnit(){
    if(window.crypto?.getRandomValues)return window.crypto.getRandomValues(new Uint32Array(1))[0]/4294967296;
    return Math.random();
  }
  function svgElement(name,attributes){
    const element=document.createElementNS(SVG_NS,name);
    for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));
    return element;
  }
  window.CampusLunchWheel={
    options:OPTIONS,
    create({root=document.getElementById('lunchWheel'),random=randomUnit}={}){
      if(!root)return {cancel(){}};
      const wheel=root.querySelector('[data-lunch-wheel]'),button=root.querySelector('[data-lunch-spin]');
      const choice=root.querySelector('[data-lunch-choice]'),message=root.querySelector('[data-lunch-message]');
      const legend=root.querySelector('[data-lunch-options]'),motion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
      const point=degrees=>({x:160+Math.cos(degrees*Math.PI/180)*154,y:160+Math.sin(degrees*Math.PI/180)*154});
      wheel.replaceChildren();legend.replaceChildren();
      for(const [index,label] of OPTIONS.entries()){
        const center=-90+index*SLICE,start=point(center-SLICE/2),end=point(center+SLICE/2);
        wheel.append(svgElement('path',{d:`M160 160 L${start.x} ${start.y} A154 154 0 0 1 ${end.x} ${end.y} Z`,fill:COLORS[index],stroke:'#fffdf5','stroke-width':2}));
        const radians=center*Math.PI/180,x=160+Math.cos(radians)*111,y=160+Math.sin(radians)*111;
        let angle=index*SLICE;if(angle>90&&angle<270)angle+=180;
        const text=svgElement('text',{x,y,transform:`rotate(${angle} ${x} ${y})`,'text-anchor':'middle','dominant-baseline':'middle','font-size':label.length>4?12:14,'font-weight':700,fill:'#3b514a'});
        text.textContent=label;wheel.append(text);
        const item=document.createElement('li');item.textContent=label;legend.append(item);
      }
      let spinning=false,rotation=0,pending=null,lastChoice=null,timer=null;
      function showResult(){
        choice.textContent=lastChoice||'돌림판을 돌려보세요';
        message.textContent=lastChoice?`오늘은 ${lastChoice} 어때요?`:'8가지 메뉴 중 하나를 골라드릴게요.';
        button.textContent=lastChoice?'다시 돌리기':'돌림판 돌리기';
        root.dataset.result=lastChoice||'';
      }
      function release(){
        window.clearTimeout(timer);timer=null;spinning=false;pending=null;
        root.classList.remove('is-spinning');button.disabled=false;
      }
      function finish(){
        if(!spinning)return;
        rotation=pending.rotation;lastChoice=OPTIONS[pending.index];
        wheel.style.transition='none';wheel.style.transform=`rotate(${rotation}deg)`;
        release();showResult();
      }
      function spin(){
        if(spinning||root.closest('[hidden]')||root.closest('dialog')?.open===false)return false;
        const index=Math.floor(random()*OPTIONS.length),jitter=(random()-.5)*28;
        const turns=5+Math.floor(random()*3),landing=normalize(-index*SLICE+jitter);
        pending={index,rotation:rotation+turns*FULL_TURN+normalize(landing-normalize(rotation))};
        spinning=true;button.disabled=true;button.textContent='돌리는 중…';root.classList.add('is-spinning');
        choice.textContent='오늘의 점심 고르는 중…';message.textContent='돌림판이 멈추면 결과를 알려드릴게요.';
        const duration=motion?.matches?500:4400;
        // Flush the previous angle before assigning the transition, including after reopening.
        wheel.getBoundingClientRect();
        wheel.style.transition=`transform ${duration}ms cubic-bezier(.12,.72,.13,1)`;
        wheel.style.transform=`rotate(${pending.rotation}deg)`;
        timer=window.setTimeout(finish,duration+100);
        return true;
      }
      function cancel(){
        if(!spinning)return;
        wheel.style.transition='none';wheel.style.transform=`rotate(${rotation}deg)`;
        release();showResult();
      }
      button.addEventListener('click',spin);
      wheel.addEventListener('transitionend',event=>{if(event.target===wheel&&event.propertyName==='transform')finish();});
      showResult();
      return {spin,cancel,get spinning(){return spinning;},get choice(){return lastChoice;},get rotation(){return rotation;}};
    },
  };
})();
