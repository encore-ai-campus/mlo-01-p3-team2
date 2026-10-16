(() => {
  'use strict';
  const worlds=window.CampusWorlds, $=id=>document.getElementById(id);
  const DEFAULT_ZOOM=1.45;
  const accountConfig=JSON.parse($('campusPresenceConfig')?.textContent||'{}');
  const avatar=window.CampusAvatars.resolve(accountConfig.avatar);
  // The existing server flag grants the administrator's wider camera controls.
  const isAdmin=JSON.parse($('campusViewConfig')?.textContent||'{}').canZoom===true;
  const MIN_ZOOM=isAdmin ? .35 : .5,MAX_ZOOM=isAdmin ? 3.6 : 1.5;
  function validPosition(position){
    const bounds=position&&typeof position.floor==='string'&&Object.hasOwn(worlds,position.floor)&&worlds[position.floor];
    return bounds&&Number.isFinite(position.x)&&Number.isFinite(position.y)&&position.x>=0&&position.x<=bounds.width
      &&position.y>=0&&position.y<=bounds.height&&['up','down','left','right'].includes(position.dir);
  }
  const spawn=worlds.campus.spawn;
  const initialPosition=validPosition(accountConfig.position)?accountConfig.position:{floor:'campus',x:spawn[0],y:spawn[1],dir:'up'};
  let D=worlds[initialPosition.floor];
  window.CampusData=D;
  const canvas=$('mapCanvas'), ctx=canvas.getContext('2d');
  const viewport=$('viewport'), dialog=$('detailDialog'), boardDialog=$('boardDialog'), exitDialog=$('exitDialog'), transferDialog=$('transferDialog'), logoutForm=$('campusLogoutForm');
  const boardCards=[...boardDialog.querySelectorAll('[data-board-choice]')];
  const communityUI=window.CampusCommunity.create({onBack:()=>showBoardChoices()});
  const lunchWheel=window.CampusLunchWheel?.create();
  let menuRequest=null,menuVersion=0;
  const isDialogOpen=(includeClassroom=true)=>(includeClassroom&&classroom.blocking)||window.CampusLearning?.blocking||window.CampusGuide?.blocking||window.CampusSession?.ending||floorTransition.blocking||dialog.open||boardDialog.open||exitDialog.open||transferDialog.open||$('settingsDialog').open||social.isTyping||boothUI.blocking||raffleUI.blocking;
  const renderers=new Map();
  const displayRefresh=new Map();
  let renderer=window.CampusIsometric.create({data:D}), P=renderer.projection, scene=renderer.scene;
  renderers.set(D.id,renderer);
  const camera={x:0,y:0,zoom:DEFAULT_ZOOM,follow:true}, player={...initialPosition,avatar,color:window.CampusAvatars.definitions[avatar].color,moving:false,step:0,walkTime:0};
  let logoutPending=false,serverHints={};
  let vw=0,vh=0,dpr=1,nearby=null,hover=null,lastRoom='',lastTime=0,toastTimer;
  const keys=new Set();
  const movementKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright']);
  const suppressedKeys=new Set();
  const floorTransition=window.CampusFloorTransition.create({
    onStart(){
      spaceGuide.close();
      for(const key of keys)suppressedKeys.add(key);
      keys.clear();player.moving=false;player.walkTime=0;press=null;hover=nearby=null;
      $('interactionPrompt').hidden=true;viewport.setAttribute('aria-busy','true');
    },
    onFinish(){
      keys.clear();player.moving=false;
      viewport.removeAttribute('aria-busy');
      if(!window.CampusSession?.ending)canvas.focus({preventScroll:true});
    },
  });
  const social=window.CampusSocial.create({config:accountConfig,onFocus(){keys.clear();player.moving=false;},onSend:text=>presence.sendChat(text),getSelfId:()=>presence.selfId});
  let pendingTransfer=null;
  const boothUI=window.CampusBoothPanel.create({onOpen(){keys.clear();player.moving=false;},onClose(){keys.clear();canvas.focus({preventScroll:true});}});
  const raffleUI=window.CampusRaffle.create({onStart:(id,resume)=>presence.joinRaffle(id,{resume}),onOpen(){keys.clear();player.moving=false;},onClose(){keys.clear();canvas.focus({preventScroll:true});},onState:state=>{for(const view of renderers.values())view.setRaffleState(state);},isNear:()=>serverHints.nearbyId==='roof-event-buzzer',notify:toast});
  const classroom=window.CampusClassroom?.create({getPlayer:()=>player,getControl:()=>presence,onPoke:()=>poke.setHeld(true),
    onOpen(){keys.clear();player.moving=false;},
    onExit(){keys.clear();focusPlayer();canvas.focus({preventScroll:true});}
  })||{blocking:false,applyState(){},tick(){}};
  const presence=window.CampusPresence.create({player,width:D.width,height:D.height,floors:worlds,onRestore:position=>restorePosition(position),onState:state=>applyControlState(state),onControlEvent:event=>applyControlEvent(event),onPoke:event=>poke.receive(event),onAuthExpired(){keys.clear();player.moving=false;},onChat:message=>social.receive(message),onChatError:message=>social.reportError(message),onConnectionChange:value=>{social.setConnected(value);raffleUI.setConnected(value);},onDoors:states=>{for(const [id,open] of Object.entries(states))applyDoorState(id,open);},onDoor:state=>applyDoorState(state.doorId,state.open),onDoorError:message=>toast(message),onRaffle:state=>raffleUI.receive(state),onRaffleEntry:message=>raffleUI.onEntry(message),onRaffleSurvey:message=>raffleUI.onSurvey(message),onRaffleError:message=>raffleUI.onError(message)});
  const poke=window.CampusPoke.create({getPlayer:()=>player,getPresence:()=>presence,getClassroom:()=>classroom,getInput:()=>classroom.blocking?classroom.inputKeys:[...keys],isBlocked:()=>isDialogOpen(false),notify:toast});
  const spaceGuide=window.CampusSpaceGuide.create({onSelect:room=>showDetail(room),isBlocked:()=>isDialogOpen(),
    onOpen(){keys.clear();player.moving=false;presence.setInput([]);poke.setHeld(false);},focusMap:()=>canvas.focus({preventScroll:true})});
  spaceGuide.setWorld(D,serverHints.roomId);
  restorePosition(initialPosition,false);
  function applyControlState(state){
    if(state.main.floor!==D.id)restorePosition(state.main);
    serverHints=state.hints||{};classroom.applyState(state.interior);
  }
  function applyControlEvent(event){
    if(event.type==='transfer_offer'){
      if(event.confirm){
        pendingTransfer=event;keys.clear();
        $('transferDescription').textContent=worlds[event.floor].name+'으로 이동합니다. 예를 누르면 이동하고, 아니오를 누르면 현재 위치에 머뭅니다.';
        if(!transferDialog.open)transferDialog.showModal();$('transferYes').focus({preventScroll:true});
      }else switchFloor(event.floor,event.objectId);
    }
  }
  function screenToWorld(x,y){return renderer.unprojectGround((x-camera.x)/camera.zoom,(y-camera.y)/camera.zoom);}
  function worldToScreen(x,y){const q=renderer.projectGround(x,y);return {x:q.x*camera.zoom+camera.x,y:q.y*camera.zoom+camera.y};}
  function focusPlayer(force=false){
    if(!isAdmin)camera.follow=true;
    if(!force&&!camera.follow)return;
    const q=renderer.projectActor(player);camera.x=vw/2-q.x*camera.zoom;camera.y=vh/2-q.y*camera.zoom;
  }
  function zoomBy(factor){
    if(floorTransition.blocking)return;
    const anchor={x:(vw/2-camera.x)/camera.zoom,y:(vh/2-camera.y)/camera.zoom};
    camera.zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,camera.zoom*factor));
    if(camera.follow)focusPlayer();else{camera.x=vw/2-anchor.x*camera.zoom;camera.y=vh/2-anchor.y*camera.zoom;}
    updateZoom();
  }
  function updateZoom(){
    $('zoomLabel').textContent=Math.round(camera.zoom*100)+'%';
    $('zoomLabel').title=isAdmin?'관리자 · 마우스 휠 또는 + / −로 확대·축소':'마우스 휠 또는 + / −로 확대·축소 (50~150%)';
    $('zoomIn').disabled=camera.zoom>=MAX_ZOOM-1e-9;$('zoomOut').disabled=camera.zoom<=MIN_ZOOM+1e-9;
    $('followBtn').hidden=!isAdmin;$('followBtn').setAttribute('aria-pressed',String(camera.follow));$('followBtn').textContent='화면 고정: '+(camera.follow?'켬':'끔');
    $('cameraStatus').textContent=camera.follow?'내 위치 고정':'자유 보기 · 드래그';$('cameraHint').textContent=camera.follow?'내 위치 화면':'자유 보기';canvas.style.cursor=isAdmin&&!camera.follow?'grab':'default';
  }
  function resize(){
    const oldWidth=vw,oldHeight=vh,r=viewport.getBoundingClientRect();vw=r.width;vh=r.height;dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(vw*dpr);canvas.height=Math.round(vh*dpr);
    if(camera.follow)focusPlayer();else{camera.x+=(vw-oldWidth)/2;camera.y+=(vh-oldHeight)/2;}updateZoom();
  }
  function render(t){
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=D.id==='campus'?'#eee5d6':'#ecf0eb';ctx.fillRect(0,0,vw,vh);
    ctx.save();ctx.translate(camera.x,camera.y);ctx.scale(camera.zoom,camera.zoom);
    const actors=visibleActors();
    renderer.draw(ctx,{camera,actors,t,hover,nearby,viewportWidth:vw,viewportHeight:vh,showNicknames:social.preferences.nicknames});ctx.restore();
    social.render(t,{actors,camera,projectActor:renderer.projectActor,selfId:presence.selfId,floor:D.id,avatarSize:window.CampusAvatars.size});
  }
  function update(t){
    const dt=Math.min((t-lastTime)/1000,.04)||.016;lastTime=t;
    if(!classroom.blocking)presence.setInput(!isDialogOpen()?[...keys]:[]);
    classroom.tick(t,dt);poke.tick(t);checkExit();
    presence.tick(t,dt);
    for(const actor of visibleActors()){
      actor.walkTime=actor.moving?(actor.walkTime||0)+dt:0;
      window.CampusStairs.updateActor(D,actor,dt);
    }
    focusPlayer();
    const r=D.rooms.find(room=>room.id===serverHints.roomId);if(r&&r.id!==lastRoom){lastRoom=r.id;spaceGuide.setRoom(r.id);$('currentRoom').textContent=r.name;for(const b of document.querySelectorAll('[data-room]')){b.classList.toggle('active',b.dataset.room===r.id);b.setAttribute('aria-current',b.dataset.room===r.id?'location':'false');}}
    nearby=D.objects.find(object=>object.id===serverHints.nearbyId)||null;
    $('interactionPrompt').hidden=!nearby;if(nearby){$('interactionPrompt').querySelector('span').textContent=nearby.name;$('interactionPrompt').querySelector('button').textContent=window.CampusDoors.isDoor(nearby)?(nearby.open?'닫기':'열기'):'보기';}
    render(t);requestAnimationFrame(update);
  }
  function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,2800);}
  function visibleActors(){return [player,...[...presence.peers.values()].filter(peer=>(peer.floor||'campus')===D.id&&peer.inClassroom!==true)];}
  function restorePosition(position,refresh=true){
    if(!validPosition(position))return;
    keys.clear();hover=nearby=null;lastRoom='';
    if(D.id!==position.floor){
      D=worlds[position.floor];window.CampusData=D;
      renderer=renderers.get(D.id)||window.CampusIsometric.create({data:D});renderers.set(D.id,renderer);P=renderer.projection;scene=renderer.scene;
      renderer.setRaffleState(raffleUI.state);
    }
    Object.assign(player,{floor:D.id,x:position.x,y:position.y,targetX:position.x,targetY:position.y,dir:position.dir,moving:false,walkTime:0});
    window.CampusStairs.resetActor(D,player);
    if(refresh){focusPlayer(true);updateFloorUI();updateZoom();loadPlazaDisplays(D,renderer);}
  }
  async function switchFloor(id,objectId){
    try{
      return await floorTransition.run(async()=>{
        await presence.command('transfer',{floor:id});
        render(performance.now());toast(id==='rooftop'?'옥상 광장에 도착했어요.':'18층 캠퍼스로 내려왔어요.');return true;
      },{from:D.id,to:id,avatar:player.avatar,kind:window.CampusFloorTransition.kindFor(objectId)});
    }catch(error){
      presence.command('cancel_transfer').catch(()=>{});toast(error.message);return false;
    }
  }
  function cancelTransfer(){
    pendingTransfer=null;keys.clear();transferDialog.close();
    presence.command('cancel_transfer').catch(error=>toast(error.message));canvas.focus({preventScroll:true});
  }
  function confirmTransfer(){
    const pending=pendingTransfer;pendingTransfer=null;transferDialog.close();keys.clear();
    if(pending)switchFloor(pending.floor,pending.objectId);
  }
  async function useStairs(item){
    if(isDialogOpen())return;
    try{applyControlEvent(await presence.command('prepare_transfer',{objectId:item.id}));}catch(error){toast(error.message);}
  }
  function updateFloorUI(){
    const hasBoard=D.id==='campus';$('boardShortcut').hidden=!hasBoard;
    viewport.closest('.map-shell').dataset.boardShortcutVisible=String(hasBoard);
    spaceGuide.setWorld(D,serverHints.roomId);
    $('currentFloor').textContent=D.name;
    $('currentRoom').textContent=D.rooms.find(room=>room.id===serverHints.roomId)?.name||(D.id==='campus'?'캠퍼스 복도':'옥상 광장');
    $('mapHeading').textContent=D.id==='campus'?'2.5D 캠퍼스':'옥상 광장';
    canvas.setAttribute('aria-label',D.name+'. 방향키 또는 WASD로 이동하고 계단으로 층을 오갈 수 있습니다.');
  }
  async function loadPlazaDisplays(data,view){
    const boards=data.objects.filter(o=>o.type==='plaza-display'||o.type==='wall-poster');if(!boards.length)return;
    const last=displayRefresh.get(data.id)||0;if(Date.now()-last<30000)return;displayRefresh.set(data.id,Date.now());
    await Promise.all(boards.map(async board=>{
      try{
        let source=board.imageUrl;
        if(board.source==='menu'){
          const response=await fetch(board.menuEndpoint,{credentials:'same-origin',cache:'no-store'});
          if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))return;
          source=(await response.json()).imageUrl;if(!source)return;
        }
        if(!source)return;
        const url=new URL(source,document.baseURI);
        if(url.origin!==location.origin||(board.source==='menu'&&!url.pathname.startsWith('/api/board/menu/images/')))return;
        if(board.photo===url.href)return;
        const image=await new Promise((resolve,reject)=>{const photo=new Image();photo.onload=()=>resolve(photo);photo.onerror=reject;photo.src=url.href;});
        if(view.setDisplayImage(board.id,image)){board.photo=url.href;if(D===data)updateFloorUI();}
      }catch{ /* Keep the legible placeholder when an image is unavailable. */ }
    }));
  }
  function checkExit(){
    if(!serverHints.exitRequired||isDialogOpen()||logoutPending)return;
    keys.clear();presence.setInput([]);exitDialog.showModal();$('exitNo').focus({preventScroll:true});
  }
  async function cancelExit(){
    if(!exitDialog.open||logoutPending)return;
    try{await presence.command('cancel_exit');exitDialog.close();keys.clear();canvas.focus({preventScroll:true});}catch(error){toast(error.message);}
  }
  function confirmExit(){
    if(!exitDialog.open||!logoutForm||logoutPending)return;
    logoutPending=true;$('exitYes').disabled=true;$('exitNo').disabled=true;
    keys.clear();player.moving=false;
    // Submit the existing POST form with Django's CSRF token and session cookie.
    logoutForm.requestSubmit();
  }
  function showDetail(item,{keyboard=false}={}){
    if(item.action==='learning'){toast(window.CampusClassroom?'학습교실 출입구로 입장해 주세요.':'로그인한 서버 화면에서 학습교실을 이용해 주세요.');return;}
    if(floorTransition.blocking||window.CampusSession?.ending)return;
    if(item.info===false)return;
    if(window.CampusDoors.isDoor(item)){toggleDoor(item);return;}
    if(item.action==='raffle'){raffleUI.open();return;}
    if(item.action==='booth'){presence.command('open_booth',{objectId:item.id}).then(()=>boothUI.open(item)).catch(error=>toast(error.message));return;}
    if(item.toFloor&&(keyboard||item.confirmTransfer)){useStairs(item);return;}
    if(item.type==='noticeboard'){showBoard();return;}
    if(item.type==='plaza-display'&&item.source==='menu'){showBoard();showMenuPhoto();return;}
    const r=D.rooms.find(r=>r.id===(item.roomId||item.id));
    $('detailTitle').textContent=item.name;$('detailEyebrow').textContent=item.type?'FACILITY GUIDE':'SPACE GUIDE';
    $('detailText').textContent=item.description||r?.description||'캠퍼스 안에 배치된 '+item.name+'입니다. 캐릭터로 가까이 이동해 공간을 둘러보세요.';
    const photo=item.photo??item.imageUrl??r?.photo;$('detailImage').hidden=!photo;if(photo){$('detailImage').src=photo;$('detailImage').alt=item.name+' 참고 사진';}else $('detailImage').removeAttribute('src');
    $('detailTags').replaceChildren();for(const label of item.tags||r?.tags||[]){const e=document.createElement('span');e.textContent=label;$('detailTags').append(e);}
    keys.clear();player.moving=false;dialog.showModal();
  }
  function showBoard(){
    keys.clear();player.moving=false;
    showBoardChoices(false);
    for(const card of boardCards){card.setAttribute('aria-pressed','false');card.querySelector('.board-card-state').textContent='선택하기';}
    $('boardSelection').textContent='';boardDialog.showModal();$('boardMenuCard').focus({preventScroll:true});
  }
  function applyDoorState(id,open){
    const door=worlds.campus.objects.find(o=>o.id===id&&window.CampusDoors.isDoor(o));
    if(!door||typeof open!=='boolean'||door.open===open)return;
    door.open=open;const view=renderers.get('campus');view?.setDoorState(id,open);
  }
  function toggleDoor(door){
    if(isDialogOpen())return;
    keys.clear();presence.setInput([]);
    if(!presence.requestDoor(door.id,!door.open))toast('연결된 뒤 문을 열고 닫을 수 있어요.');
    canvas.focus({preventScroll:true});
  }
  function cancelMenuRequest(){lunchWheel?.cancel();menuRequest?.abort();menuRequest=null;menuVersion++;$('boardMenuImage').onload=$('boardMenuImage').onerror=null;$('boardMenuImage').removeAttribute('src');}
  function showBoardChoices(focus=true){
    communityUI.hide();
    cancelMenuRequest();$('boardMenuView').hidden=true;$('boardChoices').hidden=false;$('boardDescription').hidden=false;$('boardSelection').hidden=false;
    if(focus)$('boardMenuCard').focus({preventScroll:true});
  }
  async function showMenuPhoto(){
    cancelMenuRequest();const version=menuVersion;menuRequest=new AbortController();
    $('boardChoices').hidden=true;$('boardDescription').hidden=true;$('boardSelection').hidden=true;$('boardMenuView').hidden=false;$('boardMenuView').setAttribute('aria-busy','true');
    $('boardMenuImage').hidden=true;$('boardMenuOpen').hidden=true;$('boardMenuOpen').removeAttribute('href');$('boardMenuUpdated').textContent='';$('boardMenuStatus').textContent='식단 사진을 불러오는 중이에요.';$('boardMenuBack').focus({preventScroll:true});
    const failed=()=>{if(version!==menuVersion)return;$('boardMenuView').setAttribute('aria-busy','false');$('boardMenuImage').hidden=true;$('boardMenuOpen').hidden=true;$('boardMenuStatus').textContent='식단 사진을 불러오지 못했어요. 카드 선택으로 돌아가 다시 선택해 주세요.';};
    try{
      const response=await fetch('/api/board/menu/',{credentials:'same-origin',cache:'no-store',signal:menuRequest.signal});
      if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('Menu unavailable');
      const data=await response.json();if(version!==menuVersion||!boardDialog.open)return;
      if(!data.imageUrl){$('boardMenuView').setAttribute('aria-busy','false');$('boardMenuStatus').textContent='아직 등록된 식단 사진이 없어요.';return;}
      const imageUrl=new URL(data.imageUrl,window.location.href);if(imageUrl.origin!==window.location.origin||!imageUrl.pathname.startsWith('/api/board/menu/images/'))throw new Error('Unexpected menu image');
      const updated=new Date(data.updatedAt);if(!Number.isFinite(updated.getTime()))throw new Error('Invalid photo date');
      $('boardMenuSource').textContent=data.sourceName;
      $('boardMenuUpdated').textContent='가져온 시간 · '+new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(updated);
      $('boardMenuImage').onload=()=>{if(version!==menuVersion)return;$('boardMenuView').setAttribute('aria-busy','false');$('boardMenuStatus').textContent='';$('boardMenuOpen').hidden=false;};
      $('boardMenuImage').onerror=failed;$('boardMenuOpen').href=imageUrl.href;$('boardMenuImage').hidden=false;$('boardMenuImage').src=imageUrl.href;
    }catch(error){if(error.name!=='AbortError')failed();}
  }
  // Facility clicks open information; an administrator may drag the unlocked camera.
  function pointerPosition(e){const r=canvas.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
  let press=null;
  canvas.addEventListener('pointerdown',e=>{if(e.button!==0||floorTransition.blocking)return;press={...pointerPosition(e),cameraX:camera.x,cameraY:camera.y,dragging:false};canvas.setPointerCapture(e.pointerId);canvas.focus({preventScroll:true});});
  canvas.addEventListener('pointermove',e=>{if(floorTransition.blocking)return;const p=pointerPosition(e);if(press&&isAdmin&&!camera.follow&&(press.dragging||Math.hypot(p.x-press.x,p.y-press.y)>5)){press.dragging=true;camera.x=press.cameraX+p.x-press.x;camera.y=press.cameraY+p.y-press.y;hover=null;canvas.style.cursor='grabbing';return;}hover=renderer.hitTest((p.x-camera.x)/camera.zoom,(p.y-camera.y)/camera.zoom);canvas.style.cursor=hover?'pointer':isAdmin&&!camera.follow?'grab':'default';});
  canvas.addEventListener('pointerup',e=>{if(floorTransition.blocking){press=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);return;}if(e.button!==0||!press)return;const p=pointerPosition(e),start=press;press=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(start.dragging||Math.hypot(p.x-start.x,p.y-start.y)>5){updateZoom();return;}const item=renderer.hitTest((p.x-camera.x)/camera.zoom,(p.y-camera.y)/camera.zoom);if(item)showDetail(item);});
  canvas.addEventListener('pointercancel',()=>{press=null;updateZoom();});canvas.addEventListener('pointerleave',()=>{if(!press)hover=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoomBy(Math.exp(-e.deltaY*.0015));},{passive:false});
  $('followBtn').onclick=()=>{if(!isAdmin)return;camera.follow=!camera.follow;press=null;hover=null;if(camera.follow)focusPlayer();updateZoom();};
  updateFloorUI();updateZoom();new ResizeObserver(resize).observe(viewport);
  const mapShell=viewport.closest('.map-shell'),mapFooter=mapShell.querySelector('.map-footer');
  new ResizeObserver(()=>mapShell.style.setProperty('--map-footer-height',mapFooter.getBoundingClientRect().height+'px')).observe(mapFooter);
  document.addEventListener('keydown',e=>{
    const k=window.CampusKeyboard.key(e);
    if(e.target.closest?.('#campusNavToggle,#campusSpaceGuide')&&['enter',' '].includes(k))return;
    if(floorTransition.blocking){
      if(movementKeys.has(k))suppressedKeys.add(k);
      if(movementKeys.has(k)||['e','z','escape','enter','+','=','-'].includes(k))e.preventDefault();
      return;
    }
    if(suppressedKeys.has(k)){e.preventDefault();return;}
    if((e.isComposing&&!window.CampusKeyboard.isGameKey(e))||isDialogOpen()||e.target.closest?.('input,textarea,select,[contenteditable="true"]'))return;
    if(k==='escape'&&!e.repeat){e.preventDefault();social.openSettings();}
    else if(k==='enter'&&!e.repeat){if(social.focusChat())e.preventDefault();}
    else if(movementKeys.has(k)){e.preventDefault();keys.add(k);}
    else if(k==='e'&&nearby&&!e.repeat){e.preventDefault();showDetail(nearby,{keyboard:true});}
    else if(k==='z'&&!e.repeat&&!e.ctrlKey&&!e.altKey&&!e.metaKey){e.preventDefault();poke.setHeld(true);}
    else if(k==='+'||k==='='){e.preventDefault();zoomBy(1.2);}
    else if(k==='-'){e.preventDefault();zoomBy(1/1.2);}
  });
  document.addEventListener('keyup',e=>{const k=window.CampusKeyboard.key(e);keys.delete(k);suppressedKeys.delete(k);});
  window.addEventListener('blur',()=>{keys.clear();suppressedKeys.clear();});
  $('zoomIn').onclick=()=>zoomBy(1.25);$('zoomOut').onclick=()=>zoomBy(1/1.25);
  $('closeDialog').onclick=$('detailClose').onclick=()=>{dialog.close();canvas.focus({preventScroll:true});};
  $('closeBoardDialog').onclick=$('boardClose').onclick=()=>{if(communityUI.canLeave())boardDialog.close();};
  $('openBoardShortcut').onclick=()=>{if(D.id==='campus'&&!isDialogOpen())showBoard();};
  $('chatOpen').onclick=()=>{if(!isDialogOpen())social.focusChat();};
  for(const card of boardCards)card.addEventListener('click',()=>{
    for(const option of boardCards){const selected=option===card;option.setAttribute('aria-pressed',String(selected));option.querySelector('.board-card-state').textContent=selected?'선택됨':'선택하기';}
    $('boardSelection').textContent=card.dataset.boardChoice+' 카드가 선택됐어요.';
    if(card.id==='boardMenuCard')showMenuPhoto();
    if(card.id==='boardEncoreCard'){cancelMenuRequest();communityUI.open();}
  });
  $('boardMenuBack').onclick=()=>showBoardChoices();
  boardDialog.addEventListener('close',()=>{cancelMenuRequest();communityUI.hide();keys.clear();canvas.focus({preventScroll:true});});
  boardDialog.addEventListener('cancel',e=>{if(!communityUI.canLeave())e.preventDefault();});
  boardDialog.addEventListener('click',e=>{if(e.target!==boardDialog)return;const r=boardDialog.getBoundingClientRect();if((e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)&&communityUI.canLeave())boardDialog.close();});
  $('transferNo').onclick=cancelTransfer;$('transferYes').onclick=confirmTransfer;
  transferDialog.addEventListener('cancel',event=>{event.preventDefault();cancelTransfer();});
  transferDialog.addEventListener('keydown',event=>{
    if(!transferDialog.open||event.isComposing)return;
    const key=event.key;
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key)){
      event.preventDefault();event.stopPropagation();keys.clear();suppressedKeys.add(key.toLowerCase());
      const button=(key==='ArrowLeft'||key==='ArrowUp')?$('transferNo'):$('transferYes');
      button.focus({preventScroll:true});
    }else if(key==='Enter'){
      event.preventDefault();event.stopPropagation();
      if(event.repeat)return;
      if(document.activeElement===$('transferNo'))cancelTransfer();else confirmTransfer();
    }
  });
  $('exitNo').onclick=cancelExit;$('exitYes').onclick=confirmExit;
  exitDialog.addEventListener('cancel',e=>{e.preventDefault();cancelExit();});
  dialog.addEventListener('click',e=>{const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();});
  $('interactionPrompt').querySelector('button').onclick=()=>nearby&&showDetail(nearby);
  function updateAvatarPreview(){const id=window.CampusAvatars.resolve(player.avatar);$('avatarPreview').src=`assets/characters/${id}-preview.png`;$('avatarName').textContent=window.CampusAvatars.definitions[id].name;}
  updateAvatarPreview();
  window.addEventListener('campus:avatar',updateAvatarPreview);
  window.CampusApp={showDetail,get scene(){return scene;},player,camera,screenToWorld,worldToScreen,canZoom:true,canFreeCamera:isAdmin,boothUI,raffleUI,floorTransition,social,presence,classroom,poke,get nearby(){return nearby;},get renderer(){return renderer;},get floor(){return D.id;},get data(){return D;},visibleActors,switchFloor,render,toast,zoomBy};
  window.addEventListener('campus:guide-open',()=>{keys.clear();suppressedKeys.clear();player.moving=false;presence.setInput([]);poke.setHeld(false);});
  requestAnimationFrame(update);
  window.dispatchEvent(new Event('campus:ready'));
  setInterval(()=>{if(D.id==='rooftop'&&!document.hidden)loadPlazaDisplays(D,renderer);},60000);
})();
