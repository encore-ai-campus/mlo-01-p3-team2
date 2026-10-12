/* Personal display settings, live chat, and five-second speech bubbles. */
(() => {
  'use strict';
  window.CampusSocial = {
    create({config, onFocus, onSend, getSelfId}) {
      const $ = id => document.getElementById(id);
      const dialog = $('settingsDialog'), frame = $('chatPanel'), input = $('chatInput');
      const log = $('chatMessages'), send = $('chatSend'), status = $('chatStatus');
      const layer = $('speechBubbles'), shell = document.querySelector('.map-shell');
      const preferences = {nicknames:true, chat:true, bubbles:true};
      const controls = {nicknames:$('settingNicknames'), chat:$('settingChat'), bubbles:$('settingBubbles')};
      const storageKey = config.preferencesKey || 'campus-display-v1:preview';
      const bubbles = new Map(), seen = new Set();
      let connected = false, pending = false, pendingTimer = null;
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
        for (const key of Object.keys(preferences)) if (typeof stored?.[key] === 'boolean') preferences[key] = stored[key];
      } catch { /* Default controls remain usable when browser storage is unavailable. */ }

      function applyPreferences() {
        for (const [key, control] of Object.entries(controls)) {
          control.checked = preferences[key];
          control.closest('label').querySelector('.setting-state').textContent = preferences[key] ? '켬' : '끔';
        }
        frame.hidden = !preferences.chat;
        shell.dataset.chatVisible = String(preferences.chat);
        if (!preferences.chat && document.activeElement === input) {input.blur();onFocus();}
        if (!preferences.bubbles) for (const bubble of bubbles.values()) bubble.element.hidden = true;
        if (preferences.chat) log.scrollTop = log.scrollHeight;
      }
      for (const [key, control] of Object.entries(controls)) control.addEventListener('change', () => {
        preferences[key] = control.checked;
        try {localStorage.setItem(storageKey, JSON.stringify(preferences));} catch {}
        applyPreferences();
      });
      applyPreferences();
      $('settingsAccount').hidden = !$('settingsAccount').childElementCount;
      function openSettings() {
        if (dialog.open) return;
        onFocus();dialog.showModal();$('closeSettings').focus();
      }
      $('settingsBtn').addEventListener('click', openSettings);
      $('closeSettings').addEventListener('click', () => dialog.close());
      dialog.addEventListener('close', () => {onFocus();$('mapCanvas').focus({preventScroll:true});});
      dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const r = dialog.getBoundingClientRect();
        if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
      });
      input.addEventListener('focus', onFocus);
      input.addEventListener('keydown', event => {
        if (event.key === 'Escape') {event.preventDefault();event.stopPropagation();input.blur();onFocus();$('mapCanvas').focus({preventScroll:true});}
      });
      function countInput() {
        const letters = Array.from(input.value);
        if (letters.length > 200) input.value = letters.slice(0,200).join('');
        $('chatCount').textContent = `${Math.min(letters.length,200)}/200`;
      }
      input.addEventListener('input', event => {if (!event.isComposing) countInput();});
      input.addEventListener('compositionend', countInput);
      function finishPending() {
        pending = false;clearTimeout(pendingTimer);pendingTimer = null;
        input.readOnly = false;send.disabled = !connected;
      }
      function reportError(message) {finishPending();status.textContent = message;status.dataset.state = 'error';}
      function setConnected(value) {
        connected = value;input.disabled = !value;send.disabled = !value || pending;
        status.dataset.state = value ? 'ready' : 'waiting';
        status.textContent = value ? 'Enter로 채팅 · Esc로 이동' : (config.socketPath ? '연결 중에는 메시지를 보낼 수 없어요.' : '로그인 후 채팅을 사용할 수 있어요.');
        if (!value) {
          finishPending();
          for (const bubble of bubbles.values()) bubble.element.remove();
          bubbles.clear();
        }
      }
      setConnected(false);
      $('chatForm').addEventListener('submit', event => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || !connected || pending) return;
        if (!onSend(text)) {reportError('연결을 확인한 후 다시 보내 주세요.');return;}
        pending = true;input.readOnly = true;send.disabled = true;
        status.textContent = '보내는 중…';status.dataset.state = 'waiting';
        pendingTimer = setTimeout(() => reportError('전송을 확인하지 못했어요. 연결 후 다시 보내 주세요.'),5000);
      });
      function receive(message) {
        if (seen.has(message.id)) return;
        seen.add(message.id);
        const self = message.playerId === getSelfId();
        const follow = self || log.scrollHeight - log.scrollTop - log.clientHeight < 30;
        const entry = document.createElement('li');entry.className = 'chat-message';entry.dataset.messageId = message.id;entry.dataset.self = String(self);
        const heading = document.createElement('div');heading.className = 'chat-message-heading';
        const name = document.createElement('strong');name.textContent = self ? `${message.nickname} (나)` : message.nickname;
        const floor = document.createElement('span');floor.className = 'chat-floor';floor.textContent = message.floor === 'rooftop' ? '옥상' : '18F';
        const time = document.createElement('time');time.dateTime = message.sentAt;time.textContent = new Intl.DateTimeFormat('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(message.sentAt));
        const text = document.createElement('p');text.textContent = message.text;
        heading.append(name,floor,time);entry.append(heading,text);log.append(entry);
        while (log.children.length > 100) {seen.delete(log.firstElementChild.dataset.messageId);log.firstElementChild.remove();}
        $('chatEmpty').hidden = true;
        if (follow) log.scrollTop = log.scrollHeight;
        if (self && pending) {finishPending();input.value = '';countInput();status.textContent = 'Enter로 채팅 · Esc로 이동';status.dataset.state = 'ready';}
        let bubble = bubbles.get(message.playerId);
        if (!bubble) {
          const element = document.createElement('div');element.className = 'speech-bubble';element.dataset.playerId = message.playerId;layer.append(element);
          bubble = {element};bubbles.set(message.playerId,bubble);
        }
        Object.assign(bubble,{floor:message.floor,expiresAt:performance.now()+5000});
        bubble.element.textContent = message.text;bubble.element.dataset.self = String(self);bubble.element.hidden = true;
      }
      return {
        preferences, receive, setConnected, reportError, openSettings,
        get isTyping() {return document.activeElement === input;},
        focusChat() {if (!preferences.chat || !connected) return false;onFocus();input.focus({preventScroll:true});return true;},
        render(t,{actors,camera,projectActor,selfId,floor,avatarSize}) {
          for (const [id,bubble] of bubbles) {
            if (t >= bubble.expiresAt) {bubble.element.remove();bubbles.delete(id);continue;}
            const actor = id === selfId ? actors[0] : actors.find(a => a.id === id);
            bubble.element.hidden = !preferences.bubbles || bubble.floor !== floor || !actor;
            if (bubble.element.hidden) continue;
            const q = projectActor(actor), nameSpace = actor === actors[0] || preferences.nicknames ? 24*camera.zoom/Math.max(camera.zoom,.55) : 7;
            bubble.element.style.left = `${q.x*camera.zoom+camera.x}px`;
            bubble.element.style.top = `${q.y*camera.zoom+camera.y-avatarSize*camera.zoom-nameSpace}px`;
          }
        },
      };
    },
  };
})();
