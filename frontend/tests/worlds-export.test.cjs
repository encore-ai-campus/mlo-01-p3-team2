// 서버 판정용 지도(worlds.json)가 프론트 지도와 같아야 한다: 가구·벽을 옮기면 서버 충돌도 같이 옮겨야 한다.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const test = require('node:test');
const {render, TARGET} = require('../tools/export-worlds.cjs');

test('backend worlds.json matches the frontend map (regenerate with: node frontend/tools/export-worlds.cjs)', () => {
  assert.ok(fs.readFileSync(TARGET, 'utf8') === render(), 'worlds.json is out of date; run node frontend/tools/export-worlds.cjs');
});
