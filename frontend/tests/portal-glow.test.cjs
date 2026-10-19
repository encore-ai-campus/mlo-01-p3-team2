// 프레임마다 그리는 포털 빛은 shadowBlur 를 쓰지 않는다(계획 docs/metaverse-multiprocess-plan.md B3). 흐림은 한 번만 그려 두는 바닥·게시판에만 남는다.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');

test('per-frame map drawing sets no shadow blur while the portals keep animating', () => {
  let blurs = 0, strokes = 0;
  const target = {measureText: text => ({width: text.length * 7}), createLinearGradient: () => ({addColorStop() {}}),
    createRadialGradient: () => ({addColorStop() {}}), stroke() { strokes++; }};
  const context = new Proxy(target, {
    get: (object, key) => object[key] ?? (() => {}),
    set(object, key, value) { if (key === 'shadowBlur' && value > 0) blurs++; object[key] = value; return true; },
  });
  const sandbox = vm.createContext({window: {CampusAvatars: {size: 40, draw: () => true}}, performance: {now: () => 0}, Path2D: class { constructor() { return new Proxy({}, {get: () => () => {}}); } },
    document: {createElement: () => ({getContext: () => context})}});
  for (const file of ['dist/map-data.js', 'dist/rooftop-data.js', 'dist/stair-motion.js', 'dist/isometric.js'])
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), sandbox, {filename: file});
  for (const floor of ['campus', 'rooftop']) {
    const data = sandbox.window.CampusWorlds[floor];
    assert.ok(data.objects.some(o => o.type === 'floor-portal' || o.portalGlow), `${floor} has an animated portal`);
    blurs = 0;
    const renderer = sandbox.window.CampusIsometric.create({data});
    const cached = blurs;
    blurs = 0; strokes = 0;
    renderer.draw(context, {camera: {zoom: 1, x: 0, y: 0}, actors: [], t: 1234, viewportWidth: 1e5, viewportHeight: 1e5});
    if (floor === 'campus') assert.ok(cached > 0, 'campus: cached sprites (portal floor, notice board) still use blur');
    assert.equal(blurs, 0, `${floor}: per-frame drawing set shadowBlur ${blurs} times`);
    assert.ok(strokes > 0, `${floor}: portal light was drawn`);
  }
});
