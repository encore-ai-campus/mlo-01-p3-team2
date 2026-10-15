const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
function surface() {
  const handlers = new Map();
  return {hidden:false, open:true, disabled:false,
    addEventListener(type, fn) {if (!handlers.has(type)) handlers.set(type, []);handlers.get(type).push(fn);},
    emit(type, event) {for (const fn of handlers.get(type) || []) {fn(event);if (event.stopped) break;}},
    getContext() {return {};}, setAttribute() {}, focus() {},
  };
}
function environment() {
  const document = surface(), window = surface(), button = surface();
  const elements = new Map([['campusPokeButton', button]]);
  document.getElementById = id => {
    if (!elements.has(id)) elements.set(id, surface());
    return elements.get(id);
  };
  window.matchMedia = () => ({matches:false});
  const sandbox = {document,window,performance:{now:()=>100},setTimeout,clearTimeout,setInterval,clearInterval,console};
  const context = vm.createContext(sandbox);
  vm.runInContext(read('dist/keyboard.js'), context);
  return {context,document,window,button,elements};
}
function keyEvent(key, code, extra={}) {
  return {key,code,repeat:false,isComposing:false,ctrlKey:false,altKey:false,metaKey:false,
    target:{closest:()=>null},preventDefault(){this.prevented=true;},
    stopImmediatePropagation(){this.stopped=true;},...extra};
}
const languages = [
  ['English', 'z', false], ['Korean', 'ㅋ', false], ['IME', 'Process', true], ['Shift', 'Z', false],
];
for (const [label, character, composing] of languages) {
  const env = environment(), player={x:100,y:100,floor:'campus',dir:'right'}, calls=[];
  const presence={connected:true,peers:new Map(),setPoking:active=>calls.push(active)};
  env.context.player=player;env.context.presence=presence;
  vm.runInContext(read('dist/poke.js'), env.context);
  const poke=env.window.CampusPoke.create({getPlayer:()=>player,getPresence:()=>presence,
    getClassroom:()=>({blocking:false}),isBlocked:()=>false});
  Object.assign(env.context,{poke,keys:new Set(),suppressedKeys:new Set(),
    movementKeys:new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright']),
    floorTransition:{blocking:false},isDialogOpen:()=>false,social:{openSettings(){},focusChat(){}},
    nearby:null,zoomBy(){},showDetail(){}});
  const campus = read('dist/campus.js');
  const start=campus.indexOf("document.addEventListener('keydown',e=>{");
  const end=campus.indexOf("window.addEventListener('blur'",start);
  assert.ok(start>=0&&end>start);
  vm.runInContext(campus.slice(start,end), env.context);
  env.document.emit('keydown',keyEvent(character,'KeyZ',{isComposing:composing}));
  assert.equal(poke.held,true, `${label}: main map starts poke`);
  env.document.emit('keyup',keyEvent('ㅋ','KeyZ'));
  assert.equal(poke.held,false, `${label}: release across language switch`);
  assert.deepEqual(calls,[true,false]);
  for (const modifier of ['ctrlKey','altKey','metaKey']) {
    env.document.emit('keydown',keyEvent(character,'KeyZ',{[modifier]:true}));
    assert.equal(poke.held,false,`${label}: preserves ${modifier} shortcut`);
  }
  env.document.emit('keydown',keyEvent(character,'KeyZ',{target:{closest:()=>({tagName:'INPUT'})}}));
  assert.equal(poke.held,false,`${label}: typing never triggers poke`);
  env.document.emit('keydown',keyEvent('ㅈ','KeyW',{isComposing:composing}));
  assert.equal(env.context.keys.has('w'),true,`${label}: physical movement key`);
  env.document.emit('keyup',keyEvent('w','KeyW'));
  assert.equal(env.context.keys.size,0);
  env.button.emit('keydown',keyEvent(character,'KeyZ',{isComposing:composing}));
  assert.equal(poke.held,true,`${label}: focused poke button`);
  env.document.emit('keyup',keyEvent(character,'KeyZ'));
  assert.equal(poke.held,false);
  console.log(`PASS map, movement, release, shortcuts, editable field, button: ${label}`);
}
for (const [label,character,composing] of languages) {
  const env=environment();let pokes=0;
  vm.runInContext(read('learning/static/learning/classroom.js'),env.context);
  const classroom=env.window.CampusClassroom.create({getPlayer:()=>({}),
    getControl:()=>({setInput(){},command:async()=>({})}),onPoke:()=>pokes++});
  env.document.emit('keydown',keyEvent(character,'KeyZ',{isComposing:composing}));
  assert.equal(pokes,1,`${label}: classroom poke`);
  env.document.emit('keydown',keyEvent('Process','KeyW',{isComposing:true}));
  assert.equal(classroom.inputKeys.includes('w'),true);
  env.document.emit('keyup',keyEvent('ㅈ','KeyW'));
  assert.equal(classroom.inputKeys.length,0);
  env.document.emit('keydown',keyEvent(character,'KeyZ',{metaKey:true}));
  env.document.emit('keydown',keyEvent(character,'KeyZ',{target:{closest:()=>({tagName:'TEXTAREA'})}}));
  assert.equal(pokes,1,`${label}: preserves shortcuts and text entry`);
  console.log(`PASS classroom poke, movement, release, text entry: ${label}`);
}
assert.ok(read('dist/index.html').indexOf('src="keyboard.js"') < read('dist/index.html').indexOf('src="poke.js"'));
console.log('PASS shared keyboard helper loads before controls');
