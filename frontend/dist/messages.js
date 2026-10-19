/* Private inbox. Message bodies are rendered as text, never as HTML. */
(() => {
  'use strict';
  function create({config={},onOpen=()=>{},onClose=()=>{},notify=()=>{}}={}) {
    const button=document.getElementById('privateMessagesOpen'),panel=document.getElementById('privateMessagesDialog');
    if(!config.enabled||!button||!panel)return {setRoom(){},open(){},get blocking(){return false;}};
    const $=id=>document.getElementById(id),list=$('dmConversations'),history=$('dmHistory'),form=$('dmCompose'),input=$('dmBody');
    let meta={...config,unread:0},selected=null,currentId=null,busy=false,stopped=false,statusPending=null;
    let version=0,searchVersion=0,searchTimer=null,refreshTimer=null,pendingSend=null;
    const drafts=new Map();
    const csrf=()=>decodeURIComponent(document.cookie.split('; ').find(item=>item.startsWith('campus_csrftoken='))?.split('=').slice(1).join('=')||'');
    function status(text){$('dmStatus').textContent=text;}
    function uid(){
      if(crypto.randomUUID)return crypto.randomUUID();
      const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
      const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
    }
    async function api(path,{method='GET',body}={}) {
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try {
        const response=await fetch('/api/messages/'+path,{method,credentials:'same-origin',cache:'no-store',signal:controller.signal,
          headers:method==='POST'?{'Content-Type':'application/json','X-CSRFToken':csrf()}:undefined,
          body:body===undefined?undefined:JSON.stringify(body)});
        let data;try{data=await response.json();}catch{throw new Error('서버 응답을 확인할 수 없습니다.');}
        if(!response.ok){const error=new Error(data.error||'요청을 처리하지 못했습니다.');error.status=response.status;throw error;}
        return data;
      } catch(error){if(error.name==='AbortError'||error instanceof TypeError)throw new Error('연결을 확인한 뒤 다시 시도해 주세요.');throw error;}
      finally{clearTimeout(timer);}
    }
    function updateButton(){
      button.hidden=!(meta.canStart||meta.hasInbox);$('dmBadge').hidden=!meta.unread;
      $('dmBadge').textContent=meta.unread>99?'99+':String(meta.unread||0);
      button.setAttribute('aria-label',`쪽지함${meta.unread?`, 읽지 않은 쪽지 ${meta.unread}개`:''}`);
      button.title='나와 상대방에게만 보이는 쪽지';
      $('dmNewConversation').hidden=!meta.canStart;
      if(!selected){$('dmRecipientName').textContent=meta.canStart?'누구에게 보낼까요?':'받은 대화를 선택하세요';
        $('dmRecipientHint').textContent=meta.canStart?'닉네임으로 검색해 받는 사람을 선택하세요.':'왼쪽 대화 목록에서 메시지를 확인하고 답장하세요.';}
    }
    function saveDraft(){if(selected)drafts.set(selected.id,input.value);}
    async function refreshStatus(){
      if(stopped||document.hidden)return;if(statusPending)return statusPending;
      statusPending=api('status/').then(data=>{
        if(config.viewerId&&data.viewerId!==config.viewerId){
          stopped=true;drafts.clear();selected=null;currentId=null;history.replaceChildren();input.value='';list.replaceChildren();
          if(panel.open)panel.close();button.hidden=true;notify('로그인 계정이 변경되었습니다. 페이지를 새로고침해 주세요.');return;
        }
        const arrived=data.unread>meta.unread;meta=data;updateButton();
        if(arrived&&!panel.open)notify('새 쪽지가 도착했어요. 쪽지함에서 확인하세요.');
        return data;
      }).catch(error=>{if(error.status===401||error.status===404){stopped=true;button.hidden=true;if(panel.open)panel.close();}else if(panel.open)status(error.message);})
        .finally(()=>{statusPending=null;});return statusPending;
    }
    const personLabel=person=>`${person.nickname}${person.cohort?' · '+person.cohort:''}`;
    function choose(person,id=null){
      saveDraft();version++;selected=person;currentId=id;
      $('dmRecipientName').textContent=personLabel(person);$('dmRecipientHint').textContent='보낸 사람과 받는 사람에게만 표시되는 쪽지입니다.';
      history.replaceChildren();form.hidden=false;input.value=drafts.get(person.id)||'';input.disabled=false;
      $('dmBodyCount').textContent=`${input.value.length}/2000`;$('dmSend').disabled=busy;
      if(id)loadThread().catch(error=>status(error.message));else{status('메시지를 입력해 새 대화를 시작하세요.');input.focus();}
    }
    async function refreshInbox(){
      const data=await api('conversations/');list.replaceChildren();
      for(const item of data.conversations){
        const row=document.createElement('button');row.type='button';row.className='dm-thread';row.setAttribute('aria-current',String(item.id===currentId));
        const title=document.createElement('strong');title.textContent=personLabel(item.other)+(item.unread?` · ${item.unread}개 미확인`:'');
        const preview=document.createElement('span');preview.textContent=item.preview;row.append(title,preview);
        row.addEventListener('click',()=>choose(item.other,item.id));list.append(row);
      }
      $('dmEmptyInbox').hidden=data.conversations.length>0;
    }
    async function loadThread(){
      if(!currentId||!panel.open)return;
      const id=currentId,stamp=version,data=await api(`conversations/${id}/`);
      if(id!==currentId||stamp!==version||!panel.open)return;
      const nearEnd=history.scrollHeight-history.scrollTop-history.clientHeight<70,before=history.lastElementChild?.dataset.messageId;
      const fragment=document.createDocumentFragment();
      for(const item of data.messages){
        const row=document.createElement('li');row.className='dm-message';row.dataset.mine=String(item.sentByMe);row.dataset.messageId=item.id;
        const body=document.createElement('p');body.textContent=item.body;
        const detail=document.createElement('span');detail.textContent=new Date(item.createdAt).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})+(item.sentByMe?(item.readAt?' · 읽음':' · 전송됨'):'');
        row.append(body,detail);fragment.append(row);
      }
      history.replaceChildren(fragment);if(nearEnd||!before)history.scrollTop=history.scrollHeight;
      status(data.messages.length?'최근 메시지 최대 100개를 표시합니다.':'아직 메시지가 없습니다.');
      if(document.hasFocus()&&data.messages.some(item=>!item.sentByMe&&!item.readAt)){
        await api(`conversations/${id}/read/`,{method:'POST',body:{through:data.messages.at(-1).id}});await refreshStatus();
      }
    }
    async function open(){
      if(busy||panel.open)return;
      try{
        await refreshStatus();if(stopped)return;
        if(!meta.canStart&&!meta.hasInbox)return;
        onOpen();panel.showModal();status('대화 목록을 불러오는 중…');
        await refreshInbox();if(currentId)await loadThread();else status(meta.canStart?'대화를 선택하거나 받는 사람을 검색하세요.':'왼쪽에서 받은 대화를 선택하세요.');
      }catch(error){status(error.message);notify(error.message);}
    }
    button.addEventListener('click',open);$('dmClose').addEventListener('click',()=>panel.close());
    panel.addEventListener('close',()=>{saveDraft();version++;onClose();});
    input.addEventListener('input',()=>{$('dmBodyCount').textContent=`${input.value.length}/2000`;saveDraft();});
    $('dmRecipientSearch').addEventListener('input',()=>{
      clearTimeout(searchTimer);const query=$('dmRecipientSearch').value.trim(),stamp=++searchVersion;
      $('dmRecipientResults').replaceChildren();if(!query)return;
      searchTimer=setTimeout(async()=>{
        try{
          const data=await api('recipients/?q='+encodeURIComponent(query));if(stamp!==searchVersion)return;
          const results=$('dmRecipientResults');results.replaceChildren();
          if(!data.recipients.length){const empty=document.createElement('p');empty.textContent='검색된 사람이 없습니다.';results.append(empty);}
          for(const person of data.recipients){const row=document.createElement('button');row.type='button';row.textContent=personLabel(person)+' · '+person.id.slice(0,6);
            row.addEventListener('click',()=>{choose(person);results.replaceChildren();$('dmRecipientSearch').value='';});results.append(row);}
        }catch(error){if(stamp===searchVersion)status(error.message);}
      },250);
    });
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy||!selected||!input.value.trim())return;
      const person=selected,body=input.value.trim();
      if(!pendingSend||pendingSend.recipient!==person.id||pendingSend.body!==body)pendingSend={recipient:person.id,body,requestId:uid()};
      busy=true;input.disabled=true;$('dmSend').disabled=true;status('보내는 중…');let sent=false;
      try{
        await refreshStatus();if(stopped)throw new Error('페이지를 새로고침해 주세요.');
        const data=await api('send/',{method:'POST',body:pendingSend});drafts.delete(person.id);pendingSend=null;
        sent=true;
        if(selected?.id===person.id){currentId=data.conversationId;input.value='';$('dmBodyCount').textContent='0/2000';}
        await refreshInbox();if(panel.open)await loadThread();await refreshStatus();
      }catch(error){status(sent?'메시지는 전송되었습니다. 대화를 다시 열어 확인해 주세요.':error.message+' 입력한 메시지는 그대로 남아 있습니다.');}
      finally{busy=false;input.disabled=false;$('dmSend').disabled=false;}
    });
    window.addEventListener('campus:private-message',()=>{
      clearTimeout(refreshTimer);refreshTimer=setTimeout(async()=>{await refreshStatus();if(panel.open){try{await refreshInbox();await loadThread();}catch(error){status(error.message);}}},150);
    });
    window.addEventListener('focus',()=>{refreshStatus();if(panel.open)loadThread().catch(error=>status(error.message));});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshStatus();});
    // 새 쪽지는 소켓(private_message)이 알려 주므로, 소켓이 붙어 있고 쪽지함이 닫혀 있으면 15초 조회를 하지 않는다(계획 4g)
    const interval=setInterval(async()=>{if(stopped||document.hidden||(!panel.open&&window.CampusApp?.presence?.connected))return;await refreshStatus();if(panel.open){try{await refreshInbox();await loadThread();}catch(error){status(error.message);}}},15000);
    window.addEventListener('pagehide',()=>{clearInterval(interval);clearTimeout(searchTimer);clearTimeout(refreshTimer);});
    updateButton();refreshStatus();
    return {open,get available(){return meta.canStart||meta.hasInbox;},get blocking(){return panel.open;}};
  }
  window.CampusMessages={create};
})();
