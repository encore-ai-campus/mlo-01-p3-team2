// 프론트 지도 데이터에서 서버 판정용 지도(backend/campus/data/worlds.json)를 만든다.
// 지도(map-data·rooftop-data·classroom-map 등)를 고치면 dev/ 에서: node frontend/tools/export-worlds.cjs
// frontend/tests/worlds-export.test.cjs 가 두 쪽이 어긋나면 실패한다.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const FRONTEND = path.join(__dirname, '..');
const TARGET = path.join(FRONTEND, '../backend/campus/data/worlds.json');
const SOURCES = ['dist/map-data.js', 'dist/rooftop-data.js', 'dist/stair-motion.js', 'dist/avatars.js', 'learning/static/learning/classroom-map.js'];
// 교실 소품에는 solid 표시가 없다: 책상 위 물건과 출입구 문턱만 지나간다
const CLASSROOM_PASSABLE = new Set(['laptop', 'monitor', 'door-threshold']);
// 학습교실 입장 구역: 교실 윗벽의 틈
const GATES = [['python', 'class1'], ['sql', 'class2']];

function build(root = FRONTEND) {
  const context = vm.createContext({Image: class { set src(value) {} }, window: {}});
  for (const file of SOURCES) vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, {filename: file});
  const w = context.window;
  const rect = r => ({x: r.x, y: r.y, w: r.w, h: r.h});
  const footprint = o => o.collision ? {x: o.x + o.collision.x, y: o.y + o.collision.y, w: o.collision.w, h: o.collision.h} : o;
  const object = o => {
    const row = {id: o.id, type: o.type};
    if (o.name) row.name = o.name;
    for (const key of ['toFloor', 'arrival', 'action', 'contentType']) if (o[key] !== undefined) row[key] = o[key];
    row.confirmTransfer = o.confirmTransfer === true;
    if (o.interactionPoint) row.interactionPoint = o.interactionPoint;
    row.footprint = rect(footprint(o));
    return row;
  };
  const solid = data => data.objects.filter(o => o.solid !== false && !(o.classroomAsset && CLASSROOM_PASSABLE.has(o.type)))
    .map(o => ({...rect(footprint(o)), pad: 0}));
  const base = (data, radius) => ({id: data.id, name: data.name, width: data.width, height: data.height,
    angle: data.angle ?? Math.PI / 4, tilt: data.tilt ?? .58, privateRoom: data.privateRoom === true, radius, rooms: data.rooms});
  const floor = data => ({...base(data, 5.5), ...(data.entrance ? {entrance: data.entrance} : {}), spawn: data.spawn, portals: data.portals,
    objects: data.objects.map(object),
    colliders: [...data.walls.map(l => ({x: Math.min(l.x1, l.x2), y: Math.min(l.y1, l.y2), w: Math.abs(l.x2 - l.x1), h: Math.abs(l.y2 - l.y1), pad: 5})),
      ...w.CampusStairs.barriers(data), ...solid(data)]});
  const classroom = data => ({...base({...data, privateRoom: true}, 7), spawn: data.spawn, portals: data.portals,
    objects: data.objects.map(object), colliders: solid(data), exit: data.exit});
  const campus = w.CampusWorlds.campus;
  const gate = (subject, roomId) => {
    const room = campus.rooms.find(r => r.id === roomId);
    const top = campus.walls.filter(l => l.y1 === l.y2 && l.y1 === room.y).map(l => [Math.min(l.x1, l.x2), Math.max(l.x1, l.x2)]).sort((a, b) => a[0] - b[0]);
    const gap = top.slice(1).map((l, i) => [top[i][1], l[0]]).find(([a, b]) => b > a && a >= room.x && b <= room.x + room.w);
    if (!gap) throw new Error(`${roomId}: 윗벽에 입장 틈이 없다`);
    return {subject, room, left: gap[0], right: gap[1], y: room.y};
  };
  return {version: 1, worlds: {campus: floor(campus), rooftop: floor(w.CampusWorlds.rooftop)},
    classrooms: Object.fromEntries(GATES.map(([subject]) => [subject, classroom(w.CampusClassroomMap.forSubject(subject).data)])),
    gates: GATES.map(([subject, roomId]) => gate(subject, roomId)),
    avatarColors: Object.fromEntries(Object.entries(w.CampusAvatars.definitions).map(([id, avatar]) => [id, avatar.color]))};
}

const render = () => JSON.stringify(build(), null, 2) + '\n';

if (require.main === module) {
  fs.writeFileSync(TARGET, render());
  console.log('written', path.relative(process.cwd(), TARGET));
}

module.exports = {build, render, TARGET};
