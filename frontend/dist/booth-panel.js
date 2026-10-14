/* Central booth interaction, informational PiP and same-window game navigation. */
(() => {
  'use strict';
  window.CampusBoothPanel={create({onOpen,onClose}){
    const dialog=document.getElementById('boothDialog'),panel=document.getElementById('boothPanel');
    const get=id=>panel.querySelector('#'+id),title=get('boothTitle'),intro=get('boothIntro'),status=get('boothStatus'),pipButton=get('boothPiP'),returnButton=get('boothReturn');
    const supported=window.isSecureContext&&typeof window.documentPictureInPicture?.requestWindow==='function';
    const names={youtube:'YouTube 부스',psych:'심리 테스트 존',game:'게임 부스'};
    const games={'gomoku':{name:'오목',url:'/content/gomoku/open/'},'war':{name:'전쟁시대',url:'/content/war/open/'},'dad-and-me':{name:'아빠와 나',url:'/content/dad-and-me/open/'},'minesweeper':{name:'지뢰찾기',url:'/content/minesweeper/open/'},'fruit-box':{name:'사과게임',url:'/content/fruit-box/open/'},'bubble-shooter':{name:'버블슈터',url:'/content/bubble-shooter/open/'},'suika':{name:'수박게임',url:'/content/suika/open/'},'flashman':{name:'후레시맨',url:'/content/flashman/open/'},'tetris':{name:'테트리스',url:'/content/tetris/open/'},'worlds-hardest-game':{name:'세상에서 가장 어려운 게임',url:'/content/worlds-hardest-game/open/'},'bamboo-master':{name:'죽림고수',url:'/content/bamboo-master/open/'},'sword-upgrade':{name:'검 강화하기',url:'/content/sword-upgrade/open/'},'walk-the-stork':{name:'황새와 오래 걷기',url:'/content/walk-the-stork/open/'},'isaac':{name:'아이작',url:'/content/isaac/open/'},'paladog':{name:'팔라독',url:'/content/paladog/open/'},'solitaire':{name:'솔리테어',url:'/content/solitaire/open/'}};
    const psychUrl='/content/psych-test/open/';
    const card=panel.querySelector('.booth-service-card'),choices=get('boothGameChoices'),launcher=get('boothEmbeddedSection'),externalLink=get('boothExternalLink');
    let pipWindow=null,contentWindow=null,pending=false,closed=false,restoreModal=false;
    function updateWindowButtons(){
      returnButton.hidden=!pipWindow;pipButton.hidden=!supported||!!pipWindow;
      if(panel.dataset.platform==='game'||panel.dataset.platform==='psych')pipButton.hidden=true;
    }
    function openContentWindow(url,{refreshExisting=false}={}){
      try{
        if(contentWindow&&!contentWindow.closed){
          if(refreshExisting)contentWindow.location.replace(url);
          contentWindow.focus();return true;
        }
        const width=Math.min(1100,screen.availWidth),height=Math.min(850,screen.availHeight);
        const win=window.open('about:blank','_blank','popup=yes,width='+width+',height='+height);
        if(!win)return false;
        win.opener=null;win.location.replace(url);contentWindow=win;win.focus();return true;
      }catch{return false;}
    }
    function launchContent(url,options){
      if(openContentWindow(url,options)){if(dialog.open)dialog.close();return true;}
      status.hidden=false;status.textContent='브라우저에서 팝업을 허용한 뒤 다시 열어 주세요.';
      showModal();return false;
    }
    function selectGame(id){
      if(panel.dataset.platform!=='game'||!Object.hasOwn(games,id))return;
      launchContent(new URL(games[id].url,document.baseURI).href);
    }
    function showModal(){if(!dialog.open)dialog.showModal();}
    function restorePanel(){
      if(panel.parentElement!==dialog)dialog.append(panel);
      pipWindow=null;updateWindowButtons();
      if(restoreModal&&!closed){restoreModal=false;showModal();}else{restoreModal=false;onClose?.();}
    }
    async function enterPiP(){
      if(pipWindow&&!pipWindow.closed){pipWindow.focus();return;}
      if(!supported){showModal();return;}
      pending=true;
      try{
        const win=await window.documentPictureInPicture.requestWindow({width:680,height:460});
        if(closed){win.close();return;}
        pipWindow=win;win.document.title=title.textContent;win.document.documentElement.lang='ko';
        for(const sheet of document.styleSheets){
          try{const css=win.document.createElement('style');css.textContent=[...sheet.cssRules].map(rule=>rule.cssText).join('\n');win.document.head.append(css);}
          catch{if(sheet.href){const css=win.document.createElement('link');css.rel='stylesheet';css.href=sheet.href;win.document.head.append(css);}}
        }
        win.document.body.className='booth-pip-page';win.document.body.append(panel);updateWindowButtons();
        win.addEventListener('pagehide',()=>{if(pipWindow===win)restorePanel();},{once:true});
        win.document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
        if(dialog.open)dialog.close();
      }catch{
        status.textContent='PiP 창을 열지 못했어요. 이 팝업에서 계속 이용할 수 있습니다.';showModal();
      }finally{pending=false;}
    }
    function open(item){
      closed=false;onOpen?.();const platform=Object.hasOwn(names,item.platform)?item.platform:'basic';
      panel.dataset.platform=platform;title.textContent=names[platform]||'기본 전시 부스';
      choices.hidden=platform!=='game';launcher.hidden=true;
      card.hidden=platform==='game';status.hidden=platform==='game';
      intro.textContent='부스 콘텐츠를 준비하고 있어요.';
      status.textContent='부스 중앙에서 상호작용할 수 있습니다.';
      updateWindowButtons();
      if(platform==='game'){
        intro.textContent='게임 창에서 카드를 선택해 플레이할 수 있어요.';
        if(pipWindow){const win=pipWindow;restorePanel();win.close();}
        // The card list must refresh even if its old popup is still open.
        const gameListUrl=new URL('game-booth.html',document.baseURI);
        gameListUrl.searchParams.set('v',String(Date.now()));
        launchContent(gameListUrl.href,{refreshExisting:true});return;
      }
      if(platform==='psych'){
        intro.textContent='별도 창에서 성격·연애·MBTI 등 다양한 심리 테스트를 골라볼 수 있어요.';
        if(pipWindow){const win=pipWindow;restorePanel();win.close();}
        launcher.hidden=false;externalLink.href=psychUrl;externalLink.textContent='심심테스트 열기';
        launchContent(psychUrl);return;
      }
      if(!supported){showModal();return;}
      if(pipWindow&&!pipWindow.closed){pipWindow.document.title=title.textContent;pipButton.hidden=true;pipWindow.focus();return;}
      void enterPiP();
    }
    function close(){
      closed=true;restoreModal=false;
      launcher.hidden=true;
      if(contentWindow){const win=contentWindow;contentWindow=null;if(!win.closed)win.close();}
      if(pipWindow){const win=pipWindow;restorePanel();win.close();}
      if(dialog.open)dialog.close();onClose?.();
    }
    pipButton.addEventListener('click',()=>{closed=false;void enterPiP();});
    returnButton.addEventListener('click',()=>{if(pipWindow){restoreModal=true;const win=pipWindow;restorePanel();win.close();}});
    choices.addEventListener('click',event=>{const button=event.target.closest('button[data-game]');if(button)selectGame(button.dataset.game);});
    externalLink.addEventListener('click',event=>{event.preventDefault();launchContent(externalLink.href);});
    window.addEventListener('focus',()=>{if(contentWindow?.closed){contentWindow=null;onClose?.();}});
    get('boothClose').addEventListener('click',close);
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}});
    return {open,close,get blocking(){return pending||dialog.open||!!(contentWindow&&!contentWindow.closed);},get pipWindow(){return pipWindow;},supported};
  }};
})();
