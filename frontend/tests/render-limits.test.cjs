// 그리기 상한(계획 docs/metaverse-multiprocess-plan.md B1·B2): 화면 주사율과 상관없이 초당 60번, 캔버스는 1920×1680 화소까지.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../dist/campus.js'), 'utf8');
const start = source.indexOf('const FRAME_MS='), end = source.indexOf('\n', source.indexOf('const frameDue='));

function limits(devicePixelRatio) {
  const context = vm.createContext({devicePixelRatio});
  vm.runInContext(source.slice(start, end) + '\nthis.api={pixelScale,frameDue};', context);
  return context.api;
}

test('the map draws about 60 times a second on fast screens and every frame on slower ones', () => {
  for (const [hz, expected] of [[60, 60], [75, 60], [120, 60], [144, 60], [240, 60], [30, 30]]) {
    const {frameDue} = limits(2);
    let drawn = 0;
    for (let i = 0; i < hz * 10; i++) if (frameDue(i * 1000 / hz + (i % 2 ? .4 : -.4))) drawn++;  // 프레임 시각 흔들림 ±0.4ms
    assert.ok(Math.abs(drawn / 10 - expected) <= 1, `${hz}Hz: ${drawn / 10} draws per second`);
  }
});

test('canvas pixels stay within 1920x1680, keep the aspect ratio and never exceed the device ratio', () => {
  const size = (ratio, width, height) => {const scale = limits(ratio).pixelScale(width, height); return [Math.round(width * scale), Math.round(height * scale)];};
  assert.deepEqual(size(2, 1502, 846), [1920, 1081]);   // Retina 노트북: 3004×1692 → 1920×1081
  assert.deepEqual(size(1, 1920, 1080), [1920, 1080]);  // 그대로
  assert.deepEqual(size(1, 1366, 768), [1366, 768]);    // 작은 화면을 키우지 않는다
  assert.deepEqual(size(2, 800, 600), [1600, 1200]);    // 작은 창은 예전과 같다
  assert.deepEqual(size(1, 3840, 2160), [1920, 1080]);  // 4K
  assert.deepEqual(size(2, 1000, 1500), [1120, 1680]);  // 세로로 긴 창
});
