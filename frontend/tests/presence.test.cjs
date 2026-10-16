const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function app({authenticated = true, secure = false, floors, restore = false} = {}) {
  const elements = new Map(), sockets = [], timers = new Map(), intervals = new Map(), listeners = new Map();
  let clock = 0, nextTimer = 0, redirected = null, expired = 0;
  const chats = [], chatErrors = [], connectionChanges = [], restores = [], doorSnapshots = [], doorChanges = [], doorErrors = [];
  const raffleStates = [], raffleEntries = [], raffleErrors = [];
  function element(id) {
    if (id === 'campusPresenceConfig' && !authenticated) return null;
    if (!elements.has(id)) elements.set(id, {
      hidden: true, textContent: '', dataset: {}, children: [],
      replaceChildren() {this.children = [];}, append(item) {this.children.push(item);},
      addEventListener(name, callback) {listeners.set(id + ':' + name, callback);},
    });
    return elements.get(id);
  }
  if (authenticated) element('campusPresenceConfig').textContent = JSON.stringify({socketPath: '/ws/campus/', loginUrl: '/accounts/login/'});
  class Socket {
    static OPEN = 1; static CLOSED = 3;
    constructor(url) {this.url = url; this.readyState = 1; this.sent = []; sockets.push(this);}
    send(text) {this.sent.push(JSON.parse(text));}
    close(code = 1000) {this.readyState = 3; this.onclose?.({code});}
    receive(data) {this.onmessage({data: JSON.stringify(data)});}
  }
  const protocol = secure ? 'https:' : 'http:';
  const context = vm.createContext({URL, WebSocket: Socket, performance: {now: () => clock},
    window: {location: {protocol, href: protocol + '//127.0.0.1:8000/', assign(url) {redirected = url;}},
      addEventListener(name, callback) {listeners.set('window:' + name, callback);}},
    document: {getElementById: element, createElement: () => ({textContent: ''}),
      addEventListener(name, callback) {listeners.set('document:' + name, callback);}},
    setTimeout(callback, delay) {const id = ++nextTimer; timers.set(id, {callback, delay}); return id;},
    clearTimeout(id) {timers.delete(id);},
    setInterval(callback, delay) {const id = ++nextTimer; intervals.set(id, {callback, delay}); return id;},
    clearInterval(id) {intervals.delete(id);},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../dist/presence.js'), 'utf8'), context);
  const player = {x: 1262.125, y: 437.875, dir: 'down', color: '#dfa34d', moving: false};
  const presence = context.window.CampusPresence.create({player, width: 1632, height: 820, floors, onAuthExpired() {expired++;},
    onRestore(position) {restores.push(position);if(restore)Object.assign(player,position);},
    onChat(message) {chats.push(message);}, onChatError(message) {chatErrors.push(message);}, onConnectionChange(value) {connectionChanges.push(value);},
    onDoors(states) {doorSnapshots.push(states);}, onDoor(state) {doorChanges.push(state);}, onDoorError(message) {doorErrors.push(message);},
    onRaffle(state) {raffleStates.push(state);}, onRaffleEntry(message) {raffleEntries.push(message);}, onRaffleError(message) {raffleErrors.push(message);}});
  const peer = (changes = {}) => ({id: 'peer', nickname: '조원 이름', avatar: 'female-2', x: 1200, y: 437,
    dir: 'down', color: '#4e9b91', moving: false, ...changes});
  function welcome(socket = sockets.at(-1)) {
    socket.receive({type: 'welcome', selfId: 'self', players: [peer({id: 'self', nickname: '내 이름'}), peer()]});
  }
  return {presence, player, sockets, timers, intervals, listeners, element, peer, welcome, chats, chatErrors, connectionChanges, restores, doorSnapshots, doorChanges, doorErrors, raffleStates, raffleEntries, raffleErrors,
    tick(t, dt = .016) {clock = t; presence.tick(t, dt);},
    get redirected() {return redirected;}, get expired() {return expired;}};
}

const test = require('node:test');
const floors={campus:{width:2448,height:1230,objects:[{id:'door-class1',type:'glass-door'},{id:'door-storage',type:'sliding-door',interactiveDoor:true}]},rooftop:{width:2448,height:1800}};
const plain=value=>JSON.parse(JSON.stringify(value));
test('standalone creates no socket; authenticated connections negotiate server control and WSS',()=>{
 const offline=app({authenticated:false});offline.tick(200);assert.equal(offline.sockets.length,0);
 for(const secure of [false,true]){const f=app({secure});assert.equal(f.sockets[0].url,`${secure?'wss':'ws'}://127.0.0.1:8000/ws/campus/?control=server`);f.presence.close();}
});
test('only allowed keyboard inputs are sent; client coordinates never become movement commands',()=>{
 const f=app({floors});f.welcome();f.presence.setInput(['w','d','d','teleport']);
 assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'input',keys:['d','w']});
 f.player.x=2400;f.tick(200);assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'input',keys:['d','w']});
 f.presence.close();assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'leave'});assert.equal(f.intervals.size,0);
});
test('an idle player sends no input; held keys keep the 0.1s refresh and a release is sent once',()=>{
 const f=app({floors});f.welcome();const inputs=()=>f.sockets[0].sent.filter(packet=>packet.type==='input').length;
 const idle=inputs();for(let t=100;t<=1000;t+=16)f.tick(t);assert.equal(inputs(),idle);
 f.presence.setInput(['w']);const pressed=inputs();for(let t=1016;t<=1500;t+=16)f.tick(t);assert.ok(inputs()-pressed>=4);
 f.presence.setInput([]);assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'input',keys:[]});const released=inputs();
 for(let t=1516;t<=2500;t+=16)f.tick(t);assert.equal(inputs(),released);f.presence.close();
});
test('accepted state supplies self position and interpolates remote walking across both floors',()=>{
 const f=app({floors});f.welcome();assert.equal(f.element('presenceStatus').textContent,'전체 접속 2명');
 f.sockets[0].receive({type:'move',player:f.peer({x:1230.25,moving:true})});f.tick(116);
 assert.ok(f.presence.peers.get('peer').x>1200&&f.presence.peers.get('peer').x<1230.25);
 f.sockets[0].receive({type:'move',player:f.peer({floor:'rooftop',x:2200,y:1700})});
 assert.equal(f.presence.peers.get('peer').x,2200);assert.equal(f.element('presenceStatus').textContent,'전체 접속 2명');
 f.sockets[0].receive({type:'control_state',state:{main:f.peer({id:'self',x:1400,y:600,dir:'right'})}});
 assert.equal(f.player.targetX,1400);assert.equal(f.player.dir,'right');f.presence.close();
});
test('batched moves update known people only, so a late batch cannot bring back someone who left',()=>{
 const f=app({floors});f.welcome();
 f.sockets[0].receive({type:'moves',players:[f.peer({x:1230.25,moving:true}),f.peer({id:'self',x:5}),f.peer({id:'stranger',x:900})]});f.tick(116);
 assert.ok(f.presence.peers.get('peer').x>1200&&f.presence.peers.get('peer').moving);assert.equal(f.presence.peers.has('stranger'),false);
 f.sockets[0].receive({type:'leave',id:'peer'});f.sockets[0].receive({type:'moves',players:[f.peer({x:1240})]});
 assert.equal(f.presence.peers.has('peer'),false);assert.equal(f.element('presenceStatus').textContent,'전체 접속 1명');f.presence.close();
});
test('chat validation, shared door changes and raffle requests stay routed to the server',()=>{
 const f=app({floors});f.welcome();assert.equal(f.presence.sendChat('가'.repeat(201)),false);assert.equal(f.presence.sendChat('   '),false);
 assert.equal(f.presence.sendChat('  안녕  '),true);assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'chat',text:'안녕'});
 const message={id:'m1',playerId:'peer',nickname:'조원',floor:'rooftop',text:'안녕',sentAt:'2026-10-13T01:00:00Z'};
 f.sockets[0].receive({type:'chat',message});f.sockets[0].receive({type:'chat',message:{...message,floor:'unknown'}});assert.equal(f.chats.length,1);
 assert.equal(f.presence.requestDoor('door-storage',true),true);assert.equal(f.presence.requestDoor('invalid',true),false);
 f.sockets[0].receive({type:'door_state',doorId:'door-storage',open:true});assert.equal(f.doorChanges.length,1);
 f.presence.joinRaffle('event-1');assert.deepEqual(plain(f.sockets[0].sent.at(-1)),{type:'raffle_enter',eventId:'event-1'});f.presence.close();
});
test('control results match request IDs and disconnect rejects pending actions',async()=>{
 const f=app({floors});f.welcome();const result=f.presence.command('open_booth',{objectId:'roof-booth-3'});const packet=f.sockets[0].sent.at(-1);
 f.sockets[0].receive({type:'control_result',requestId:packet.requestId,result:{type:'booth_open'}});assert.equal((await result).type,'booth_open');
 const pending=f.presence.command('interact');f.presence.close();await assert.rejects(pending,/연결/);assert.equal(f.timers.size,0);
});
test('unexpected disconnection reconnects once and expired authentication cannot retry',()=>{
 const f=app({floors});f.welcome();f.sockets[0].close(1006);assert.equal(f.timers.size,1);[...f.timers.values()][0].callback();assert.equal(f.sockets.length,2);f.presence.close();
 const expired=app();expired.welcome();expired.sockets[0].close(4401);assert.equal(expired.expired,1);assert.equal(expired.timers.size,0);
});
