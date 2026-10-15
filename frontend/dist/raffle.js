/* One persisted server result; the slot reel only presents that result. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const kst=value=>new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const inputTime=value=>value?new Date(new Date(value).getTime()+9*3600000).toISOString().slice(0,19):'';
  const wireTime=value=>value?new Date(value+'+09:00').toISOString():null;
  window.CampusRaffle={
    create({onOpen=()=>{},onClose=()=>{},onState=()=>{},onStart=()=>false,isNear=()=>false,notify=()=>{}}={}){
      const dialog=$('raffleDialog'),drawDialog=$('raffleDrawDialog');
      const config=JSON.parse($('campusPresenceConfig')?.textContent||'{}');
      const enabled=Boolean($('campusPresenceConfig'));
      let surveyUrl='',surveyEventId=null,surveyWindow=null;
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
      function protectedImage(image,value,path){
        let url;try{url=new URL(value,location.origin);if(!value||url.origin!==location.origin||url.pathname!==path)throw new Error();}catch{image.hidden=true;image.removeAttribute('src');return false;}
        const target=url.pathname+url.search;if(image.dataset.failedSource===target){image.hidden=true;return false;}
        image.hidden=false;if(image.getAttribute('src')!==target)image.src=target;return true;
      }
      function renderContactCard(prefix,allowed){
        const card=$(prefix),image=$(prefix+'Qr'),contact=state?.winnerContact;
        card.hidden=!allowed||!contact;
        if(card.hidden){image.hidden=true;image.removeAttribute('src');delete image.dataset.failedSource;return;}
        $(prefix+'Event').textContent=contact.eventTitle+' · '+contact.nickname+' 님 당첨';
        const ready=contact.status==='ready'&&protectedImage(image,contact.qrUrl,'/api/raffle/winner-contact/qr/'+contact.eventId+'/');
        if(!ready){image.hidden=true;image.removeAttribute('src');}
        $(prefix+'Message').textContent=ready?'QR을 스캔해 카카오톡 1:1 오픈채팅으로 들어가 주세요. 당첨 닉네임과 이벤트 이름을 알려주시면 선물 수령을 안내해 드립니다.':image.dataset.failedSource?'QR을 불러오지 못했어요. 안내 새로고침을 눌러 다시 확인해 주세요.':'관리자가 오픈채팅 QR을 준비 중입니다. 등록되면 이곳에 표시돼요. 나중에 이벤트 창을 다시 열어 확인할 수 있습니다.';
      }
      function renderWinnerContact(){
        renderContactCard('raffleWinnerContact',true);
        renderContactCard('raffleDrawWinnerContact',drawDialog.dataset.finished==='true'&&state?.winnerContact?.eventId===showingEvent?.id);
        const manager=state?.canManage===true,config=state?.winnerContactConfig,preview=$('raffleWinnerContactPreview');
        $('raffleWinnerContactUpload').disabled=busy||!manager;
        $('raffleWinnerContactImage').disabled=busy||!manager;
        $('raffleWinnerContactStatus').textContent=config?.configured?'QR이 등록됐어요. 당첨자에게 수령 안내가 표시됩니다.':'아직 등록된 QR이 없어요. 나중에 이미지를 등록할 수 있습니다.';
        if(manager&&config?.configured)protectedImage(preview,config.previewUrl,'/api/raffle/winner-contact/qr/');else{preview.hidden=true;preview.removeAttribute('src');}
      }
      function render(){
        const event=state?.event,status=event?.status||'draft',joined=Boolean(state?.myEntryId),cutoff=event?.drawAt&&now()>=Date.parse(event.drawAt);
        const currentWinner=status==='drawn'&&state?.winnerContact?.eventId===event?.id;
        $('raffleParticipationTitle').textContent=status==='drawn'?(currentWinner?'당첨을 축하합니다!':'이벤트 결과 안내'):joined?'참가 등록 완료':'부저를 누르고 설문에 참여하세요';
        $('raffleTitle').textContent=event?.title||'옥상 기프티콘 이벤트';
        const badge=$('raffleStatusBadge');badge.textContent=status==='open'&&!cutoff?'참여 가능':status==='drawn'?'추첨 완료':cutoff?'추첨 준비 중':'준비 중';badge.dataset.status=status;
        const near=isNear(),surveyOpened=state?.survey?.status==='pending',configured=state?.survey?.configured===true;
        if(surveyEventId!==event?.id)surveyUrl='';
        $('raffleJoin').disabled=!enabled||!connected||pending||busy||joined||status!=='open'||cutoff||(!near&&!surveyOpened)||!configured;
        const surveyLink=$('raffleSurveyLink');surveyLink.hidden=!surveyUrl||joined||status!=='open'||Boolean(cutoff);
        if(surveyUrl)surveyLink.href=surveyUrl;surveyLink.setAttribute('aria-disabled',String($('raffleJoin').disabled));surveyLink.tabIndex=$('raffleJoin').disabled?-1:0;
        $('raffleSurveyUnavailable').hidden=configured||joined||status==='drawn';
        $('raffleJoin').dataset.joined=String(joined);
        $('raffleJoinLabel').textContent=joined?'참여 완료 ✓':pending?'설문 준비 중…':status==='drawn'||cutoff?'참여 마감':!configured?'설문 연결 준비 중':status==='open'?(near||surveyOpened?(surveyOpened?'설문 조사 다시 열기':'부저 눌러 설문 조사하기'):'부저 가까이로 이동'):'이벤트 준비 중';
        $('raffleParticipationHint').textContent=status==='drawn'?(currentWinner?'아래 수령 안내를 확인해 주세요.':'추첨이 끝났어요. 다음 이벤트에서 만나요.'):joined?'닉네임이 참가 명단에 등록됐어요. 추첨을 기다려 주세요.':surveyOpened?'설문 제출을 확인 중입니다. 제출이 확인되면 자동으로 등록돼요.':status==='open'?'자동 입력된 참가 확인 코드를 유지하고 설문을 끝까지 제출해 주세요.':'참여가 시작되면 옥상 부저를 눌러 주세요.';
        const participants=state?.participants||[];$('raffleParticipantCount').textContent=participants.length+'명';
        const list=$('raffleParticipantList');list.replaceChildren();
        for(const person of participants){const li=document.createElement('li'),check=document.createElement('span'),name=document.createElement('span');check.className='raffle-check';check.textContent='✓';check.setAttribute('aria-hidden','true');name.textContent=person.nickname;li.append(check,name);if(person.id===state.myEntryId){const me=document.createElement('small');me.textContent='나';li.append(me);}list.append(li);}
        $('raffleParticipantEmpty').hidden=participants.length>0;
        $('raffleScheduleLabel').textContent=event?[event.opensAt?'참여 시작: '+kst(event.opensAt):null,event.drawAt?'추첨: '+kst(event.drawAt):'추첨 시간은 아직 정해지지 않았어요.'].filter(Boolean).join('\n'):'';
        if(status==='drawn'&&event?.drawnAt)$('raffleScheduleLabel').textContent='추첨 완료: '+kst(event.drawnAt);
        const winner=$('raffleLastWinner');winner.hidden=status!=='drawn';winner.textContent=event?.winner?'당첨자: '+event.winner.nickname:'참가자가 없어 추첨을 마쳤어요.';
        renderWinnerContact();
        const admin=state?.canManage===true;$('raffleAdmin').hidden=!admin;launcher.hidden=!admin;
        $('raffleSurveySave').disabled=busy;
        $('raffleSurveyConnectionStatus').textContent=configured?(state.survey.error||'설문 제출 자동 확인이 연결됐어요.'):'설문을 연결하면 제출 완료된 계정이 자동으로 참가 명단에 등록됩니다.';
        if(document.activeElement!==$('raffleSurveyEndpoint')&&!$('raffleSurveyEndpoint').value)$('raffleSurveyEndpoint').value=state?.survey?.endpoint||'';
        $('rafflePrepare').disabled=busy||Boolean(event&&status!=='drawn');$('raffleOpen').disabled=busy||Boolean(event&&status!=='draft');$('raffleDraw').disabled=busy||!event||status!=='open';
        $('raffleScheduleSave').disabled=busy||!event||status==='drawn';$('raffleOpensAt').disabled=status==='open'||status==='drawn';
        if(!dialog.contains(document.activeElement)||!$('raffleScheduleDetails').open){$('raffleEventName').value=event?.title||'옥상 기프티콘 이벤트';$('raffleOpensAt').value=inputTime(event?.opensAt);$('raffleDrawAt').value=inputTime(event?.drawAt);}
      }
      function valid(value){return value&&Number.isSafeInteger(value.revision)&&typeof value.serverNow==='string'&&Number.isFinite(Date.parse(value.serverNow))&&Array.isArray(value.participants)&&value.participants.every(p=>typeof p.id==='string'&&typeof p.nickname==='string')&&(!value.event||(typeof value.event.id==='string'&&['draft','open','drawn'].includes(value.event.status)));}
      function receive(value){
        if(!valid(value)||value.revision<(state?.revision??-1))return;
        const previousEvent=state?.event?.id,wasWaiting=state?.survey?.status==='pending'&&!state?.myEntryId;state=value;clockOffset=Date.parse(value.serverNow)-Date.now();
        if(state.myEntryId){pending=false;clearTimeout(pendingTimer);}
        if(previousEvent&&previousEvent!==state.event?.id)report('');
        render();onState(state);maybeDraw();
        if(wasWaiting&&previousEvent===state.event?.id&&state.myEntryId){report('설문 제출 확인 완료! 참가 명단에 등록됐어요.');notify('이벤트 참여가 완료됐어요!');}
      }
      function finish(){
        cancelAnimationFrame(frame);drawDialog.dataset.finished='true';$('raffleReel').style.transform='';
        const event=showingEvent,participants=showingParticipants,winner=event?.winner;
        $('raffleReelPrevious').textContent=participants[0]?.nickname||'PLAYDATA';$('raffleReelCurrent').textContent=winner?.nickname||'다음에 만나요';$('raffleReelNext').textContent=participants.at(-1)?.nickname||'ROOFTOP EVENT';
        $('raffleDrawTitle').textContent=winner?'축하합니다!':'이번 추첨을 마쳤어요';$('raffleDrawStatus').textContent=winner?'참가 계정 중 한 명을 무작위로 선정했어요.':'이번 이벤트에는 참가자가 없었어요.';
        $('raffleWinnerAnnouncement').textContent=winner?winner.nickname+' 님이 당첨됐어요!':'';$('raffleShowResult').hidden=true;$('raffleReturn').hidden=false;renderWinnerContact();
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
      function closeWaitingWindow(){try{surveyWindow?.close();}catch{}surveyWindow=null;}
      function startSurvey(){
        if($('raffleJoin').disabled)return;
        surveyWindow=window.open('about:blank','_blank');if(surveyWindow)surveyWindow.opener=null;
        pending=true;render();report('설문을 준비하고 있어요.');
        if(!onStart(state.event.id,state.survey?.status==='pending')){closeWaitingWindow();onError('서버 연결을 확인해 주세요.');return;}
        pendingTimer=setTimeout(()=>{closeWaitingWindow();onError('설문을 준비하지 못했어요. 다시 눌러 주세요.');},10000);
      }
      function onSurvey(message){
        let url;try{url=new URL(message.url);if(url.protocol!=='https:'||url.hostname!=='docs.google.com'||url.username||url.password||!url.pathname.startsWith('/forms/')||!url.pathname.endsWith('/viewform'))throw new Error();}catch{closeWaitingWindow();onError('설문 주소를 확인해 주세요.');return;}
        receive(message.state);pending=false;clearTimeout(pendingTimer);
        if(message.eventId!==state?.event?.id||state.event.status!=='open'||(state.event.drawAt&&now()>=Date.parse(state.event.drawAt))){closeWaitingWindow();render();return;}
        surveyEventId=message.eventId;surveyUrl=url.href;
        const blocked=!surveyWindow||surveyWindow.closed;
        if(!blocked)surveyWindow.location.replace(surveyUrl);
        surveyWindow=null;render();report(blocked?'팝업이 차단됐어요. 아래 설문 조사 열기 링크를 눌러 주세요.':'설문을 제출해 주세요. 제출이 확인되면 자동으로 참가 등록됩니다.');
      }
      async function connectSurvey(){
        if(busy||!state?.canManage)return;busy=true;render();report('Google 설문 연결을 확인하고 있어요.');
        try{
          const token=JSON.parse($('campusSessionPolicyConfig')?.textContent||'{}').csrfToken||decodeURIComponent(document.cookie.split('; ').find(s=>s.startsWith('campus_csrftoken='))?.split('=')[1]||'');
          const response=await fetch('/api/raffle/survey/connect/',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({endpoint:$('raffleSurveyEndpoint').value.trim(),accessKey:$('raffleSurveyKey').value.trim()})});
          const result=await response.json();if(!response.ok)throw new Error(result.error||'설문 연결에 실패했어요.');$('raffleSurveyKey').value='';receive(result);report('설문을 연결했어요. 이제 제출이 확인되면 참가 명단에 자동 등록됩니다.');
        }catch(error){report(error.message||'설문 연결을 확인해 주세요.',true);}
        finally{busy=false;render();}
      }
      async function uploadWinnerContact(){
        if(busy||!state?.canManage)return;
        const image=$('raffleWinnerContactImage').files[0];
        if(!image){report('오픈채팅 QR 이미지를 선택해 주세요.',true);return;}
        if(image.size>2*1024*1024){report('QR 이미지는 2MB 이하로 등록해 주세요.',true);return;}
        busy=true;render();report('당첨자 수령 안내를 저장하고 있어요.');
        try{
          const token=JSON.parse($('campusSessionPolicyConfig')?.textContent||'{}').csrfToken||decodeURIComponent(document.cookie.split('; ').find(s=>s.startsWith('campus_csrftoken='))?.split('=')[1]||'');
          const body=new FormData();body.append('qrImage',image);
          const response=await fetch('/api/raffle/winner-contact/',{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':token},body});
          let result;try{result=await response.json();}catch{throw new Error('QR 이미지 등록을 확인해 주세요. 파일은 2MB 이하로 선택해 주세요.');}
          if(!response.ok)throw new Error(result.error||'QR 이미지를 등록하지 못했어요.');
          receive(result);$('raffleWinnerContactForm').reset();report('QR 이미지를 등록했어요. 당첨자에게 수령 안내가 표시됩니다.');
        }catch(error){report(error.message||'QR 이미지 등록을 확인해 주세요.',true);}
        finally{busy=false;render();}
      }
      $('raffleWinnerContactForm').onsubmit=event=>{event.preventDefault();uploadWinnerContact();};
      for(const prefix of ['raffleWinnerContact','raffleDrawWinnerContact']){
        $(prefix+'Refresh').onclick=()=>{delete $(prefix+'Qr').dataset.failedSource;$(prefix+'Qr').removeAttribute('src');refresh();};
        $(prefix+'Qr').onerror=()=>{$(prefix+'Qr').dataset.failedSource=$(prefix+'Qr').getAttribute('src')||'';$(prefix+'Qr').hidden=true;$(prefix+'Message').textContent='QR을 불러오지 못했어요. 안내 새로고침을 눌러 다시 확인해 주세요.';};
      }
      $('raffleJoin').onclick=startSurvey;
      $('raffleSurveyLink').onclick=e=>{if($('raffleJoin').disabled)e.preventDefault();};
      $('raffleSurveyConnectionForm').onsubmit=e=>{e.preventDefault();connectSurvey();};
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
      return {open,receive,onEntry,onSurvey,onError(message){closeWaitingWindow();onError(message);},refresh,setConnected(value){connected=value;render();},get state(){return state;},get blocking(){return dialog.open||drawDialog.open;}};
    },
  };
})();
