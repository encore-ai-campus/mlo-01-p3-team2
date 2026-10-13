/* Timed chat display, personal settings, and five-second speech bubbles. */
(() => {
  'use strict';
  window.CampusSocial = {
    create({config, onFocus, onSend, getSelfId}) {
      const $ = id => document.getElementById(id);
      const dialog = $('settingsDialog'), frame = $('chatPanel'), input = $('chatInput');
      const log = $('chatMessages'), send = $('chatSend'), status = $('chatStatus');
      const form = $('chatForm'), meta = frame.querySelector('.chat-composer-meta'), open = $('chatOpen');
      const layer = $('speechBubbles'), shell = document.querySelector('.map-shell');
      const preferences = {nicknames:true, chat:true, bubbles:true};
      const controls = {nicknames:$('settingNicknames'), chat:$('settingChat'), bubbles:$('settingBubbles')};
      const storageKey = config.preferencesKey || 'campus-display-v1:preview';
      const bubbles = new Map(), seen = new Set();
      const CHAT_IDLE_MS = 10000, FADE_MS = 400;
      let connected = false, pending = false, pendingTimer = null, editing = false, composing = false;
      let visibleUntil = 0, idleTimer = null, fadeTimer = null;
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
        for (const key of Object.keys(preferences)) if (typeof stored?.[key] === 'boolean') preferences[key] = stored[key];
      } catch { /* Default controls remain usable when browser storage is unavailable. */ }

      function clearDisplayTimers() {
        clearTimeout(idleTimer);clearTimeout(fadeTimer);idleTimer = fadeTimer = null;
      }
      function hideChat() {
        clearDisplayTimers();frame.hidden = true;frame.classList.remove('is-fading');
        shell.dataset.chatVisible = 'false';
      }
      function scheduleHide() {
        clearTimeout(idleTimer);idleTimer = null;
        if (frame.hidden || !preferences.chat || editing || pending) return;
        const remaining = visibleUntil-performance.now();
        if (remaining > 0) {idleTimer = setTimeout(scheduleHide,remaining);return;}
        if (fadeTimer !== null) return;
        frame.classList.add('is-fading');
        const duration = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : FADE_MS;
        fadeTimer = setTimeout(hideChat,duration);
      }
      function revealChat() {
        if (!preferences.chat) return;
        clearDisplayTimers();frame.hidden = false;frame.classList.remove('is-fading');
        shell.dataset.chatVisible = 'true';visibleUntil = performance.now()+CHAT_IDLE_MS;
        scheduleHide();
      }
      function leaveEditor({focusMap = true} = {}) {
        editing = false;shell.dataset.chatEditing = 'false';open.setAttribute('aria-expanded','false');
        if (frame.contains(document.activeElement)) document.activeElement.blur();
        form.hidden = true;meta.hidden = true;onFocus();scheduleHide();
        if (focusMap) $('mapCanvas').focus({preventScroll:true});
      }
      function focusChat() {
        if (!preferences.chat || !connected) return false;
        editing = true;shell.dataset.chatEditing = 'true';open.setAttribute('aria-expanded','true');
        revealChat();form.hidden = false;meta.hidden = false;onFocus();input.focus({preventScroll:true});
        log.scrollTop = log.scrollHeight;return true;
      }
      hideChat();form.hidden = true;meta.hidden = true;shell.dataset.chatEditing = 'false';
      function applyPreferences() {
        for (const [key, control] of Object.entries(controls)) {
          control.checked = preferences[key];
          control.closest('label').querySelector('.setting-state').textContent = preferences[key] ? '켬' : '끔';
        }
        open.disabled = !preferences.chat || !connected;
        if (!preferences.chat) {leaveEditor({focusMap:false});hideChat();}
        else scheduleHide();
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
      frame.addEventListener('focusout', event => {
        if (editing && !frame.contains(event.relatedTarget)) leaveEditor({focusMap:false});
      });
      frame.addEventListener('keydown', event => {
        if (event.key === 'Escape' && editing) {event.preventDefault();event.stopPropagation();leaveEditor();}
      });
      input.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || composing || event.isComposing || event.keyCode === 229) return;
        event.preventDefault();event.stopPropagation();
        if (event.repeat || pending) return;
        if (!input.value.trim()) {leaveEditor();return;}
        form.requestSubmit();
      });
      function countInput() {
        const letters = Array.from(input.value);
        if (letters.length > 200) input.value = letters.slice(0,200).join('');
        $('chatCount').textContent = `${Math.min(letters.length,200)}/200`;
      }
      input.addEventListener('input', event => {if (!event.isComposing) countInput();});
      input.addEventListener('compositionstart', () => {composing = true;});
      input.addEventListener('compositionend', () => {composing = false;countInput();});
      function finishPending() {
        pending = false;clearTimeout(pendingTimer);pendingTimer = null;
        input.readOnly = false;send.disabled = !connected;
      }
      function reportError(message) {
        const wasPending = pending;finishPending();status.textContent = message;status.dataset.state = 'error';
        if (wasPending && connected && preferences.chat) focusChat();
        else {revealChat();meta.hidden = !preferences.chat;scheduleHide();}
      }
      function setConnected(value) {
        connected = value;input.disabled = !value;send.disabled = !value || pending;
        open.disabled = !value || !preferences.chat;
        status.dataset.state = value ? 'ready' : 'waiting';
        status.textContent = value ? 'Enter로 채팅 · Esc로 이동' : (config.socketPath ? '연결 중에는 메시지를 보낼 수 없어요.' : '로그인 후 채팅을 사용할 수 있어요.');
        if (!value) {
          finishPending();
          if (editing) leaveEditor();
          else scheduleHide();
          for (const bubble of bubbles.values()) bubble.element.remove();
          bubbles.clear();
        }
      }
      setConnected(false);
      form.addEventListener('submit', event => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || !connected || pending || composing) return;
        if (!onSend(text)) {reportError('연결을 확인한 후 다시 보내 주세요.');return;}
        pending = true;input.readOnly = true;send.disabled = true;
        clearDisplayTimers();
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
        if (self && pending) {
          const returnToMap = editing;finishPending();input.value = '';countInput();
          status.textContent = 'Enter로 채팅 · Esc로 이동';status.dataset.state = 'ready';
          if (returnToMap) leaveEditor();
        }
        revealChat();
        if (follow) log.scrollTop = log.scrollHeight;
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
        get isTyping() {return editing;},
        focusChat,
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
