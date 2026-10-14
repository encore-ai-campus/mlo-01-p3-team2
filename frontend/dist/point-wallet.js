/* Read the server wallet on entry, learning updates, and return to this tab. */
(() => {
  'use strict';
  const wallet=document.getElementById('mapWallet');
  if(!wallet)return;
  const value=document.getElementById('mapWalletBalance'),gain=document.getElementById('mapWalletGain');
  const anchor=wallet.closest('.map-wallet-anchor'),history=document.getElementById('mapWalletHistory');
  const list=document.getElementById('mapWalletHistoryList'),status=document.getElementById('mapWalletHistoryStatus');
  const more=document.getElementById('mapWalletHistoryMore'),retry=document.getElementById('mapWalletHistoryRetry');
  let balance=null,pending=null,refreshAgain=false,gainTimer=null,lastAttempt=-Infinity;
  let historyController=null,historyVersion=0,nextCursor=null,retryAppend=false,lastHistoryAttempt=-Infinity;
  const subjects={python:'Python',sql:'SQL'},levels={beginner:'초급',intermediate:'중급',advanced:'고급'};
  const types={multiple_choice:'객관식',fill_blank:'코드 빈칸'};
  const dateFormat=new Intl.DateTimeFormat('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'});

  function display(next) {
    if(!Number.isSafeInteger(next)||next<0)throw new Error('Invalid wallet balance');
    const previous=balance;
    balance=next;
    const formatted=next.toLocaleString('ko-KR');
    value.textContent=formatted;
    wallet.style.setProperty('--wallet-font-size',`${formatted.length>16?10:formatted.length>11?12:formatted.length>7?16:20}px`);
    wallet.dataset.state='ready';
    wallet.setAttribute('aria-label',`보유 포인트 ${formatted}P, 적립 내역`);
    wallet.title=`보유 포인트 ${formatted}P · 클릭해서 적립 내역 보기`;
    if(previous!==null&&next>previous){
      clearTimeout(gainTimer);
      gain.textContent=`+${(next-previous).toLocaleString('ko-KR')}P`;
      gain.hidden=false;
      wallet.classList.remove('is-earned');
      void wallet.offsetWidth;
      wallet.classList.add('is-earned');
      gainTimer=setTimeout(()=>{gain.hidden=true;wallet.classList.remove('is-earned');},1800);
    }
  }

  function refresh(passive=false) {
    if(document.hidden||window.CampusSession?.ending)return;
    if(passive&&Date.now()-lastAttempt<15000)return;
    if(pending){if(!passive)refreshAgain=true;return pending;}
    lastAttempt=Date.now();
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    pending=(async()=>{
      try{
        const response=await fetch('/api/learning/wallet/',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
        if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('Wallet unavailable');
        display((await response.json()).balance);
      }catch{
        wallet.dataset.state=balance===null?'unavailable':'stale';
        wallet.title=balance===null?'포인트를 불러오지 못했어요.':'마지막으로 확인한 포인트입니다. 다시 연결하면 갱신됩니다.';
        if(balance===null)wallet.setAttribute('aria-label','보유 포인트를 불러오지 못했어요. 적립 내역');
      }finally{
        clearTimeout(timer);
        pending=null;
        if(refreshAgain){refreshAgain=false;refresh();}
      }
    })();
    return pending;
  }

  function fitHistory() {
    const viewport=document.getElementById('viewport').getBoundingClientRect(),button=wallet.getBoundingClientRect();
    history.style.setProperty('--wallet-history-width',`${Math.max(160,viewport.width-24)}px`);
    history.style.setProperty('--wallet-history-max-height',`${Math.min(340,Math.max(96,viewport.bottom-button.bottom-18))}px`);
  }

  function historyRow(item) {
    if(!Number.isSafeInteger(item.amount)||item.amount<=0||!Number.isSafeInteger(item.balance_after)||item.balance_after<0||
       !Number.isInteger(item.question_order)||item.question_order<1||!subjects[item.subject]||!levels[item.difficulty]||!types[item.question_type]||
       typeof item.granted_at!=='string'||!Number.isFinite(Date.parse(item.granted_at)))throw new Error('Invalid point history');
    const row=document.createElement('li'),copy=document.createElement('div'),title=document.createElement('strong');
    const detail=document.createElement('span'),after=document.createElement('small'),amount=document.createElement('strong');
    copy.className='map-wallet-history-copy';amount.className='map-wallet-history-amount';
    title.textContent=`${subjects[item.subject]} ${levels[item.difficulty]} · ${types[item.question_type]}`;
    detail.textContent=`${item.question_order}번 정답 · ${dateFormat.format(new Date(item.granted_at))}`;
    after.textContent=`적립 후 ${item.balance_after.toLocaleString('ko-KR')}P`;
    amount.textContent=`+${item.amount.toLocaleString('ko-KR')}P`;
    copy.append(title,detail,after);row.append(copy,amount);return row;
  }

  async function loadHistory(append=false) {
    if(history.hidden||document.hidden||window.CampusSession?.ending)return;
    if(append&&(!nextCursor||historyController))return;
    historyController?.abort();
    const controller=new AbortController(),version=++historyVersion;
    historyController=controller;lastHistoryAttempt=Date.now();
    const timer=setTimeout(()=>controller.abort(),10000);
    retry.hidden=true;more.disabled=true;
    if(!append){list.replaceChildren();list.hidden=true;more.hidden=true;nextCursor=null;}
    status.hidden=false;status.textContent=append?'이전 내역을 불러오는 중…':'내역을 불러오는 중…';
    history.setAttribute('aria-busy','true');
    try{
      const query=append?`?cursor=${encodeURIComponent(nextCursor)}`:'';
      const response=await fetch(`/api/learning/wallet/history/${query}`,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
      if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('History unavailable');
      const data=await response.json();
      if(version!==historyVersion||history.hidden)return;
      if(!Array.isArray(data.items)||(data.next_cursor!==null&&typeof data.next_cursor!=='string'))throw new Error('Invalid point history');
      const fragment=document.createDocumentFragment();
      for(const item of data.items)fragment.append(historyRow(item));
      list.append(fragment);list.hidden=!list.childElementCount;
      nextCursor=data.next_cursor;more.hidden=!nextCursor;
      if(append&&more.hidden&&document.activeElement===more)list.focus({preventScroll:true});
      status.hidden=!!list.childElementCount;
      status.textContent='아직 적립 내역이 없어요.\n학습 문제를 맞히면 포인트가 쌓여요.';
    }catch{
      if(version!==historyVersion||history.hidden)return;
      retryAppend=append;status.hidden=false;status.textContent='포인트 내역을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';more.hidden=true;retry.hidden=false;
    }finally{
      clearTimeout(timer);
      if(version===historyVersion){historyController=null;more.disabled=false;history.removeAttribute('aria-busy');}
    }
  }

  function closeHistory(restoreFocus=false) {
    history.hidden=true;wallet.setAttribute('aria-expanded','false');
    historyVersion++;historyController?.abort();historyController=null;history.removeAttribute('aria-busy');
    if(restoreFocus)wallet.focus({preventScroll:true});
  }

  function refreshHistory(passive=false) {
    if(!history.hidden&&(!passive||(!historyController&&Date.now()-lastHistoryAttempt>=15000)))loadHistory();
  }

  wallet.addEventListener('click',()=>{
    if(!history.hidden){closeHistory();return;}
    history.hidden=false;wallet.setAttribute('aria-expanded','true');fitHistory();loadHistory();refresh();
  });
  document.getElementById('mapWalletHistoryClose').addEventListener('click',()=>closeHistory(true));
  more.addEventListener('click',()=>loadHistory(true));
  retry.addEventListener('click',()=>loadHistory(retryAppend));
  document.addEventListener('pointerdown',event=>{if(!history.hidden&&!anchor.contains(event.target))closeHistory();});
  anchor.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!history.hidden){event.preventDefault();closeHistory(true);}
    event.stopPropagation();
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!history.hidden){event.preventDefault();event.stopImmediatePropagation();closeHistory(true);}});
  window.addEventListener('resize',()=>{if(!history.hidden)fitHistory();});

  // Answer responses may contain an older saved balance, so read the current wallet.
  window.addEventListener('campus:wallet',()=>{refresh();refreshHistory();});
  window.addEventListener('focus',()=>{refresh(true);refreshHistory(true);});
  window.addEventListener('online',()=>{refresh();refreshHistory();});
  window.addEventListener('pageshow',event=>{if(event.persisted){refresh();refreshHistory();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();refreshHistory(true);}});
  refresh();
})();
