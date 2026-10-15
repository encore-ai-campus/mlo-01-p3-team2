/* Collapsible space list, separate from the first-visit instruction guide. */
(()=>{
 'use strict';
 window.CampusSpaceGuide={create({onSelect=()=>{},onOpen=()=>{},isBlocked=()=>false,focusMap=()=>{}}={}){
  const toggle=document.getElementById('campusNavToggle'),panel=document.getElementById('campusSpaceGuide'),nav=document.getElementById('roomNav'),title=document.getElementById('spaceGuideTitle');
  let floor=null;
  function close({focus=false}={}){panel.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.title='캠퍼스 공간 안내 펼치기';if(focus)toggle.focus({preventScroll:true});}
  function setRoom(id){for(const button of nav.querySelectorAll('[data-room]')){const active=button.dataset.room===id;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','location');else button.removeAttribute('aria-current');}}
  function setWorld(data,roomId){
   if(floor!==data.id){
    floor=data.id;title.textContent=floor==='rooftop'?'옥상 광장 둘러보기':'공간 둘러보기';nav.replaceChildren();
    const groups=floor==='rooftop'?[['전시 부스',['festival-youtube','festival-instagram','festival-booth3']],['쉼터 · 연결 공간',['roof-upper','roof-terrace','roof-plaza','roof-stairs']]]:[['라운지',['lounge1','lounge2']],['강의 공간',['class1','class2','class3-4','left-bottom','left-middle','left-top']],['회의 · 상담',['meeting','meeting-l2-a','meeting-l2-b','consult-a','consult-b']],['기타 공간',['office','storage','stairs']]];
    for(const [label,ids] of groups){
     const rooms=ids.map(id=>data.rooms.find(r=>r.id===id&&r.info!==false)).filter(Boolean);if(!rooms.length)continue;
     const group=document.createElement('div');group.className='nav-group-label';group.textContent=label;nav.append(group);
     for(const room of rooms){
      const button=document.createElement('button');button.type='button';button.className='room-nav-button';button.dataset.room=room.id;
      const icon=document.createElement('span');icon.className='nav-icon';icon.setAttribute('aria-hidden','true');icon.textContent=room.id.startsWith('lounge')?'L'+room.id.slice(-1):'▤';
      const name=document.createElement('span');name.textContent=room.name;button.append(icon,name);
      button.addEventListener('click',()=>{if(isBlocked())return;close();onSelect(room);});nav.append(button);
     }
    }
    nav.scrollTop=0;
   }
   setRoom(roomId);
  }
  toggle.addEventListener('click',()=>{if(isBlocked())return;if(!panel.hidden)close();else{onOpen();panel.hidden=false;toggle.setAttribute('aria-expanded','true');toggle.title='캠퍼스 공간 안내 접기';}});
  document.getElementById('spaceGuideClose').addEventListener('click',()=>close({focus:true}));
  document.addEventListener('pointerdown',event=>{if(!panel.hidden&&!panel.contains(event.target)&&!toggle.contains(event.target))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden&&!isBlocked()){event.preventDefault();event.stopImmediatePropagation();close();focusMap();}},true);
  window.addEventListener('campus:guide-open',()=>close());
  return {setWorld,setRoom,close,get open(){return !panel.hidden;}};
 }};
})();
