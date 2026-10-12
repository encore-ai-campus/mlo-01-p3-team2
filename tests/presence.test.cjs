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

const standalone = app({authenticated: false});
standalone.tick(200); assert.equal(standalone.sockets.length, 0); assert.equal(standalone.presence.peers.size, 0);

const live = app(), socket = live.sockets[0];
assert.equal(socket.url, 'ws://127.0.0.1:8000/ws/campus/');
live.welcome();
assert.equal(live.element('presenceStatus').textContent, '전체 접속 2명');
assert.equal(live.element('presencePeers').children[0].textContent, '조원 이름');
assert.equal(live.presence.peers.size, 1); // self is always rendered locally as 나
assert.equal(live.player.avatar, 'female-2');
assert.equal(live.presence.peers.get('peer').avatar, 'female-2');
assert.equal(socket.sent[0].x, 1262.125); assert.equal(socket.sent[0].y, 437.875);
live.player.x += .375; live.player.moving = true;
live.tick(50); assert.equal(socket.sent.length, 1);
live.tick(100); assert.equal(socket.sent.length, 2); assert.equal(socket.sent[1].x, 1262.5);
live.tick(120); live.tick(190); assert.equal(socket.sent.length, 2);
live.player.moving = false; live.tick(200);
assert.equal(socket.sent.length, 3); assert.equal(socket.sent[2].moving, false);
live.tick(400); assert.equal(socket.sent.length, 3); // no redundant idle position writes

socket.receive({type: 'move', player: live.peer({x: 1230.25, moving: true})});
live.tick(416);
const smooth = live.presence.peers.get('peer');
assert(smooth.x > 1200 && smooth.x < 1230.25, 'Remote walking is interpolated');
socket.receive({type: 'move', player: live.peer({x: 365.75, nickname: '변경된 이름'})});
assert.equal(smooth.x, 365.75, 'Room teleport snaps instead of crossing walls');
assert.equal(live.element('presencePeers').children[0].textContent, '변경된 이름');
socket.receive({type: 'move', player: live.peer({avatar: 'male-2'})});
assert.equal(smooth.avatar, 'male-2');
socket.receive({type: 'identity', player: live.peer({id: 'self', avatar: 'male-1'})});
assert.equal(live.player.avatar, 'male-1');
socket.receive({type: 'identity', player: live.peer({id: 'peer', avatar: 'female-1'})});
assert.equal(live.player.avatar, 'male-1', 'Another account cannot change our outfit');
socket.receive({type: 'move', player: live.peer({avatar: 'unknown'})});
assert.equal(smooth.avatar, 'male-2', 'Invalid avatar identifiers are rejected');
socket.receive({type: 'leave', id: 'peer'});
assert.equal(live.presence.peers.size, 0); assert.equal(live.element('presenceStatus').textContent, '전체 접속 1명');

socket.close(1006);
assert.equal(live.intervals.size, 0); assert.equal(live.timers.size, 1);
assert.equal(live.element('presenceStatus').dataset.state, 'disconnected');
[...live.timers.values()][0].callback();
live.welcome(); assert.equal(live.sockets.length, 2); assert.equal(live.presence.peers.size, 1);
live.listeners.get('campusLogoutForm:submit')();
assert.equal(live.sockets[1].sent.at(-1).type,'leave');
assert.equal(JSON.parse(live.element('campusLastPosition').value).x,live.player.x);
assert.equal(live.sockets[1].readyState, 3); assert.equal(live.timers.size, 0); assert.equal(live.intervals.size, 0);

