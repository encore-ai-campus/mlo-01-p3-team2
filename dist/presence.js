/* Shared avatars; movement stays in world coordinates, independent of zoom. */
(() => {
  'use strict';
  window.CampusPresence = {
    create({player, width, height, floors, onAuthExpired, onRestore = () => {}, onChat = () => {}, onChatError = () => {}, onConnectionChange = () => {}, onDoors = () => {}, onDoor = () => {}, onDoorError = () => {}}) {
      const configElement = document.getElementById('campusPresenceConfig');
      const status = document.getElementById('presenceStatus');
      const roster = document.getElementById('presencePeers');
      const peers = new Map();
      if (!configElement) return {peers, connected:false, selfId:null, sendChat(){return false;}, requestDoor(){return false;}, tick() {}, close() {}};
      const config = JSON.parse(configElement.textContent);
      let socket = null, selfId = null, ready = false, closed = false;
      let welcomed = false;
      let retry = null, retryDelay = 1000, heartbeat = null, lastSent = -Infinity, lastState = '';
      const floorBounds = floors || {campus:{width,height}};
      const doorIds = new Set((floors?.campus?.objects||[]).filter(o=>o.type==='glass-door').map(o=>o.id));
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
          && (p.avatar === undefined || avatars.has(p.avatar));
      }
      function upsert(p) {
        if (!validPeer(p) || p.id === selfId) return false;
        p = {...p,floor:p.floor||'campus',avatar:p.avatar||'male-1'};
        const now = performance.now(), peer = peers.get(p.id);
        if (!peer) {
          peers.set(p.id, {...p, targetX: p.x, targetY: p.y, receivedAt: now});
          return true;
        }
        const renamed = peer.nickname !== p.nickname || peer.floor !== p.floor;
        // Room navigation teleports instead of drawing a trip through walls.
        if (peer.floor!==p.floor||Math.hypot(peer.x - p.x, peer.y - p.y) > 180) {peer.x = p.x; peer.y = p.y;}
        Object.assign(peer, {targetX: p.x, targetY: p.y, dir: p.dir, color: p.color,
          moving: p.moving, nickname: p.nickname, avatar:p.avatar, floor:p.floor, receivedAt: now});
        return renamed;
      }
      function publish(t, force = false) {
        if (!ready || socket?.readyState !== WebSocket.OPEN || (!force && t - lastSent < 100)) return;
        const state = {type: 'move', floor:player.floor||'campus', x: player.x, y: player.y, dir: player.dir,
          color: player.color, moving: player.moving};
        const encoded = JSON.stringify(state);
        if (encoded === lastState) return;
        socket.send(encoded); lastSent = t; lastState = encoded;
      }
      function connect() {
        if (closed) return;
        clearTimeout(retry);
        setStatus('연결 중…', 'connecting');
        const url = new URL(config.socketPath, window.location.href);
        url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(url.href);
        const current = socket;
        current.onmessage = event => {
          if (current !== socket || closed) return;
          let message;
          try {message = JSON.parse(event.data);} catch {return;}
          if (message.type === 'welcome' && Array.isArray(message.players)) {
            selfId = message.selfId; peers.clear();
            const own = message.players.find(p => p.id === selfId);
            applyIdentity(own);
            if(message.doors&&typeof message.doors==='object'&&!Array.isArray(message.doors))onDoors(Object.fromEntries(Object.entries(message.doors).filter(([id,open])=>doorIds.has(id)&&typeof open==='boolean')));
            if (!welcomed && validPeer(own)) {
              onRestore({floor:own.floor||'campus',x:own.x,y:own.y,dir:own.dir});
              welcomed = true;
            }
            for (const p of message.players) upsert(p);
            ready = true; retryDelay = 1000; lastSent = -Infinity; lastState = '';
            updateRoster(); publish(performance.now());
            clearInterval(heartbeat);
            heartbeat = setInterval(() => {
              if (current.readyState === WebSocket.OPEN) current.send(JSON.stringify({type: 'ping'}));
            }, 15000);
          } else if (ready && message.type === 'identity') {
            applyIdentity(message.player);
          } else if (ready && (message.type === 'join' || message.type === 'move')) {
            if (upsert(message.player)) updateRoster();
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
          }
        };
        current.onclose = event => {
          if (current !== socket) return;
          ready = false; peers.clear(); roster.replaceChildren(); clearInterval(heartbeat);
          if (closed) return;
          if (event.code === 4401) {
            closed = true; setStatus('로그인이 필요해요', 'disconnected');
            onAuthExpired(); window.location.assign(config.loginUrl); return;
          }
          setStatus('연결 끊김 · 다시 연결 중…', 'disconnected');
          retry = setTimeout(connect, retryDelay); retryDelay = Math.min(retryDelay * 2, 10000);
        };
        // onclose performs recovery; avoid a separate retry for the same failure.
        current.onerror = () => {};
      }
      function applyIdentity(p) {
        if (!validPeer(p) || p.id !== selfId) return;
        player.avatar = p.avatar || 'male-1';
        player.nickname = p.nickname;
        if (window.CampusAvatars) player.color = window.CampusAvatars.definitions[player.avatar].color;
        window.dispatchEvent?.(new Event('campus:avatar'));
      }
      function close() {
        if (closed) return;
        if (ready && socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({type:'leave',floor:player.floor||'campus',x:player.x,y:player.y,
            dir:player.dir,color:player.color,moving:false}));
        }
        closed = true; ready = false; peers.clear();
        onConnectionChange(false);
        clearTimeout(retry); clearInterval(heartbeat);
        socket?.close(1000);
      }
      window.addEventListener('pagehide', close);
      window.addEventListener('pageshow', event => {
        if (event.persisted) {closed = false; connect();}
      });
      document.getElementById('campusLogoutForm')?.addEventListener('submit', () => {
        const input = document.getElementById('campusLastPosition');
        if (input) input.value = JSON.stringify({floor:player.floor||'campus',x:player.x,y:player.y,dir:player.dir});
        close();
      });
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !closed && socket?.readyState === WebSocket.CLOSED) connect();
      });
      connect();
      return {
        peers, close,
        get connected() {return ready;},
        get selfId() {return selfId;},
        requestDoor(doorId, open) {
          if(!ready||socket?.readyState!==WebSocket.OPEN||(player.floor||'campus')!=='campus'||!doorIds.has(doorId)||typeof open!=='boolean')return false;
          publish(performance.now(),true);socket.send(JSON.stringify({type:'door',doorId,open}));return true;
        },
        sendChat(text) {
          if (!ready || socket?.readyState !== WebSocket.OPEN || typeof text !== 'string') return false;
          text = text.trim();
          if (!text || Array.from(text).length > 200) return false;
          // Publish the current floor before chat, including immediately after a portal.
          publish(performance.now(), true);
          socket.send(JSON.stringify({type:'chat',text}));
          return true;
        },
        tick(t, dt) {
          publish(t);
          const blend = 1 - Math.exp(-dt * 18);
          for (const peer of peers.values()) {
            peer.x += (peer.targetX - peer.x) * blend;
            peer.y += (peer.targetY - peer.y) * blend;
            if (t - peer.receivedAt > 300) peer.moving = false;
          }
        },
      };
    },
  };
})();
