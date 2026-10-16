// 소켓이 붙어 있으면 소켓이 알려 주므로 15초 HTTP 조회를 하지 않는다(계획 docs/metaverse-optimization-plan.md 4g).
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');

const flush = () => new Promise(resolve => setImmediate(resolve));

// 어떤 속성이든 받아 주는 가짜 요소: 화면 코드는 그대로 두고 조회 타이머만 본다
function element(fields = {}) {
  const target = {dataset: {}, style: {}, children: [], textContent: '', value: '',
    classList: {add() {}, remove() {}, toggle() {}, contains() {return false;}}, ...fields};
  return new Proxy(target, {
    get(t, key) {
      if (key in t) return t[key];
      if (typeof key !== 'string' || /^(on|hidden|disabled|open|checked|parentElement|title|id|href|src)/.test(key)) return undefined;
      return () => element();
    },
    set(t, key, value) {t[key] = value; return true;},
  });
}

function load(file, {elements = {}, body = () => ({})} = {}) {
  const intervals = [], fetched = [], ids = new Map(Object.entries(elements));
  const document = {getElementById(id) {if (!ids.has(id)) ids.set(id, element()); return ids.get(id);},
    createElement: () => element(), body: element(), cookie: '', hidden: false,
    addEventListener() {}, querySelectorAll: () => [], querySelector: () => null};
  const window = {addEventListener() {}, confirm: () => false};
  const context = vm.createContext({window, document, location: {href: 'http://127.0.0.1/', replace() {}}, URL, AbortController, crypto: globalThis.crypto,
    setTimeout: () => 0, clearTimeout() {}, setInterval(callback, delay) {intervals.push({callback, delay}); return intervals.length;}, clearInterval() {},
    requestAnimationFrame: () => 0, cancelAnimationFrame() {},
    fetch(url) {fetched.push(String(url)); return Promise.resolve({ok: true, status: 200, json: async () => body(String(url))});}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../dist', file), 'utf8'), context);
  return {window, fetched, every: delay => intervals.find(item => item.delay === delay).callback};
}

test('raffle state is not polled while the socket delivers it', async () => {
  const app = load('raffle.js');
  const ui = app.window.CampusRaffle.create();
  await flush();
  const poll = app.every(15000), before = app.fetched.length;
  poll(); await flush();
  assert.equal(app.fetched.length, before + 1);  // 끊겨 있으면 조회한다
  ui.setConnected(true);
  poll(); await flush();
  assert.equal(app.fetched.length, before + 1);  // 붙어 있으면 소켓(welcome·raffle_state)이 알려 준다
});

test('private message status is not polled while connected unless the inbox is open', async () => {
  const app = load('messages.js', {body: () => ({unread: 0, canStart: true, hasInbox: false})});
  app.window.CampusMessages.create({config: {enabled: true}});
  await flush(); await flush();
  const poll = app.every(15000), before = app.fetched.length;
  app.window.CampusApp = {presence: {connected: true}};
  await poll(); await flush();
  assert.equal(app.fetched.length, before);  // 새 쪽지는 소켓(private_message)이 알려 준다
  app.window.CampusApp.presence.connected = false;
  await poll(); await flush();
  assert.equal(app.fetched.length, before + 1);
});

test('session status is not polled while connected, and a coming warning is checked once first', async () => {
  const now = Date.now(), hour = 3600e3;
  const status = {authenticated: true, reason: null, serverNow: now, absoluteExpiresAt: now + hour, idleExpiresAt: now + hour, expiresAt: now + hour, warningSeconds: 60};
  const config = element({textContent: JSON.stringify({statusUrl: '/s/', activityUrl: '/a/', logoutUrl: '/o/', loginUrl: '/l/', csrfToken: 'x',
    activityIntervalSeconds: 15, status})});
  const app = load('session-policy.js', {elements: {campusSessionPolicyConfig: config}, body: () => status});
  await flush();
  const poll = app.every(15000), render = app.every(1000), before = app.fetched.length;
  app.window.CampusApp = {presence: {connected: true}};
  poll(); await flush();
  assert.equal(app.fetched.length, before);  // 만료·교체는 소켓이 바로 알린다
  app.window.CampusApp.presence.connected = false;
  poll(); await flush();
  assert.equal(app.fetched.length, before + 1);
  app.window.CampusApp.presence.connected = true;
  const soon = Date.now() + 30e3;
  app.window.CampusSession.receive({...status, serverNow: Date.now(), expiresAt: soon, idleExpiresAt: soon});  // 다른 탭의 활동을 모르는 상태
  await flush();
  assert.equal(app.fetched.length, before + 2);  // 경고를 띄우기 전에 한 번 확인한다
  render(); await flush();
  assert.equal(app.fetched.length, before + 2);  // 확인한 마감은 다시 묻지 않는다
});
