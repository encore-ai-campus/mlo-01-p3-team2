/* A personal lunch picker; the final slice and the displayed result always agree. */
(() => {
  'use strict';
  const OPTIONS=Object.freeze(['한식','일식','양식','중식','분식','패스트푸드','베트남음식','구내식당']);
  const COLORS=['#f3d0b6','#c9e4d9','#d9d6ec','#f1dfb8','#ebcbd5','#d0e0ed','#d7e4be','#eee5c4'];
  const SVG_NS='http://www.w3.org/2000/svg',FULL_TURN=360,SLICE=FULL_TURN/OPTIONS.length;
  const normalize=angle=>((angle%FULL_TURN)+FULL_TURN)%FULL_TURN;
  async function serverPick(){
    const config=document.getElementById('campusSessionPolicyConfig');
    const token=config?JSON.parse(config.textContent).csrfToken:decodeURIComponent(document.cookie.split('; ').find(s=>s.startsWith('campus_csrftoken='))?.split('=')[1]||'');
    const response=await fetch('/api/campus/lunch/spin/',{method:'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json','X-CSRFToken':token},body:'{}'});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'점심 선택을 다시 시도해 주세요.');
    return data;
  }
  function svgElement(name,attributes){
    const element=document.createElementNS(SVG_NS,name);
    for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));
    return element;
  }
  window.CampusLunchWheel={
    options:OPTIONS,
    create({root=document.getElementById('lunchWheel'),pick=serverPick}={}){
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
      let spinning=false,rotation=0,pending=null,lastChoice=null,timer=null,sequence=0;
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
        if(!spinning||!pending)return;
        rotation=pending.rotation;lastChoice=OPTIONS[pending.index];
        wheel.style.transition='none';wheel.style.transform=`rotate(${rotation}deg)`;
        release();showResult();
      }
      async function spin(){
        if(spinning||root.closest('[hidden]')||root.closest('dialog')?.open===false)return false;
        const requestId=++sequence;
        spinning=true;button.disabled=true;button.textContent='돌리는 중…';root.classList.add('is-spinning');
        choice.textContent='오늘의 점심 고르는 중…';message.textContent='돌림판이 멈추면 결과를 알려드릴게요.';
        try{
          const result=await pick();
          if(requestId!==sequence)return false;
          if(!Number.isInteger(result.index)||result.index<0||result.index>=OPTIONS.length||!Number.isFinite(result.jitter)||Math.abs(result.jitter)>14||!Number.isInteger(result.turns)||result.turns<5||result.turns>7)throw new Error('선택 결과를 다시 받아 주세요.');
          const landing=normalize(-result.index*SLICE+result.jitter);
          pending={index:result.index,rotation:rotation+result.turns*FULL_TURN+normalize(landing-normalize(rotation))};
          const duration=motion?.matches?500:4400;
          wheel.getBoundingClientRect();
          wheel.style.transition=`transform ${duration}ms cubic-bezier(.12,.72,.13,1)`;
          wheel.style.transform=`rotate(${pending.rotation}deg)`;
          timer=window.setTimeout(finish,duration+100);
          return true;
        }catch(error){
          if(requestId===sequence){release();showResult();message.textContent=error.message||'서버 연결을 확인해 주세요.';}
          return false;
        }
      }
      function cancel(){
        if(!spinning)return;
        sequence++;
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
