/* Game controls use physical keys; text fields keep the active input language. */
(() => {
  'use strict';
  const physicalKeys = Object.freeze({
    KeyW: 'w', KeyA: 'a', KeyS: 's', KeyD: 'd', KeyE: 'e', KeyZ: 'z', Space: ' ',
    ArrowUp: 'arrowup', ArrowDown: 'arrowdown', ArrowLeft: 'arrowleft', ArrowRight: 'arrowright',
  });
  const gameKeys = new Set(Object.values(physicalKeys));
  function key(event) {
    return physicalKeys[event.code] || String(event.key || '').toLowerCase();
  }
  window.CampusKeyboard = Object.freeze({key, isGameKey: event => gameKeys.has(key(event))});
})();
