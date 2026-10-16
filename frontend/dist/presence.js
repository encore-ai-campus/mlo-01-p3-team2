/* Transport keyboard intentions and display the positions accepted by the backend. */
(() => {
  'use strict';
  window.CampusPresence = {
    create({player, width, height, floors, onAuthExpired, onRestore = () => {}, onState = () => {}, onControlEvent = () => {}, onPoke = () => {}, onJump = () => {}, onChat = () => {}, onChatError = () => {}, onConnectionChange = () => {}, onDoors = () => {}, onDoor = () => {}, onDoorError = () => {}, onRaffle = () => {}, onRaffleEntry = () => {}, onRaffleSurvey = () => {}, onRaffleError = () => {}}) {
      const configElement = document.getElementById('campusPresenceConfig');
      const status = document.getElementById('presenceStatus');
      const roster = document.getElementById('presencePeers');
      const peers = new Map();
      if (!configElement) return {peers, connected:false, selfId:null, sendChat(){return false;}, setPoking(){}, requestDoor(){return false;}, joinRaffle(){return false;}, setInput() {}, command(){return Promise.reject(new Error('연결이 필요해요.'));}, tick() {}, close() {}};
      const config = JSON.parse(configElement.textContent);
      let socket = null, selfId = null, ready = false, closed = false;
      let inputKeys = [], sequence = 0, poking = false, pokeContext = null;
      const pending = new Map();
      const allowedKeys = new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright']);
      let retry = null, retryDelay = 1000, heartbeat = null, lastSent = -Infinity, lastInput = '', authChecked = false;
      let lastReceived = 0;
      const floorBounds = floors || {campus:{width,height}};
      const doorIds = new Set((floors?.campus?.objects||[]).filter(o=>(o.type==='glass-door'||(o.type==='sliding-door'&&o.interactiveDoor===true))).map(o=>o.id));
      const colors = new Set(['#dfa34d', '#4e9b91', '#8a78bb', '#cb7773', '#648eb5']);
      const directions = new Set(['up', 'down', 'left', 'right']);
      const avatars = new Set(['male-1', 'male-2', 'female-1', 'female-2']);

      function setStatus(text, state) {
        status.hidden = false;
        status.textContent = text;
        status.dataset.state = state;
        onConnectionChange(state === 'connected');
      }
      function updateRoster() {
        setStatus(`전체 접속 ${peers.size + 1}명`, 'connected');
        roster.replaceChildren();
        for (const peer of peers.values()) {
          const item = document.createElement('li');
          item.textContent = peer.nickname;
          roster.append(item);
        }
      }
      function validPeer(p) {
        const floor = p?.floor===undefined?'campus':p.floor;
        const bounds = typeof floor==='string'&&Object.hasOwn(floorBounds,floor)&&floorBounds[floor];
        return p && typeof p.id === 'string' && typeof p.nickname === 'string'
          && (p.floor===undefined||typeof p.floor==='string') && bounds
          && Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= bounds.width && p.y >= 0 && p.y <= bounds.height
          && colors.has(p.color) && directions.has(p.dir) && typeof p.moving === 'boolean'
          && (p.inClassroom === undefined || typeof p.inClassroom === 'boolean')
          && (p.avatar === undefined || avatars.has(p.avatar));
      }
      function upsert(p) {
        if (!validPeer(p) || p.id === selfId) return false;
        p = {...p,floor:p.floor||'campus',avatar:p.avatar||'male-1',inClassroom:p.inClassroom===true};
        const now = performance.now(), peer = peers.get(p.id);
        if (!peer) {
          peers.set(p.id, {...p, targetX: p.x, targetY: p.y, receivedAt: now});
          return true;
        }
        const renamed = peer.nickname !== p.nickname || peer.floor !== p.floor;
        // Room navigation teleports instead of drawing a trip through walls.
        if (peer.floor!==p.floor||Math.hypot(peer.x - p.x, peer.y - p.y) > 180) {peer.x = p.x; peer.y = p.y;}
        Object.assign(peer, {targetX: p.x, targetY: p.y, dir: p.dir, color: p.color,
          moving: p.moving, nickname: p.nickname, avatar:p.avatar, floor:p.floor, inClassroom:p.inClassroom, receivedAt: now});
        return renamed;
      }
      function publish(t, force = false) {
        if (!ready || socket?.readyState !== WebSocket.OPEN || (!force && t - lastSent < 100)) return;
        socket.send(JSON.stringify({type:'input',keys:inputKeys,...(poking?{poking:true,...(force?{pokeContext}: {})}: {})}));
        lastSent=t;
      }
      function setInput(keys) {
        const next=[...new Set(keys)].filter(key=>allowedKeys.has(key)).sort(), encoded=JSON.stringify(next);
        inputKeys=next;
        if(encoded!==lastInput){lastInput=encoded;publish(performance.now(),true);}
      }
      function setPoking(active,scope=null,keys=inputKeys) {
        const next=[...new Set(keys)].filter(key=>allowedKeys.has(key)).sort(), encoded=JSON.stringify(next);
        const value=active===true;
        if(value===poking&&encoded===lastInput&&(!value||JSON.stringify(scope)===JSON.stringify(pokeContext)))return;
        inputKeys=next;lastInput=encoded;poking=value;pokeContext=value?scope:null;
        publish(performance.now(),true);
      }
      function command(action,data={}) {
        if(!ready||socket?.readyState!==WebSocket.OPEN)return Promise.reject(new Error('연결된 뒤 이용해 주세요.'));
        const requestId=String(++sequence);
        return new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{pending.delete(requestId);reject(new Error('서버 응답을 기다리지 못했어요. 다시 시도해 주세요.'));},10000);
          pending.set(requestId,{resolve,reject,timer});
          socket.send(JSON.stringify({type:'control',requestId,action,data}));
        });
      }
      function rejectPending() {
        for(const {reject,timer} of pending.values()){clearTimeout(timer);reject(new Error('연결이 끊겼어요. 다시 연결해 주세요.'));}
        pending.clear();inputKeys=[];lastInput='';poking=false;pokeContext=null;player.moving=false;
      }
      function acceptSelf(p) {
        if(!validPeer(p)||p.id!==selfId)return;
        const floor=p.floor||'campus';
        applyIdentity(p);
        if(player.floor!==floor||!Number.isFinite(player.targetX)||Math.hypot(player.x-p.x,player.y-p.y)>80){player.x=p.x;player.y=p.y;}
        Object.assign(player,{floor,targetX:p.x,targetY:p.y,dir:p.dir,moving:p.moving,inClassroom:p.inClassroom===true,receivedAt:performance.now()});
      }
      function backoff() {
        // 2배씩 늘리되(최대 10초) 사람마다 0.5~1.5배로 흩뜨린다: 여럿이 함께 끊겨도 한순간에 다시 몰리지 않게(계획 6d)
        const delay = retryDelay * (0.5 + Math.random()); retryDelay = Math.min(retryDelay * 2, 10000); return delay;
      }
      function reconnectNow() {
        if(closed)return;
        const previous=socket;socket=null;
        rejectPending();ready=false;peers.clear();roster.replaceChildren();
        clearInterval(heartbeat);clearTimeout(retry);
        previous?.close(4000,'Reconnecting');
        connect();
      }
      function connect() {
        if (closed) return;
        clearTimeout(retry);
        setStatus('연결 중…', 'connecting');
        const url = new URL(config.socketPath, window.location.href);
        url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        url.searchParams.set('control','server');
        socket = new WebSocket(url.href);
        const current = socket;
        current.onmessage = event => {
          if (current !== socket || closed) return;
          let message;
          try {message = JSON.parse(event.data);} catch {return;}
          lastReceived=performance.now();
          if (message.type === 'welcome' && Array.isArray(message.players)) {
            window.CampusSession?.receive(message.session);
            if(message.raffle)onRaffle(message.raffle);
            selfId = message.selfId; peers.clear();
            const own = message.players.find(p => p.id === selfId);
            applyIdentity(own);
            if(message.doors&&typeof message.doors==='object'&&!Array.isArray(message.doors))onDoors(Object.fromEntries(Object.entries(message.doors).filter(([id,open])=>doorIds.has(id)&&typeof open==='boolean')));
            if(validPeer(own)){onRestore(own);acceptSelf(own);}
            for (const p of message.players) upsert(p);
            ready = true; retryDelay = 1000; lastSent = -Infinity; lastInput = ''; authChecked = false;
            updateRoster(); publish(performance.now());
            clearInterval(heartbeat);
            heartbeat = setInterval(() => {
              if(current!==socket||closed||current.readyState!==WebSocket.OPEN)return;
              if(!document.hidden&&performance.now()-lastReceived>10000){reconnectNow();return;}
              current.send(JSON.stringify({type: 'ping'}));
            }, 5000);
          } else if (ready && message.type === 'control_state' && validPeer(message.state?.main)) {
            onState(message.state);acceptSelf(message.state.main);
          } else if (ready && message.type === 'control_event' && message.event) {
            onControlEvent(message.event);
          } else if (ready && message.type === 'jump') {
            onJump(message);
          } else if (ready && ['poke','poke_state','poke_hit'].includes(message.type)) {
            onPoke(message);
          } else if (ready && message.type === 'control_result') {
            const task=pending.get(message.requestId);
            if(task){pending.delete(message.requestId);clearTimeout(task.timer);if(message.error)task.reject(new Error(message.error));else task.resolve(message.result);}
          } else if (ready && message.type === 'control_error' && typeof message.message === 'string') {
            onDoorError(message.message);
          } else if (ready && message.type === 'private_message' && typeof message.conversationId === 'string') {
            window.dispatchEvent(new CustomEvent('campus:private-message',{detail:{conversationId:message.conversationId}}));
          } else if (message.type === 'session_expired') {
            window.CampusSession?.expire(message.reason);
          } else if (ready && message.type === 'identity') {
            applyIdentity(message.player);
          } else if (ready && (message.type === 'join' || message.type === 'move')) {
            if (upsert(message.player)) updateRoster();
          } else if (ready && message.type === 'moves' && Array.isArray(message.players)) {
            // 0.1초마다 묶여 오는 위치. 이미 아는 사람만 갱신한다(떠난 사람이 늦게 온 묶음으로 되살아나지 않게, 새 사람은 join 으로 온다)
            let renamed=false;for(const p of message.players)if(p&&peers.has(p.id))renamed=upsert(p)||renamed;
            if(renamed)updateRoster();
          } else if (ready && message.type === 'leave') {
            if (peers.delete(message.id)) updateRoster();
          } else if (ready && message.type === 'chat') {
            const m = message.message;
            if (m && typeof m.id === 'string' && typeof m.playerId === 'string'
                && typeof m.nickname === 'string' && typeof m.text === 'string'
                && m.text.trim() && Array.from(m.text).length <= 200
                && typeof m.floor === 'string' && Object.hasOwn(floorBounds,m.floor)
                && typeof m.sentAt === 'string' && Number.isFinite(Date.parse(m.sentAt))) onChat(m);
          } else if (ready && message.type === 'door_state' && doorIds.has(message.doorId) && typeof message.open === 'boolean') {
            onDoor({doorId:message.doorId,open:message.open});
          } else if (ready && message.type === 'door_error' && typeof message.message === 'string') {
            onDoorError(message.message);
          } else if (ready && message.type === 'chat_error' && typeof message.message === 'string') {
            onChatError(message.message);
          } else if (ready && message.type === 'raffle_state' && message.state) {
            onRaffle(message.state);
          } else if (ready && message.type === 'raffle_entry' && message.state && typeof message.entryId === 'string') {
            onRaffleEntry(message);
          } else if (ready && message.type === 'raffle_survey' && message.state && typeof message.url === 'string' && typeof message.eventId === 'string') {
            onRaffleSurvey(message);
          } else if (ready && message.type === 'raffle_error' && typeof message.message === 'string') {
            onRaffleError(message.message);
          }
        };
        current.onclose = event => {
          if (current !== socket) return;
          rejectPending();ready = false; peers.clear(); roster.replaceChildren(); clearInterval(heartbeat);
          if (closed) return;
          if(event.code===4409){
            closed=true;setStatus('새 연결로 전환됨 · 이 창에서 계속하려면 새로고침하세요','disconnected');
            return;
          }
          if (event.code === 4401 && window.CampusSession?.verify && !authChecked) {
            // 로그인이 정말 끝났는지 세션 상태로 한 번 확인한다(계획 6c): 끝났으면 CampusSession 이 로그인 화면으로 보내고, 살아 있으면 다시 연결한다.
            // 다시 붙기 전에 또 4401 이면 확인 없이 끝낸다(되풀이하지 않게)
            authChecked = true; setStatus('로그인 상태를 확인하는 중…', 'connecting');
            window.CampusSession.verify().then(alive => {
              if (closed || current !== socket) return;
              if (alive) retry = setTimeout(connect, backoff());
              else {closed = true; setStatus('로그인이 필요해요', 'disconnected'); onAuthExpired();}
            });
            return;
          }
          if (event.code === 4401) {
            closed = true; setStatus('로그인이 필요해요', 'disconnected');
            onAuthExpired();
            if(window.CampusSession)window.CampusSession.expire();else window.location.assign(config.loginUrl);
            return;
          }
          setStatus('연결 끊김 · 다시 연결 중…', 'disconnected');
          retry = setTimeout(connect, backoff());
        };
        // onclose performs recovery; avoid a separate retry for the same failure.
        current.onerror = () => {};
      }
      function applyIdentity(p) {
        if (!validPeer(p) || p.id !== selfId) return;
        const avatar = p.avatar || 'male-1', changed = player.avatar !== avatar || player.nickname !== p.nickname;
        player.avatar = avatar;
        player.nickname = p.nickname;
        if (window.CampusAvatars) player.color = window.CampusAvatars.definitions[player.avatar].color;
        if (changed) window.dispatchEvent?.(new Event('campus:avatar'));  // 아바타·닉네임이 바뀌었을 때만 화면을 다시 그린다(계획 5단계)
      }
      function close() {
        if (closed) return;
        if (ready && socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({type:'input',keys:[]}));
          socket.send(JSON.stringify({type:'leave'}));
        }
        rejectPending();closed = true; ready = false; peers.clear();
        onConnectionChange(false);
        clearTimeout(retry); clearInterval(heartbeat);
        socket?.close(1000);
      }
      window.addEventListener('pagehide', close);
      window.addEventListener('pageshow', event => {
        if (event.persisted) {closed = false; connect();}
      });
      document.getElementById('campusLogoutForm')?.addEventListener('submit', close);
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !closed && (socket?.readyState === WebSocket.CLOSED||performance.now()-lastReceived>10000)) reconnectNow();
      });
      window.addEventListener('online',()=>{
        if(!closed&&(!ready||performance.now()-lastReceived>10000))reconnectNow();
      });
      connect();
      return {
        peers, close, setInput, setPoking, command,
        get connected() {return ready;},
        get selfId() {return selfId;},
        get inputKeys() {return [...inputKeys];},
        joinRaffle(eventId, {resume=false}={}) {
          if(!ready||socket?.readyState!==WebSocket.OPEN||typeof eventId!=='string')return false;
          publish(performance.now(),true);socket.send(JSON.stringify({type:'raffle_enter',eventId}));return true;
        },
        requestDoor(doorId, open) {
          if(!ready||socket?.readyState!==WebSocket.OPEN||!doorIds.has(doorId)||typeof open!=='boolean')return false;
          publish(performance.now(),true);socket.send(JSON.stringify({type:'door',doorId,open}));return true;
        },
        sendChat(text) {
          if (!ready || socket?.readyState !== WebSocket.OPEN || typeof text !== 'string') return false;
          text = text.trim();
          if (!text || Array.from(text).length > 200) return false;
          // Input is forwarded separately; the backend supplies the accepted floor.
          publish(performance.now(), true);
          socket.send(JSON.stringify({type:'chat',text}));
          return true;
        },
        tick(t, dt) {
          if(inputKeys.length||poking)publish(t); // 누르고 있는 동안만 0.1초마다 갱신한다(서버의 키 유효 시간 0.35초). 놓은 순간은 setInput 이 바로 보낸다
          const blend = 1 - Math.exp(-dt * 18);
          for (const peer of [player,...peers.values()]) {
            if(!Number.isFinite(peer.targetX))continue;
            peer.x += (peer.targetX - peer.x) * blend;
            peer.y += (peer.targetY - peer.y) * blend;
            if (t - peer.receivedAt > 300) peer.moving = false;
          }
        },
      };
    },
  };
})();
