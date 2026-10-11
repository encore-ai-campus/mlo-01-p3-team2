/* One persisted server result; the slot reel only presents that result. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const kst=value=>new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const inputTime=value=>value?new Date(new Date(value).getTime()+9*3600000).toISOString().slice(0,19):'';
  const wireTime=value=>value?new Date(value+'+09:00').toISOString():null;
  window.CampusRaffle={
    create({onOpen=()=>{},onClose=()=>{},onState=()=>{},onJoin=()=>false,isNear=()=>false,notify=()=>{}}={}){
      const dialog=$('raffleDialog'),drawDialog=$('raffleDrawDialog');
      const config=JSON.parse($('campusPresenceConfig')?.textContent||'{}');
      const enabled=Boolean($('campusPresenceConfig'));
      let state=null,connected=false,pending=false,busy=false,clockOffset=0,frame=0,pendingTimer=null;
      let animationToken=null,showingEvent=null,showingParticipants=[],skipAnimation=false,requestNumber=0;
      const seen=new Set();
      const storageKey='campus-raffle-seen:'+config.preferencesKey;
      try{for(const token of JSON.parse(sessionStorage.getItem(storageKey)||'[]'))seen.add(token);}catch{}
      const launcher=document.createElement('button');launcher.id='raffleAdminLauncher';launcher.type='button';launcher.className='toolbtn';launcher.textContent='이벤트 관리';launcher.hidden=true;
      document.querySelector('.top-actions')?.append(launcher);
      launcher.onclick=()=>open();
      const now=()=>Date.now()+clockOffset;
      function report(message,error=false){$('raffleStatus').textContent=message;$('raffleStatus').dataset.error=String(error);}
      function markSeen(){if(!animationToken)return;seen.add(animationToken);try{sessionStorage.setItem(storageKey,JSON.stringify([...seen].slice(-30)));}catch{}}
      function render(){
        const event=state?.event,status=event?.status||'draft',joined=Boolean(state?.myEntryId),cutoff=event?.drawAt&&now()>=Date.parse(event.drawAt);
        $('raffleTitle').textContent=event?.title||'옥상 기프티콘 이벤트';
        const badge=$('raffleStatusBadge');badge.textContent=status==='open'&&!cutoff?'참여 가능':status==='drawn'?'추첨 완료':cutoff?'추첨 준비 중':'준비 중';badge.dataset.status=status;
        const near=isNear();$('raffleJoin').disabled=!enabled||!connected||pending||busy||joined||status!=='open'||cutoff||!near;
        $('raffleJoin').dataset.joined=String(joined);
        $('raffleJoinLabel').textContent=joined?'참여 완료 ✓':pending?'참여 저장 중…':status==='drawn'?'참여 마감':status==='open'&&!cutoff?(near?'부저 눌러 참여하기':'부저 가까이로 이동'):'이벤트 준비 중';
        $('raffleParticipationHint').textContent=joined?'닉네임이 참가 명단에 등록됐어요. 추첨을 기다려 주세요.':status==='drawn'?'추첨이 끝났어요. 다음 이벤트에서 만나요.':status==='open'?'옥상 부저 가까이에서 눌러 주세요. 계정당 한 번 참여해요.':'참여가 시작되면 옥상 부저를 눌러 주세요.';
        const participants=state?.participants||[];$('raffleParticipantCount').textContent=participants.length+'명';
        const list=$('raffleParticipantList');list.replaceChildren();
        for(const person of participants){const li=document.createElement('li'),check=document.createElement('span'),name=document.createElement('span');check.className='raffle-check';check.textContent='✓';check.setAttribute('aria-hidden','true');name.textContent=person.nickname;li.append(check,name);if(person.id===state.myEntryId){const me=document.createElement('small');me.textContent='나';li.append(me);}list.append(li);}
        $('raffleParticipantEmpty').hidden=participants.length>0;
        $('raffleScheduleLabel').textContent=event?[event.opensAt?'참여 시작: '+kst(event.opensAt):null,event.drawAt?'추첨: '+kst(event.drawAt):'추첨 시간은 아직 정해지지 않았어요.'].filter(Boolean).join('\n'):'';
        const winner=$('raffleLastWinner');winner.hidden=status!=='drawn';winner.textContent=event?.winner?'당첨자: '+event.winner.nickname:'참가자가 없어 추첨을 마쳤어요.';
        const admin=state?.canManage===true;$('raffleAdmin').hidden=!admin;launcher.hidden=!admin;
        $('rafflePrepare').disabled=busy||Boolean(event&&status!=='drawn');$('raffleOpen').disabled=busy||Boolean(event&&status!=='draft');$('raffleDraw').disabled=busy||!event||status!=='open';
        $('raffleScheduleSave').disabled=busy||!event||status==='drawn';$('raffleOpensAt').disabled=status==='open'||status==='drawn';
        if(!dialog.contains(document.activeElement)||!$('raffleScheduleDetails').open){$('raffleEventName').value=event?.title||'옥상 기프티콘 이벤트';$('raffleOpensAt').value=inputTime(event?.opensAt);$('raffleDrawAt').value=inputTime(event?.drawAt);}
      }
      function valid(value){return value&&Number.isSafeInteger(value.revision)&&typeof value.serverNow==='string'&&Number.isFinite(Date.parse(value.serverNow))&&Array.isArray(value.participants)&&value.participants.every(p=>typeof p.id==='string'&&typeof p.nickname==='string')&&(!value.event||(typeof value.event.id==='string'&&['draft','open','drawn'].includes(value.event.status)));}
      function receive(value){
        if(!valid(value)||value.revision<(state?.revision??-1))return;
        const previousEvent=state?.event?.id;state=value;clockOffset=Date.parse(value.serverNow)-Date.now();
        if(state.myEntryId){pending=false;clearTimeout(pendingTimer);}
        if(previousEvent&&previousEvent!==state.event?.id)report('');
        render();onState(state);maybeDraw();
      }
      function finish(){
        cancelAnimationFrame(frame);drawDialog.dataset.finished='true';$('raffleReel').style.transform='';
        const event=showingEvent,participants=showingParticipants,winner=event?.winner;
        $('raffleReelPrevious').textContent=participants[0]?.nickname||'PLAYDATA';$('raffleReelCurrent').textContent=winner?.nickname||'다음에 만나요';$('raffleReelNext').textContent=participants.at(-1)?.nickname||'ROOFTOP EVENT';
        $('raffleDrawTitle').textContent=winner?'축하합니다!':'이번 추첨을 마쳤어요';$('raffleDrawStatus').textContent=winner?'참가 계정 중 한 명을 무작위로 선정했어요.':'이번 이벤트에는 참가자가 없었어요.';
        $('raffleWinnerAnnouncement').textContent=winner?winner.nickname+' 님이 당첨됐어요!':'';$('raffleShowResult').hidden=true;$('raffleReturn').hidden=false;
      }
      function animate(){
        if(!drawDialog.open)return;
        const event=showingEvent,elapsed=Math.max(0,(now()-Date.parse(event.drawnAt))/1000),duration=event.animationSeconds;
        if(skipAnimation||!event.winner||elapsed>=duration||window.matchMedia('(prefers-reduced-motion: reduce)').matches){finish();return;}
        const participants=showingParticipants,progress=Math.min(1,elapsed/duration),step=Math.floor((1-(1-progress)**3)*duration*23);
        // Event ID seeds a shared visual sequence; the selected winner comes only from the server.
        const seed=[...event.id].reduce((sum,c)=>sum+c.charCodeAt(0),0),index=(step+seed)%participants.length;
        $('raffleReelPrevious').textContent=participants[(index+participants.length-1)%participants.length].nickname;$('raffleReelCurrent').textContent=participants[index].nickname;$('raffleReelNext').textContent=participants[(index+1)%participants.length].nickname;
        $('raffleReel').style.transform=`translateY(${Math.sin(elapsed*32)*(1-progress)*9}px)`;
        $('raffleDrawStatus').textContent=`참가 ${participants.length}명 · ${Math.max(1,Math.ceil(duration-elapsed))}초 후 당첨자 공개`;
        frame=requestAnimationFrame(animate);
      }
      function maybeDraw(){
        if(window.CampusApp?.floorTransition.blocking||window.CampusSession?.ending)return;
        const event=state?.event;if(event?.status!=='drawn'||!event.drawnAt)return;
        const token=event.id+':'+event.drawnAt;
        if(drawDialog.open&&animationToken===token)return;
        if(seen.has(token)||now()>Date.parse(event.drawnAt)+(event.animationSeconds+state.popupGraceSeconds)*1000)return;
        animationToken=token;showingEvent={...event};showingParticipants=state.participants.map(person=>({...person}));skipAnimation=false;cancelAnimationFrame(frame);
        onOpen();if(dialog.open)dialog.close();drawDialog.dataset.finished='false';$('raffleDrawEventName').textContent=event.title;$('raffleDrawTitle').textContent='오늘의 행운은 누구에게?';$('raffleWinnerAnnouncement').textContent='';$('raffleShowResult').hidden=false;$('raffleReturn').hidden=true;
        if(!drawDialog.open)drawDialog.showModal();animate();
      }
      async function refresh(){
        if(!enabled)return;
        try{const response=await fetch('/api/raffle/',{credentials:'same-origin',cache:'no-store'});if(response.ok)receive(await response.json());else if(dialog.open)report('이벤트 정보를 다시 불러오지 못했어요.',true);}catch{if(dialog.open)report('서버 연결을 확인해 주세요.',true);}
      }
      async function operate(action,extra={}){
        if(busy||!state?.canManage)return;busy=true;const request=++requestNumber;render();report('이벤트 설정을 저장하고 있어요.');
        try{
          const token=$('campusSessionPolicyConfig')?JSON.parse($('campusSessionPolicyConfig').textContent).csrfToken:decodeURIComponent(document.cookie.split('; ').find(s=>s.startsWith('campus_csrftoken='))?.split('=')[1]||'');
          const response=await fetch('/api/raffle/control/',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({action,eventId:state.event?.id||null,...extra})});
          const result=await response.json();if(!response.ok)throw new Error(result.error||'설정을 저장하지 못했어요.');receive(result);report(action==='open'?'참여를 시작했어요.':action==='draw'?'전체 접속자에게 추첨을 보여주고 있어요.':action==='prepare'?'새 이벤트를 준비했어요.':'시간 설정을 저장했어요.');
        }catch(error){report(error.message||'서버 연결을 확인해 주세요.',true);await refresh();}
        finally{if(request===requestNumber){busy=false;render();}}
      }
      function open(){onOpen();report('');render();if(!dialog.open)dialog.showModal();refresh();}
      function onEntry(message){receive(message.state);pending=false;clearTimeout(pendingTimer);render();report(message.created?'참여 완료! 참가 명단에 등록됐어요.':'이미 참여한 이벤트예요.');notify(message.created?'이벤트 참여가 완료됐어요!':'이미 참여한 이벤트예요.');}
      function onError(message){pending=false;clearTimeout(pendingTimer);render();report(message,true);notify(message);refresh();}
      $('raffleJoin').onclick=()=>{if($('raffleJoin').disabled)return;pending=true;report('참여를 저장하고 있어요.');render();if(!onJoin(state.event.id)){onError('서버 연결을 확인한 뒤 다시 눌러 주세요.');return;}pendingTimer=setTimeout(()=>onError('참여 결과를 확인하고 있어요. 잠시 후 다시 눌러 주세요.'),10000);};
      $('raffleClose').onclick=()=>dialog.close();dialog.addEventListener('close',onClose);
      for(const id of ['raffleDrawClose','raffleReturn'])$(id).onclick=()=>drawDialog.close();
      drawDialog.addEventListener('close',()=>{markSeen();cancelAnimationFrame(frame);onClose();});
      $('raffleShowResult').onclick=()=>{skipAnimation=true;finish();};
      $('rafflePrepare').onclick=()=>operate('prepare');$('raffleOpen').onclick=()=>operate('open');
      $('raffleDraw').onclick=()=>{if(window.confirm('참여를 마감하고 전체 접속자에게 추첨을 보여줄까요?'))operate('draw');};
      $('raffleScheduleForm').onsubmit=e=>{e.preventDefault();try{operate('schedule',{title:$('raffleEventName').value.trim(),opensAt:$('raffleOpensAt').disabled?null:wireTime($('raffleOpensAt').value),drawAt:wireTime($('raffleDrawAt').value)});}catch{report('예약 시간을 확인해 주세요.',true);}};
      window.addEventListener('campus:floor-transition-end',maybeDraw);
      if(enabled){refresh();setInterval(refresh,15000);setInterval(()=>{if(dialog.open)render();},1000);}
      render();
      return {open,receive,onEntry,onError,refresh,setConnected(value){connected=value;render();},get state(){return state;},get blocking(){return dialog.open||drawDialog.open;}};
    },
  };
})();
