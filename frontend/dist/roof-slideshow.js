/* 광고 모듈 대신 기존 화면 호출 지점에 연결하는 옥상 사진 순환 표시기. */
(() => {
  'use strict';
  const config = window.CampusRoofSlideshowConfig || {};
  const base = new URL(document.currentScript?.src || document.baseURI);
  const interval = Number.isFinite(config.intervalMs) && config.intervalMs >= 1000 ? config.intervalMs : 10000;
  const urls = [];
  for (const value of Array.isArray(config.images) ? config.images : []) {
    try {
      if (typeof value !== 'string' || !value.trim()) continue;
      const url = new URL(value, base);
      if (url.origin === base.origin && ['http:', 'https:'].includes(url.protocol) && !urls.includes(url.href)) urls.push(url.href);
    } catch { /* 잘못된 목록 항목은 건너뛰고 나머지 사진을 표시한다. */ }
  }
  const applied = new WeakMap(), retryAfter = new Map();
  let current = -1, currentImage = null, cursor = 0, due = 0, pending = false, prepared = null;

  function load(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      let finished = false;
      const timer = setTimeout(() => finish(false), 8000);
      function finish(ok) {
        if (finished) return;
        finished = true; clearTimeout(timer); image.onload = image.onerror = null;
        if (ok) resolve(image); else reject(new Error('roof_image_unavailable'));
      }
      image.onload = () => {
        // 이미지 디코딩까지 끝난 후보만 넘겨 화면 교체 중 빈 프레임을 피한다.
        if (typeof image.decode === 'function') image.decode().then(() => finish(true), () => finish(false));
        else finish(true);
      };
      image.onerror = () => finish(false);
      image.src = url;
    });
  }

  function prepareNext(now) {
    if (pending || prepared || !urls.length || (urls.length === 1 && current === 0)) return;
    for (let count = 0; count < urls.length; count++) {
      const index = (cursor + count) % urls.length;
      if (index === current || (retryAfter.get(index) || 0) > now) continue;
      pending = true;
      load(urls[index]).then(image => {
        prepared = { index, image }; retryAfter.delete(index);
      }, () => {
        // 실패한 사진 때문에 현재 사진을 지우지 않고 다음 항목을 시도한다.
        retryAfter.set(index, performance.now() + 5000); cursor = (index + 1) % urls.length;
      }).finally(() => { pending = false; });
      return;
    }
  }

  function tick({ now, floor, renderer }) {
    if (floor !== 'rooftop' || document.hidden || !renderer) return;
    if (currentImage && applied.get(renderer) !== currentImage) {
      if (renderer.setDisplayImage('roof-ad-board', currentImage)) applied.set(renderer, currentImage);
    }
    if (prepared && (current < 0 || now >= due)) {
      if (renderer.setDisplayImage('roof-ad-board', prepared.image)) {
        current = prepared.index; currentImage = prepared.image; applied.set(renderer, currentImage);
        prepared = null; due = now + interval; cursor = (current + 1) % urls.length;
      }
    }
    // 현재 사진과 다음 후보만 유지한다. 층 이동 중에도 기존 사진을 보존한다.
    prepareNext(now);
  }

  let portalCursor = 0, portalVersion = 0;
  const portalImages = new Map();
  const pair = () => Array.from({ length: Math.min(2, urls.length) }, (_, i) => urls[(portalCursor + i) % urls.length]);

  function warmPortal(url) {
    if (!portalImages.has(url)) {
      const promise = load(url).catch(() => null).then(image => {
        if (!image && portalImages.get(url) === promise) portalImages.delete(url);
        return image;
      });
      portalImages.set(url, promise);
    }
    return portalImages.get(url);
  }

  function preparePortal() {
    const next = pair();
    // 다음 이동에 필요한 두 장만 미리 준비한다. 옥상 순환 상태는 변경하지 않는다.
    for (const url of portalImages.keys()) if (!next.includes(url)) portalImages.delete(url);
    for (const url of next) warmPortal(url);
  }

  function stopPortal() {
    portalVersion++;
    const slot = document.getElementById('floorTransitionAdSlot');
    if (slot) { slot.replaceChildren(); slot.hidden = true; }
    preparePortal();
  }

  async function startPortal() {
    const version = ++portalVersion;
    const slot = document.getElementById('floorTransitionAdSlot');
    const dialog = document.getElementById('floorTransitionDialog');
    if (!slot || !dialog?.open || !urls.length) return;
    slot.replaceChildren(); slot.hidden = true;
    const selected = pair();
    preparePortal();
    portalCursor = (portalCursor + selected.length) % urls.length;
    await Promise.all(selected.map(async (url, index) => {
      const image = await warmPortal(url);
      // 이동 화면이 닫혔거나 다음 이동이 시작되면 늦게 도착한 사진을 버린다.
      if (!image || version !== portalVersion || !dialog.open) return;
      const panel = document.createElement('div');
      panel.className = 'portal-ad portal-ad-' + index;
      image.alt = '캠퍼스 안내 사진'; image.draggable = false;
      panel.append(image); slot.append(panel); slot.hidden = false;
    }));
  }

  window.addEventListener('campus:ready', preparePortal);
  window.addEventListener('campus:floor-transition-end', stopPortal);
  // 기존 게임 호출만 연결하며 광고 서버 요청·노출 보고·클릭 이동은 실행하지 않는다.
  window.CampusAds = { tick, startPortal, stopPortal, clickRoof() { return false; } };
})();
