(() => {
  'use strict';
  const worlds=window.CampusWorlds, $=id=>document.getElementById(id);
  const DEFAULT_ZOOM=1.45;
  const MOVE_SPEED=125*1.25;
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
  let menuRequest=null,menuVersion=0;
  const isDialogOpen=()=>dialog.open||boardDialog.open||exitDialog.open||transferDialog.open||$('settingsDialog').open||social.isTyping||boothUI.blocking;
  const renderers=new Map();
  const displayRefresh=new Map();
  let renderer=window.CampusIsometric.create({data:D}), P=renderer.projection, scene=renderer.scene;
  renderers.set(D.id,renderer);
  const camera={x:0,y:0,zoom:DEFAULT_ZOOM,follow:true}, player={...initialPosition,avatar,color:window.CampusAvatars.definitions[avatar].color,moving:false,step:0,walkTime:0};
  let exitReturnPoint={x:spawn[0],y:spawn[1]}, logoutPending=false;
  let vw=0,vh=0,dpr=1,nearby=null,hover=null,lastRoom='',lastTime=0,toastTimer,lastPortalAt=-Infinity;
  const keys=new Set();
  const social=window.CampusSocial.create({config:accountConfig,onFocus(){keys.clear();player.moving=false;},onSend:text=>presence.sendChat(text),getSelfId:()=>presence.selfId});
  let pendingTransfer=null,ignoredPortalId=null;
  const boothUI=window.CampusBoothPanel.create({onOpen(){keys.clear();player.moving=false;},onClose(){keys.clear();canvas.focus({preventScroll:true});}});
  const presence=window.CampusPresence.create({player,width:D.width,height:D.height,floors:worlds,onRestore:position=>restorePosition(position),onAuthExpired(){keys.clear();player.moving=false;},onChat:message=>social.receive(message),onChatError:message=>social.reportError(message),onConnectionChange:value=>social.setConnected(value)});
  const solidTypes=new Set(['desk','chair','bar','counter','water','coffee-machine','printer','bin','pillar','bookshelf','bookshelf-side','sofa','bench','coffee','roundtable','ottoman','cabinet','box','tv','plant','fire-extinguisher','noticeboard','stool','woodwall','glass-wall','tree','planter','terrace-bench','festival-booth','festival-stage','speaker','photo-frame','booth-collider','booth-side','game-arcade','game-gomoku-table','game-pc-station','game-console-display','game-controller-shelf','creator-screen','camera-tripod','microphone-stand','creator-console','creator-award','photo-backdrop','ring-light','phone-podium','photo-display','psych-test-backdrop','psych-type-wheel','psych-question-kiosk','psych-mood-cards','fountain','plaza-display','plaza-lamp']);
  function distRect(x,y,o){if(o.interactionPoint)return Math.hypot(x-o.interactionPoint[0],y-o.interactionPoint[1]);const r=renderer.footprint(o);return Math.hypot(Math.max(r.x-x,0,x-r.x-r.w),Math.max(r.y-y,0,y-r.y-r.h));}
  const inside=(r,x,y)=>x>=r.x&&x<=r.x+r.w&&y>=r.y&&y<=r.y+r.h;
  // Bucket nearby wall and furniture footprints for keyboard movement.
  const collisionBuckets=new Map(),bucketSize=64;
  // Furniture may define a floor footprint relative to its drawing bounds.
  let navigation;
  function rebuildCollision(){
    collisionBuckets.clear();
    const colliders=[...D.walls.map(w=>({x:Math.min(w.x1,w.x2),y:Math.min(w.y1,w.y2),w:Math.abs(w.x2-w.x1),h:Math.abs(w.y2-w.y1),pad:5})),...D.objects.filter(o=>o.solid!==false&&solidTypes.has(o.type)).map(o=>({x:o.x+(o.collision?.x??0),y:o.y+(o.collision?.y??0),w:o.collision?.w??o.w,h:o.collision?.h??o.h,pad:0}))];
    for(const o of colliders){const margin=o.pad+6;for(let yy=Math.floor((o.y-margin)/bucketSize);yy<=Math.floor((o.y+o.h+margin)/bucketSize);yy++)for(let xx=Math.floor((o.x-margin)/bucketSize);xx<=Math.floor((o.x+o.w+margin)/bucketSize);xx++){const id=xx+','+yy;if(!collisionBuckets.has(id))collisionBuckets.set(id,[]);collisionBuckets.get(id).push(o);}}
    navigation=window.CampusNavigation.create({width:D.width,height:D.height,isWalkable:walkable});
  }
  rebuildCollision();
  restorePosition(initialPosition,false);
  function walkable(x,y,radius=5.5){
    if(!D.rooms.some(r=>inside(r,x,y))&&!(D.entrance&&inside(D.entrance,x,y)))return false;
    const candidates=collisionBuckets.get(Math.floor(x/bucketSize)+','+Math.floor(y/bucketSize))||[];
    return !candidates.some(o=>{const dx=Math.max(o.x-x,0,x-o.x-o.w),dy=Math.max(o.y-y,0,y-o.y-o.h);return dx*dx+dy*dy<(radius+o.pad)**2;});
  }
  const roomAt=(x,y)=>[...D.rooms].reverse().find(r=>inside(r,x,y))||(D.entrance&&inside(D.entrance,x,y)?D.entrance:null);
  function move(dx,dy){
    const px=player.x,py=player.y;
    if(walkable(player.x+dx,player.y))player.x+=dx;
    if(walkable(player.x,player.y+dy))player.y+=dy;
    player.moving=Math.hypot(player.x-px,player.y-py)>.01;return player.moving;
  }
  function screenToWorld(x,y){return renderer.unprojectGround((x-camera.x)/camera.zoom,(y-camera.y)/camera.zoom);}
  function worldToScreen(x,y){const q=renderer.projectGround(x,y);return {x:q.x*camera.zoom+camera.x,y:q.y*camera.zoom+camera.y};}
  function focusPlayer(force=false){
    if(!isAdmin)camera.follow=true;
    if(!force&&!camera.follow)return;
    const q=renderer.projectActor(player);camera.x=vw/2-q.x*camera.zoom;camera.y=vh/2-q.y*camera.zoom;
  }
  function zoomBy(factor){
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
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#ecf0eb';ctx.fillRect(0,0,vw,vh);
    ctx.save();ctx.translate(camera.x,camera.y);ctx.scale(camera.zoom,camera.zoom);
    const actors=visibleActors();
    renderer.draw(ctx,{camera,actors,t,hover,nearby,viewportWidth:vw,viewportHeight:vh,showNicknames:social.preferences.nicknames});ctx.restore();
    social.render(t,{actors,camera,projectActor:renderer.projectActor,selfId:presence.selfId,floor:D.id,avatarSize:window.CampusAvatars.size});
  }
  function update(t){
    const dt=Math.min((t-lastTime)/1000,.04)||.016;lastTime=t;
    const wasMoving=player.moving;player.moving=false;
    if(!isDialogOpen()){
      const k=keys;let dx=(k.has('d')||k.has('arrowright')?1:0)-(k.has('a')||k.has('arrowleft')?1:0),dy=(k.has('s')||k.has('arrowdown')?1:0)-(k.has('w')||k.has('arrowup')?1:0);
      if(dx||dy){
        const horizontal=dx>0?'right':'left',vertical=dy>0?'down':'up';
        // Keep a compatible facing while walking diagonally; start sideways from rest.
        if(!dx)player.dir=vertical;
        else if(!dy||!wasMoving||(player.dir!==horizontal&&player.dir!==vertical))player.dir=horizontal;
        const length=Math.hypot(dx,dy),v=P.inverseVector(dx/length,dy/length);move(v.x*MOVE_SPEED*dt,v.y*MOVE_SPEED*dt);
      }

    }
    checkPortals(t);checkExit();
    presence.tick(t,dt);
    for(const actor of visibleActors()){
      actor.walkTime=actor.moving?(actor.walkTime||0)+dt:0;
      const z=D.elevationAt?.(actor.x,actor.y)||0;
      actor.visualZ=Number.isFinite(actor.visualZ)?actor.visualZ+(z-actor.visualZ)*Math.min(dt*24,1):z;
    }
    focusPlayer();
    const r=roomAt(player.x,player.y);if(r&&r.id!==lastRoom){lastRoom=r.id;$('currentRoom').textContent=r.name;for(const b of document.querySelectorAll('[data-room]')){b.classList.toggle('active',b.dataset.room===r.id);b.setAttribute('aria-current',b.dataset.room===r.id?'location':'false');}}
    nearby=D.objects.filter(o=>o.name&&distRect(player.x,player.y,o)<35).sort((a,b)=>distRect(player.x,player.y,a)-distRect(player.x,player.y,b))[0]||null;
    $('interactionPrompt').hidden=!nearby;if(nearby)$('interactionPrompt').querySelector('span').textContent=nearby.name;
    render(t);requestAnimationFrame(update);
  }
  function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,2800);}
  function closestOpen(x,y,max=55){if(walkable(x,y))return {x,y};for(let radius=4;radius<=max;radius+=4)for(let i=0;i<24;i++){const a=i*Math.PI/12,p={x:x+Math.cos(a)*radius,y:y+Math.sin(a)*radius};if(walkable(p.x,p.y))return p;}return null;}
  function visibleActors(){return [player,...[...presence.peers.values()].filter(peer=>(peer.floor||'campus')===D.id)];}
  function restorePosition(position,refresh=true){
    if(!validPosition(position))return;
    keys.clear();hover=nearby=null;lastRoom='';
    if(D.id!==position.floor){
      D=worlds[position.floor];window.CampusData=D;
      renderer=renderers.get(D.id)||window.CampusIsometric.create({data:D});renderers.set(D.id,renderer);P=renderer.projection;scene=renderer.scene;
      rebuildCollision();
    }
    // A changed map may have placed furniture over an old saved location.
    const outside=D.entrance&&inside(D.entrance,position.x,position.y);
    const target=(!outside&&closestOpen(position.x,position.y,80))||closestOpen(...D.spawn,80);
    if(!target)throw new Error('Saved position needs a walkable spawn');
    Object.assign(player,{floor:D.id,x:target.x,y:target.y,dir:position.dir,moving:false,walkTime:0,visualZ:D.elevationAt?.(target.x,target.y)||0});
    lastPortalAt=performance.now();ignoredPortalId=D.portals.find(portal=>inside(portal,target.x,target.y))?.objectId||null;
    if(D.entrance)exitReturnPoint={x:target.x,y:Math.min(target.y,D.entrance.y-12)};
    if(refresh){focusPlayer(true);nav();updateFloorUI();updateZoom();loadPlazaDisplays(D,renderer);}
  }
  function switchFloor(id,arrival){
    if(!Object.hasOwn(worlds,id)||id===D.id)return false;
    keys.clear();hover=nearby=null;lastRoom='';
    D=worlds[id];window.CampusData=D;
    renderer=renderers.get(id)||window.CampusIsometric.create({data:D});renderers.set(id,renderer);P=renderer.projection;scene=renderer.scene;
    rebuildCollision();const target=closestOpen(...(arrival||D.spawn));if(!target)throw new Error('Floor arrival must be walkable');
    Object.assign(player,{floor:id,x:target.x,y:target.y,moving:false,visualZ:D.elevationAt?.(target.x,target.y)||0});lastPortalAt=performance.now();
    ignoredPortalId=D.portals.find(portal=>inside(portal,player.x,player.y))?.objectId||null;
    focusPlayer(true);nav();updateFloorUI();updateZoom();
    loadPlazaDisplays(D,renderer);
    canvas.focus({preventScroll:true});toast(id==='rooftop'?'옥상 광장에 도착했어요.':'18층 캠퍼스로 내려왔어요.');return true;
  }
  function checkPortals(t){
    if(isDialogOpen())return;
    if(ignoredPortalId){const ignored=D.portals.find(portal=>portal.objectId===ignoredPortalId);if(ignored&&inside(ignored,player.x,player.y))return;ignoredPortalId=null;}
    if(t-lastPortalAt<1200)return;
    const portal=D.portals.find(portal=>inside(portal,player.x,player.y));
    if(portal){const object=D.objects.find(o=>o.id===portal.objectId);if(object.confirmTransfer)requestTransfer(object);else switchFloor(object.toFloor,object.arrival);}
  }
  function requestTransfer(item){
    if(transferDialog.open||!worlds[item.toFloor]||distRect(player.x,player.y,item)>=35)return;
    keys.clear();player.moving=false;pendingTransfer={floor:D.id,item};
    $('transferDescription').textContent=worlds[item.toFloor].name+'으로 이동합니다. 예를 누르면 이동하고, 아니오를 누르면 현재 위치에 머뭅니다.';
    transferDialog.showModal();$('transferNo').focus();
  }
  function cancelTransfer(){
    if(pendingTransfer)ignoredPortalId=pendingTransfer.item.id;
    pendingTransfer=null;keys.clear();transferDialog.close();canvas.focus({preventScroll:true});
  }
  function confirmTransfer(){
    const pending=pendingTransfer;pendingTransfer=null;transferDialog.close();keys.clear();
    if(pending&&pending.floor===D.id&&distRect(player.x,player.y,pending.item)<35)switchFloor(pending.item.toFloor,pending.item.arrival);
  }
  function useStairs(item){
    if(performance.now()-lastPortalAt<1200)return;
    if(distRect(player.x,player.y,item)<35){if(item.confirmTransfer)requestTransfer(item);else switchFloor(item.toFloor,item.arrival);}

  }
  function updateFloorUI(){
    $('currentFloor').textContent=D.name;
    $('mapHeading').textContent=D.id==='campus'?'2.5D 캠퍼스':'옥상 광장';
    document.querySelector('.sidebar-heading h1').textContent=D.id==='campus'?'공간 둘러보기':'옥상 광장 둘러보기';
    $('referenceBtn').textContent=D.id==='campus'?'설계도 보기':'옥상 안내';
    $('exportBtn').href=scene.toDataURL('image/png');$('exportBtn').download=D.id==='campus'?'PLAYDATA-campus-map.png':'PLAYDATA-rooftop-map.png';
    canvas.setAttribute('aria-label',D.name+'. 방향키 또는 WASD로 이동하고 계단으로 층을 오갈 수 있습니다.');
  }
  async function loadPlazaDisplays(data,view){
    const boards=data.objects.filter(o=>o.type==='plaza-display');if(!boards.length)return;
    const last=displayRefresh.get(data.id)||0;if(Date.now()-last<30000)return;displayRefresh.set(data.id,Date.now());
    await Promise.all(boards.map(async board=>{
      try{
        let source=board.imageUrl;
        if(board.source==='menu'){
          const response=await fetch(board.menuEndpoint,{credentials:'same-origin',cache:'no-store'});
          if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))return;
          source=(await response.json()).imageUrl;if(!source)return;
        }
        const url=new URL(source,document.baseURI);
        if(url.origin!==location.origin||(board.source==='menu'&&!url.pathname.startsWith('/api/board/menu/images/')))return;
        if(board.photo===url.href)return;
        const image=await new Promise((resolve,reject)=>{const photo=new Image();photo.onload=()=>resolve(photo);photo.onerror=reject;photo.src=url.href;});
        if(view.setDisplayImage(board.id,image)){board.photo=url.href;if(D===data)updateFloorUI();}
      }catch{ /* Keep the legible placeholder when an image is unavailable. */ }
    }));
  }
  function checkExit(){
    // Logout belongs to the authenticated Django map, which supplies this form.
    if(!logoutForm||!D.entrance||isDialogOpen()||logoutPending)return;
    if(D.rooms.some(r=>inside(r,player.x,player.y))&&player.y<=D.entrance.y-12)exitReturnPoint={x:player.x,y:player.y};
    if(!inside(D.entrance,player.x,player.y)||player.y<=D.entrance.y+6)return;
    keys.clear();player.moving=false;
    exitDialog.showModal();$('exitNo').focus();
  }
  function cancelExit(){
    if(!exitDialog.open||logoutPending)return;
    const point=closestOpen(exitReturnPoint.x,Math.min(exitReturnPoint.y,D.entrance.y-12),30)||closestOpen(...spawn,30);
    if(point){player.x=point.x;player.y=point.y;}
    keys.clear();player.moving=false;
    exitDialog.close();canvas.focus({preventScroll:true});
  }
  function confirmExit(){
    if(!exitDialog.open||!logoutForm||logoutPending)return;
    logoutPending=true;$('exitYes').disabled=true;$('exitNo').disabled=true;
    keys.clear();player.moving=false;
    // Submit the existing POST form with Django's CSRF token and session cookie.
    logoutForm.requestSubmit();
  }
  function showDetail(item,{keyboard=false}={}){
    if(item.action==='booth'){if(distRect(player.x,player.y,item)<35)boothUI.open(item);else toast('부스 중앙의 E 표시 가까이로 이동해 주세요.');return;}
    if(item.toFloor&&(keyboard||(item.confirmTransfer&&distRect(player.x,player.y,item)<35))){useStairs(item);return;}
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
  function cancelMenuRequest(){menuRequest?.abort();menuRequest=null;menuVersion++;$('boardMenuImage').onload=$('boardMenuImage').onerror=null;$('boardMenuImage').removeAttribute('src');}
  function showBoardChoices(focus=true){
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
  function nav(){
    $('roomNav').replaceChildren();
    const groups=D.id==='rooftop'?[['전시 부스',['festival-youtube','festival-instagram','festival-booth3']],['쉼터 · 연결 공간',['roof-upper','roof-terrace','roof-plaza','roof-stairs']]]:[['라운지',['lounge1','lounge2']],['강의 공간',['class1','class2','class3','class4','left-bottom','left-middle','left-top']],['회의 · 상담',['meeting','meeting-l2-a','meeting-l2-b','consult-a','consult-b']],['기타 공간',['office','storage','stairs']]];
    for(const [label,ids] of groups){const heading=document.createElement('div');heading.className='nav-group-label';heading.textContent=label;$('roomNav').append(heading);for(const id of ids){const r=D.rooms.find(r=>r.id===id),b=document.createElement('button');b.type='button';b.className='room-nav-button';b.dataset.room=id;const icon=document.createElement('span');icon.className='nav-icon';icon.textContent=id.startsWith('lounge')?'L'+id.slice(-1):id.startsWith('class')?id.slice(-1):id.startsWith('consult')?id.slice(-1).toUpperCase():id.startsWith('left')?r.name.slice(-1):'▤';const n=document.createElement('span');n.textContent=r.name;b.append(icon,n);b.addEventListener('click',()=>showDetail(r));$('roomNav').append(b);}}
  }
  // Facility clicks open information; an administrator may drag the unlocked camera.
  function pointerPosition(e){const r=canvas.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
  let press=null;
  canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;press={...pointerPosition(e),cameraX:camera.x,cameraY:camera.y,dragging:false};canvas.setPointerCapture(e.pointerId);canvas.focus({preventScroll:true});});
  canvas.addEventListener('pointermove',e=>{const p=pointerPosition(e);if(press&&isAdmin&&!camera.follow&&(press.dragging||Math.hypot(p.x-press.x,p.y-press.y)>5)){press.dragging=true;camera.x=press.cameraX+p.x-press.x;camera.y=press.cameraY+p.y-press.y;hover=null;canvas.style.cursor='grabbing';return;}hover=renderer.hitTest((p.x-camera.x)/camera.zoom,(p.y-camera.y)/camera.zoom);canvas.style.cursor=hover?'pointer':isAdmin&&!camera.follow?'grab':'default';});
  canvas.addEventListener('pointerup',e=>{if(e.button!==0||!press)return;const p=pointerPosition(e),start=press;press=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(start.dragging||Math.hypot(p.x-start.x,p.y-start.y)>5){updateZoom();return;}const item=renderer.hitTest((p.x-camera.x)/camera.zoom,(p.y-camera.y)/camera.zoom);if(item)showDetail(item);});
  canvas.addEventListener('pointercancel',()=>{press=null;updateZoom();});canvas.addEventListener('pointerleave',()=>{if(!press)hover=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoomBy(Math.exp(-e.deltaY*.0015));},{passive:false});
  $('followBtn').onclick=()=>{if(!isAdmin)return;camera.follow=!camera.follow;press=null;hover=null;if(camera.follow)focusPlayer();updateZoom();};
  nav();updateFloorUI();updateZoom();new ResizeObserver(resize).observe(viewport);
  document.addEventListener('keydown',e=>{const k=e.key.toLowerCase();if(e.isComposing||isDialogOpen()||e.target.closest?.('input,textarea,[contenteditable="true"]'))return;if(k==='escape'&&!e.repeat){e.preventDefault();social.openSettings();}else if(k==='enter'&&!e.repeat){if(social.focusChat())e.preventDefault();}else if(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright'].includes(k)){e.preventDefault();keys.add(k);}else if(k==='e'&&nearby&&!e.repeat){e.preventDefault();showDetail(nearby,{keyboard:true});}else if(k==='+'||k==='='){e.preventDefault();zoomBy(1.2);}else if(k==='-'){e.preventDefault();zoomBy(1/1.2);}});
  document.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));window.addEventListener('blur',()=>keys.clear());
  $('zoomIn').onclick=()=>zoomBy(1.25);$('zoomOut').onclick=()=>zoomBy(1/1.25);
  $('fullscreenBtn').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.querySelector('.map-shell').requestFullscreen();}catch{toast('현재 창에서는 전체 화면을 사용할 수 없습니다.');}};
  $('closeDialog').onclick=$('detailClose').onclick=()=>{dialog.close();canvas.focus({preventScroll:true});};
  $('closeBoardDialog').onclick=$('boardClose').onclick=()=>boardDialog.close();
  for(const card of boardCards)card.addEventListener('click',()=>{
    for(const option of boardCards){const selected=option===card;option.setAttribute('aria-pressed',String(selected));option.querySelector('.board-card-state').textContent=selected?'선택됨':'선택하기';}
    $('boardSelection').textContent=card.dataset.boardChoice+' 카드가 선택됐어요.';
    if(card.id==='boardMenuCard')showMenuPhoto();
  });
  $('boardMenuBack').onclick=()=>showBoardChoices();
  boardDialog.addEventListener('close',()=>{cancelMenuRequest();keys.clear();canvas.focus({preventScroll:true});});
  boardDialog.addEventListener('click',e=>{if(e.target!==boardDialog)return;const r=boardDialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)boardDialog.close();});
  $('transferNo').onclick=cancelTransfer;$('transferYes').onclick=confirmTransfer;
  transferDialog.addEventListener('cancel',event=>{event.preventDefault();cancelTransfer();});
  $('exitNo').onclick=cancelExit;$('exitYes').onclick=confirmExit;
  exitDialog.addEventListener('cancel',e=>{e.preventDefault();cancelExit();});
  dialog.addEventListener('click',e=>{const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();});
  $('referenceBtn').onclick=()=>showDetail(D.id==='rooftop'?{name:'옥상 광장 안내',description:'옥상 중앙의 세로 계단을 기준으로 휴게 광장과 아래 광장의 길이를 맞췄습니다. 위쪽 광장에는 유튜브·심리 테스트·게임 부스 세 개를 회전한 맵의 긴 변을 따라 나란히 배치하고, 입구를 오른쪽으로 90도 돌렸습니다. 분수와 광고 게시판, 계단 위쪽까지 이어진 높은 벽면을 따라 둘러보세요. 18층 라운지 2 소화기에서 E를 누르면 옥상 왼쪽 끝으로 올라올 수 있습니다.',tags:['중앙 8단 계단','전시 부스 3개','분수 · 광고 게시판','우상단 벽면']}:{name:'캠퍼스 설계도',photo:'assets/blueprint.png',description:'제공해 주신 설계도를 기준으로 방의 위치와 비율을 반영했습니다. 복도 오른쪽은 라운지 1, 왼쪽은 라운지 2입니다. 문이 표시되지 않은 곳에는 이동을 위한 출입구를 추가했습니다. 사진이 없는 강의실·직원실·회의실의 가구는 기본 구성으로 채웠습니다.',tags:['원본 설계도','실제 사진 반영','출입구 위치 추정']});
  $('interactionPrompt').querySelector('button').onclick=()=>nearby&&showDetail(nearby);
  function updateAvatarPreview(){const id=window.CampusAvatars.resolve(player.avatar);$('avatarPreview').src=`assets/characters/${id}-preview.png`;$('avatarName').textContent=window.CampusAvatars.definitions[id].name;}
  updateAvatarPreview();
  window.addEventListener('campus:avatar',updateAvatarPreview);
  window.CampusApp={walkable,roomAt,showDetail,get scene(){return scene;},player,camera,screenToWorld,worldToScreen,closestOpen,get navigation(){return navigation;},canZoom:true,canFreeCamera:isAdmin,boothUI,social,presence,get nearby(){return nearby;},get renderer(){return renderer;},get floor(){return D.id;},get data(){return D;},visibleActors,switchFloor,move,render,toast,zoomBy};
  requestAnimationFrame(update);
  setInterval(()=>{if(D.id==='rooftop'&&!document.hidden)loadPlazaDisplays(D,renderer);},60000);
})();