const expired = app(); expired.welcome(); expired.sockets[0].close(4401);
assert.equal(expired.expired, 1); assert.equal(expired.redirected, '/accounts/login/'); assert.equal(expired.timers.size, 0);
const secure = app({secure: true}); assert.equal(secure.sockets[0].url, 'wss://127.0.0.1:8000/ws/campus/'); secure.presence.close();
const floors = app({floors:{campus:{width:2448,height:1230},rooftop:{width:2448,height:1800}}});floors.welcome();
floors.sockets[0].receive({type:'move',player:floors.peer({floor:'rooftop',x:2310,y:1700})});
assert.equal(floors.presence.peers.get('peer').floor,'rooftop');assert.equal(floors.element('presenceStatus').textContent,'전체 접속 2명');
assert.equal(floors.element('presencePeers').children.length,1);
Object.assign(floors.player,{floor:'rooftop',x:2325,y:1565});floors.tick(200);
assert.equal(floors.sockets[0].sent.at(-1).floor,'rooftop');assert.equal(floors.element('presenceStatus').textContent,'전체 접속 2명');
assert.equal(floors.element('presencePeers').children[0].textContent,'조원 이름');
floors.sockets[0].receive({type:'move',player:floors.peer({floor:'rooftop',y:1801})});assert.equal(floors.presence.peers.get('peer').y,1700);
floors.sockets[0].receive({type:'move',player:floors.peer({floor:'campus'})});assert.equal(floors.element('presenceStatus').textContent,'전체 접속 2명');
floors.sockets[0].receive({type:'join',player:floors.peer({id:'third',floor:'rooftop',nickname:'옥상 조원'})});
assert.equal(floors.element('presenceStatus').textContent,'전체 접속 3명');
floors.sockets[0].receive({type:'leave',id:'peer'});assert.equal(floors.element('presenceStatus').textContent,'전체 접속 2명');
floors.sockets[0].receive({type:'leave',id:'third'});assert.equal(floors.element('presenceStatus').textContent,'전체 접속 1명');
floors.presence.close();
const chat = app({floors:{campus:{width:2448,height:1230},rooftop:{width:2448,height:1800}}});
assert.equal(chat.presence.sendChat('연결 전'),false);
chat.welcome();
assert.equal(chat.presence.connected,true);assert.equal(chat.presence.selfId,'self');
chat.tick(101);chat.player.floor='rooftop';chat.player.y=1610;
assert.equal(chat.presence.sendChat('  안녕하세요  '),true);
assert.equal(chat.sockets[0].sent.at(-2).floor,'rooftop','New floor is published before its chat');
assert.equal(chat.sockets[0].sent.at(-1).type,'chat');assert.equal(chat.sockets[0].sent.at(-1).text,'안녕하세요');
assert.equal(chat.presence.sendChat('가'.repeat(201)),false);assert.equal(chat.presence.sendChat('   '),false);
const message={id:'message-1',playerId:'peer',nickname:'조원',floor:'rooftop',text:'안녕',sentAt:'2026-10-08T01:00:00Z'};
chat.sockets[0].receive({type:'chat',message});assert.equal(chat.chats.length,1);
chat.sockets[0].receive({type:'chat',message:{...message,floor:'invalid'}});
chat.sockets[0].receive({type:'chat',message:{...message,text:'가'.repeat(201)}});
chat.sockets[0].receive({type:'chat',message:{...message,sentAt:'not-a-date'}});
assert.equal(chat.chats.length,1);
chat.sockets[0].receive({type:'chat_error',message:'잠시 후 다시 보내 주세요.'});assert.equal(chat.chatErrors.length,1);
chat.presence.close();assert.equal(chat.presence.connected,false);assert.equal(chat.presence.sendChat('연결 후'),false);
const restored=app({restore:true,floors:{campus:{width:2448,height:1230},rooftop:{width:2448,height:1800}}});
const saved=restored.peer({id:'self',floor:'rooftop',x:2100.25,y:1510.75,dir:'right'});
restored.sockets[0].receive({type:'welcome',selfId:'self',players:[saved]});
assert.equal(restored.player.floor,'rooftop');assert.equal(restored.player.x,2100.25);
assert.equal(restored.sockets[0].sent[0].floor,'rooftop');
restored.player.x+=.75;restored.player.dir='left';
restored.sockets[0].close(1006);[...restored.timers.values()][0].callback();
restored.sockets[1].receive({type:'welcome',selfId:'self',players:[saved]});
assert.equal(restored.restores.length,1,'Reconnect must preserve newer local movement');
assert.equal(restored.player.x,2101);
restored.sockets[1].receive({type:'identity',player:{...saved,avatar:'male-1'}});
assert.equal(restored.player.x,2101,'Identity refresh must not teleport the player');
restored.player.x+=.125;
restored.listeners.get('window:pagehide')();
assert.equal(restored.sockets[1].sent.at(-1).type,'leave');
assert.equal(restored.sockets[1].sent.at(-1).x,2101.125,'Closing sends the final frame without waiting 100ms');
assert.equal(restored.sockets[1].sent.at(-1).moving,false);
restored.presence.close();assert.equal(restored.sockets[1].sent.filter(p=>p.type==='leave').length,1);
const doors=app({floors:{campus:{width:2448,height:1230,objects:[{id:'door-class1',type:'glass-door'}]},rooftop:{width:2448,height:1800}}});
assert.equal(doors.presence.requestDoor('door-class1',true),false);
doors.sockets[0].receive({type:'welcome',selfId:'self',players:[doors.peer({id:'self'})],doors:{'door-class1':true,invalid:true}});
assert.deepEqual(JSON.parse(JSON.stringify(doors.doorSnapshots[0])),{'door-class1':true});
assert.equal(doors.presence.requestDoor('door-class1',false),true);
assert.equal(doors.sockets[0].sent.at(-2).type,'move');
assert.deepEqual(doors.sockets[0].sent.at(-1),{type:'door',doorId:'door-class1',open:false});
doors.sockets[0].receive({type:'door_state',doorId:'door-class1',open:false});
doors.sockets[0].receive({type:'door_state',doorId:'invalid',open:true});
doors.sockets[0].receive({type:'door_state',doorId:'door-class1',open:'yes'});
assert.equal(doors.doorChanges.length,1);
doors.sockets[0].receive({type:'door_error',message:'캐릭터가 문에 있어요.'});assert.equal(doors.doorErrors.length,1);
doors.player.floor='rooftop';assert.equal(doors.presence.requestDoor('door-class1',true),false);
doors.presence.close();assert.equal(doors.presence.requestDoor('door-class1',true),false);
const eventLive=app({floors:{campus:{width:2448,height:1230},rooftop:{width:2448,height:1800}}});
const eventSocket=eventLive.sockets[0],eventState={revision:1,event:{id:'raffle-event',status:'open'},participants:[]};
eventSocket.receive({type:'welcome',selfId:'self',players:[eventLive.peer({id:'self'})],raffle:eventState});
assert.equal(eventLive.raffleStates.length,1);
assert.equal(eventLive.presence.joinRaffle('raffle-event'),false,'Entries require the rooftop');
Object.assign(eventLive.player,{floor:'rooftop',x:2170,y:1004});
assert.equal(eventLive.presence.joinRaffle('raffle-event'),true);
assert.equal(eventSocket.sent.at(-2).type,'move');
assert.equal(eventSocket.sent.at(-2).floor,'rooftop');
assert.deepEqual(eventSocket.sent.at(-1),{type:'raffle_enter',eventId:'raffle-event'});
eventSocket.receive({type:'raffle_state',state:{...eventState,revision:2}});
eventSocket.receive({type:'raffle_entry',entryId:'entry-1',created:true,state:eventState});
eventSocket.receive({type:'raffle_error',message:'이미 마감됐어요.'});
assert.equal(eventLive.raffleStates.length,2);assert.equal(eventLive.raffleEntries.length,1);assert.equal(eventLive.raffleErrors.length,1);
Object.assign(eventLive.player,{floor:'campus'});
assert.equal(eventLive.presence.joinRaffle('raffle-event',{resume:true}),true,'An already requested survey can reopen after switching floors');
eventLive.presence.close();assert.equal(eventLive.presence.joinRaffle('raffle-event'),false);
console.log('PASS: standalone preview, nickname roster, movement, chat, doors, rooftop raffle packets, reconnect, logout, expired session, WSS');
