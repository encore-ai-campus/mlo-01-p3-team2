/* Four-direction sprite sheets: four walking frames and a separate profile idle. */
(() => {
  'use strict';
  const definitions = {
    'male-1': {name: '민트 후드', color: '#4e9b91'},
    'male-2': {name: '보라색 재킷', color: '#8a78bb'},
    'female-1': {name: '보라색 후드', color: '#cb7773'},
    'female-2': {name: '초록색 카디건', color: '#4e9b91'},
  };
  const images = new Map();
  const rows = {down: 0, left: 1, right: 2, up: 3};
  const frameSize = 128, size = 40;
  const resolve = id => Object.hasOwn(definitions, id) ? id : 'male-1';
  function frameFor(actor, t) {
    const row = rows[actor.dir] ?? 0;
    const elapsed = Number.isFinite(actor.walkTime) ? actor.walkTime * 1000 : t;
    const column = actor.moving ? Math.floor(elapsed / 115) % 4 : (row === 1 || row === 2 ? 4 : 1);
    return {row, column};
  }
  function draw(ctx, actor, t) {
    const image = images.get(resolve(actor.avatar));
    if (!image?.complete || !image.naturalWidth) return false;
    const {row, column} = frameFor(actor, t);
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(image, column * frameSize, row * frameSize, frameSize, frameSize,
      -size / 2, -124 / frameSize * size, size, size);
    ctx.restore();
    return true;
  }
  for (const id of Object.keys(definitions)) {
    const image = new Image(); images.set(id, image);
    image.src = `assets/characters/${id}-walk-v5.png`;
  }
  window.CampusAvatars = {definitions, ids: Object.keys(definitions), size, resolve, frameFor, draw, images};
})();
