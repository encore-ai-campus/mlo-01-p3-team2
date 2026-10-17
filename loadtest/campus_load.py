"""메타버스 백엔드 부하 생성기. 브라우저와 같은 주기로 N명을 흉내 낸다(load 컨테이너 안에서 run.py 가 실행).

브라우저 동작(frontend/dist):
- presence.js: 접속 후 5초마다 ping. 입력은 화면 프레임마다 publish(t)를 부르고 100ms 제한만 있어서, 키를 안 눌러도
  0.1초마다 input 을 보낸다(`--client current`). 키가 바뀌면 바로 보낸다. `--client new`는 계획 1c(키·찌르기가 있을 때만 0.1초마다).
- session-policy.js·messages.js: 15초마다 HTTP 조회 둘(`--client current`). `new` 는 계획 4g: 소켓이 붙어 있으면 조회하지 않는다.
- session-policy.js: 키·마우스 입력이 있으면 활동 POST(15초에 한 번까지). 여기서는 이동 중인 사람이 보낸다.
- 끊기면 1→2→4→…→10초 간격으로 다시 연결하고, 4401·4409 면 멈춘다.

이동은 사용자마다 "쉬기 → 2~4초 이동"을 되풀이한다. `--moving` 은 이동 중인 시간의 비율이다.
`--behavior real` 은 실사용 모방(사람마다 초당 행동 10건, 아래 '실사용 모방' 절): 걷기·점프·찌르기·채팅·계단·교실 학습·부스·패널 HTTP 를
서버 규칙대로 실제로 한다. 화면을 열 때처럼 접속마다 첫 화면(GET /)도 받는다. 서버 지도는 /app(backend)의 campus.motion 을 쓴다.
측정 구간의 시작·끝에 `MEASURE_START`·`MEASURE_END` 를 찍고(run.py 가 이때 서버 CPU·DB 를 읽는다) 마지막 줄에 JSON 요약을 낸다.
"""
import argparse
import asyncio
import heapq
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from autobahn.asyncio.websocket import WebSocketClientFactory, WebSocketClientProtocol

# 여러 프로세스 시험(계획 M5)은 nginx(세션 고정 배정)로 붙는다: CAMPUS_HOST=nginx CAMPUS_PORT=8000
HOST, PORT = os.environ.get("CAMPUS_HOST", "backend"), int(os.environ.get("CAMPUS_PORT", "9003"))
MOVE_KEYS = (["d"], ["a"], ["w"], ["s"], ["d", "w"], ["a", "s"])
POLLS = ("/accounts/session/status/", "/api/messages/status/")  # 추첨(/api/raffle/)은 기능을 없앴다(2026-10-16)
ACTIVITY = "/accounts/session/activity/"
CSRF = "a" * 32  # 부하 시험용 CSRF 비밀(쿠키와 헤더에 같은 값)
MOVE_PREFIX = b'{"type": "move"'  # move 와 moves(0.1초 묶음) 둘 다
MOVES_PREFIX = b'{"type": "moves"'
EFFECTS = b', "effects": ['  # 0.1초 묶음에 실린 점프·찌르기(계획 §8)


class Stats:
    def __init__(self):
        self.recv, self.sent, self.closes, self.http_status = Counter(), Counter(), Counter(), Counter()
        self.state_gap, self.move_lag, self.peer_gap, self.loop_lag = [], [], [], []
        self.http_ms = {}  # 경로 → 응답 시간들
        self.welcomed = 0
        self.actions, self.action_errors, self.errands = Counter(), Counter(), Counter()  # 실사용 모방: 행동·거절·심부름
        self.action_ms = {}  # 행동 → 결과까지 시간(조작은 control_result, 채팅은 내 채팅이 돌아올 때, 패널은 요청을 모두 마칠 때)


stats = Stats()
measuring = False


class User:
    def __init__(self, key, rng, watch):
        self.key, self.rng, self.watch = key, rng, watch
        self.proto, self.ready, self.keys = None, False, []
        self.last_state = self.move_started = None
        self.peers = {}
        self.closed = None
        self.reset_real()

    def reset_real(self):
        self.player_id = self.pose = self.interior = self.errand = self.poke_scope = self.chat_sent = None
        self.floor, self.poking, self.transferring, self.busy, self.http_busy = "campus", False, False, False, False
        self.poke_until = self.next_chat = self.next_panel = 0.0
        self.last_jump = self.last_chat = -math.inf
        self.pending, self.sequence, self.chat_count = {}, 0, 0
        self.progress = ((0.0, 0.0), 0.0)


class Client(WebSocketClientProtocol):
    def onOpen(self):
        self.factory.user.proto = self

    def onMessage(self, payload, is_binary):
        user, now = self.factory.user, time.monotonic()
        if payload.startswith(MOVE_PREFIX) and not user.watch:
            if measuring:
                stats.recv["moves" if payload.startswith(MOVES_PREFIX) else "move"] += 1
                if EFFECTS in payload:
                    for effect in json.loads(payload)["effects"]:
                        stats.recv[effect["type"]] += 1
            return
        message = json.loads(payload)
        kind = message.get("type")
        if measuring:
            stats.recv[kind] += 1
            for effect in message.get("effects", ()) if kind == "moves" else ():
                stats.recv[effect["type"]] += 1
        if kind == "welcome":
            user.ready = True
            user.player_id = message["selfId"]
            stats.welcomed += 1
        elif kind == "control_result":
            entry = user.pending.pop(message.get("requestId"), None)
            if entry:
                future, action, started = entry
                if measuring:
                    stats.action_ms.setdefault(action, []).append(now - started)
                    if "error" in message:
                        stats.action_errors[f"{action}: {message['error']}"] += 1
                if not future.done():
                    future.set_result(message)
        elif kind == "control_event":
            event = message.get("event") or {}
            if event.get("type") == "transfer_offer" and not user.transferring and floors:
                later(take_transfer(user, event))
        elif kind in ("control_error", "chat_error"):
            count(stats.action_errors, f"{kind}: {message.get('message')}")
        elif kind == "chat":
            if message["message"].get("playerId") == user.player_id and user.chat_sent is not None:
                if measuring:
                    stats.action_ms.setdefault("chat", []).append(now - user.chat_sent)
                user.chat_sent = None
        if kind == "control_state":
            state = message["state"]
            user.floor, interior = state["main"]["floor"], state.get("interior")
            user.interior = interior["subject"] if interior else None
            actor = interior["actor"] if interior else state["main"]
            user.pose = (actor["x"], actor["y"])
            if user.keys and user.last_state is not None and measuring:
                stats.state_gap.append(now - user.last_state)
            user.last_state = now if user.keys else None
            if user.move_started is not None and actor.get("moving"):  # 교실 안에서는 교실 속 나
                if measuring:
                    stats.move_lag.append(now - user.move_started)
                user.move_started = None
        elif kind in ("move", "moves") and user.watch:
            for player in message["players"] if kind == "moves" else [message["player"]]:
                if player.get("moving"):
                    last = user.peers.get(player["id"])
                    if last is not None and measuring:
                        stats.peer_gap.append(now - last)
                    user.peers[player["id"]] = now
                else:
                    user.peers.pop(player["id"], None)

    def onClose(self, was_clean, code, reason):
        user = self.factory.user
        stats.closes[code] += 1
        user.ready, user.proto = False, None
        for future, _, _ in user.pending.values():
            if not future.done():
                future.set_result(None)
        user.reset_real()
        if user.closed and not user.closed.done():
            user.closed.set_result(code)


def send(user, obj, kind):
    if user.proto is not None and user.ready:
        user.proto.sendMessage(json.dumps(obj).encode())
        if measuring:
            stats.sent[kind] += 1


def set_keys(user, keys):
    user.keys = keys
    user.last_state = None
    user.move_started = time.monotonic() if keys else None
    message = {"type": "input", "keys": keys}
    if user.poking:  # 찌르는 중에 키가 바뀌면 찌르기 범위도 함께(presence.js publish force)
        message.update(poking=True, pokeContext=user.poke_scope)
    send(user, message, "input")  # 바뀌면 바로(presence.js setInput)


async def heartbeat(user):
    while True:
        await asyncio.sleep(5)
        send(user, {"type": "ping"}, "ping")


async def input_loop(user, client):
    if client == "current":
        while True:
            await asyncio.sleep(0.1)
            send(user, {"type": "input", "keys": user.keys}, "input")
    while True:
        await asyncio.sleep(0.1)
        if user.keys or user.poking:  # 누르고 있는 동안만(presence.js tick)
            send(user, {"type": "input", "keys": user.keys, **({"poking": True} if user.poking else {})}, "input")


async def behave(user, moving):
    if moving <= 0:
        return
    hold = 3.0
    idle = hold * (1 - moving) / moving
    await asyncio.sleep(user.rng.uniform(0, idle + hold))
    while True:
        set_keys(user, list(user.rng.choice(MOVE_KEYS)))
        await asyncio.sleep(user.rng.uniform(2, 4))
        set_keys(user, [])
        await asyncio.sleep(user.rng.uniform(0.5 * idle, 1.5 * idle))


def fetch(path, key, data=None):
    """data 가 있으면 JSON POST(CSRF 쿠키·헤더). (상태, 걸린 초, 본문)."""
    headers = {"Cookie": f"campus_sessionid={key}; campus_csrftoken={CSRF}", "Accept": "application/json"}
    if data is not None:
        headers.update({"X-CSRFToken": CSRF, "Origin": f"http://{HOST}:{PORT}", "Content-Type": "application/json"})
        data = json.dumps(data).encode()
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", data=data, headers=headers)
    started = time.monotonic()
    body = b""
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
    except OSError:
        status = "error"
    return status, time.monotonic() - started, body


async def request(user, path):
    status, seconds, _ = await asyncio.get_running_loop().run_in_executor(None, fetch, path, user.key, {} if path == ACTIVITY else None)
    if measuring:
        stats.http_status[f"{path} {status}"] += 1
        stats.http_ms.setdefault(path, []).append(seconds)


async def polls(user, every, client):
    await asyncio.sleep(user.rng.uniform(0, every))
    while True:
        if client == "current" or not user.ready:  # new: 소켓이 붙어 있으면 소켓이 알려 준다
            for path in POLLS:
                await request(user, path)
        await asyncio.sleep(every)


async def activity(user):
    """키 입력이 있으면 활동 POST — session-policy.js 처럼 15초에 한 번까지."""
    last = -math.inf
    while True:
        await asyncio.sleep(0.5)
        if user.keys and time.monotonic() - last >= 15:
            last = time.monotonic()
            await request(user, ACTIVITY)


async def run_user(user, delay, args):
    loop = asyncio.get_running_loop()
    await asyncio.sleep(delay)
    if args.polls > 0:
        asyncio.create_task(polls(user, args.polls, args.client))
    asyncio.create_task(activity(user))
    retry = 1.0
    while True:
        if args.behavior == "real":  # 브라우저는 화면(GET /)을 받은 뒤 소켓을 연다
            await call(user, "/", label="page")
        factory = WebSocketClientFactory(f"ws://{HOST}:{PORT}/ws/campus/?control=server", origin=f"http://{HOST}:{PORT}",
                                         headers={"Cookie": f"campus_sessionid={user.key}"})
        factory.setProtocolOptions(utf8validateIncoming=False, openHandshakeTimeout=30)  # 브라우저처럼 핸드셰이크를 오래 기다린다(autobahn 기본 5초)
        factory.protocol, factory.user = Client, user
        user.closed = loop.create_future()
        try:
            await loop.create_connection(factory, HOST, PORT)
        except OSError:
            stats.closes["connect_error"] += 1
            await asyncio.sleep(retry)
            retry = min(retry * 2, 10)
            continue
        for _ in range(300):
            if user.ready or user.closed.done():
                break
            await asyncio.sleep(0.05)
        tasks = []
        if user.ready:
            retry = 1.0
            tasks = [asyncio.create_task(heartbeat(user)), asyncio.create_task(input_loop(user, args.client)),
                     asyncio.create_task(real_user(user) if args.behavior == "real" else behave(user, args.moving))]
        code = await user.closed
        for task in tasks:
            task.cancel()
        user.keys = []
        user.reset_real()
        if code in (4401, 4409):
            return
        await asyncio.sleep(retry)
        retry = min(retry * 2, 10)


# ---- 실사용 모방(--behavior real, 계획 docs/metaverse-multiprocess-plan.md §8) ----
# 행동 = 사용자가 직접 한 일이 서버로 가는 것: 이동 키를 누르기·바꾸기·떼기, 점프, 찌르기 누르기·떼기, 채팅, 패널 열기(HTTP),
# 계단·포탈 이동 확인, 교실 학습 시작·답 제출·나가기, 부스 열기. 누르고 있는 키의 0.1초 갱신·ping·활동 POST 는 행동이 아니다.
# 모든 행동은 서버 규칙(점프 착지 0.72초, 채팅 0.8초, 계단·교실·부스는 그 자리에서)을 지켜 실제로 받아들여지게 한다.
ACTION_RATE = 10  # 사람마다 초당 행동 슬롯. 슬롯마다 아래 몫으로 하나를 고른다
JUMP_SHARE, POKE_SHARE = .10, .10  # 점프·찌르기(누르기)의 몫. 나머지는 이동 키(가려는 곳 쪽 두 방향을 번갈아 — 사람이 키를 고쳐 누르듯)
CHAT_EVERY, PANEL_EVERY = 12.0, 15.0  # 채팅·패널의 평균 간격(초)
ERRANDS = {"campus": (("wander", .73), ("portal", .12), ("classroom", .15)),
           "rooftop": (("wander", .80), ("portal", .15), ("booth", .05))}
PANELS = (("menu", .2), ("messages", .2), ("dm_send", .1), ("community", .2), ("wallet", .2), ("lunch", .1))
COMBOS = (("d",), ("a",), ("w",), ("s",), ("d", "w"), ("d", "s"), ("a", "w"), ("a", "s"))
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
STEP = 8  # 길찾기 칸(px). 벽은 반지름·여유를 더해 11px 넘게 두꺼워 칸 사이로 빠지지 않는다
ERRAND_LIMIT = 40.0
floors = {}  # 공간 이름 → Floor. 부모 프로세스가 한 번 만들고 fork 로 나눠 쓴다
background = set()


class Floor:
    """한 공간의 걷기 지도(서버와 같은 충돌 판정 campus.motion.World): 칸마다 걸을 수 있는지와 목적지마다 '다음 칸'(흐름장)."""

    def __init__(self, data):
        from campus.motion import World
        self.world, self.data = World(data), data
        self.free = {(cx, cy) for cy in range(int(data["height"] // STEP) + 1) for cx in range(int(data["width"] // STEP) + 1)
                     if self.world.walkable(cx * STEP, cy * STEP)}
        self.cells = sorted(self.free)
        angle, tilt = data["angle"], data["tilt"]
        self.velocity = {}
        for combo in COMBOS:  # 서버 motion.tick 과 같은 키 → 이동 방향
            dx, dy = ("d" in combo) - ("a" in combo), ("s" in combo) - ("w" in combo)
            n = math.hypot(dx, dy)
            vx = math.cos(angle) * dx / n + math.sin(angle) * dy / n / tilt
            vy = -math.sin(angle) * dx / n + math.cos(angle) * dy / n / tilt
            self.velocity[combo] = (vx / math.hypot(vx, vy), vy / math.hypot(vx, vy))
        self.flows, self.goals = {}, {}

    def cell(self, x, y):
        cx, cy = round(x / STEP), round(y / STEP)
        for r in range(3):
            near = [(cx + ox, cy + oy) for ox in range(-r, r + 1) for oy in range(-r, r + 1) if (cx + ox, cy + oy) in self.free]
            if near:
                return min(near, key=lambda c: (c[0] * STEP - x) ** 2 + (c[1] * STEP - y) ** 2)
        return None

    def add_goal(self, name, x, y):
        goal = self.world.closest(x, y)
        start = self.cell(goal["x"], goal["y"])
        nxt, dist, heap = {start: None}, {start: 0.0}, [(0.0, start)]
        while heap:
            d, (cx, cy) = heapq.heappop(heap)
            if d > dist[(cx, cy)]:
                continue
            for ox, oy in NEIGHBORS:
                n = (cx + ox, cy + oy)
                if n not in self.free or (ox and oy and ((cx + ox, cy) not in self.free or (cx, cy + oy) not in self.free)):
                    continue
                nd = d + (1.414 if ox and oy else 1.0)
                if nd < dist.get(n, math.inf):
                    dist[n], nxt[n] = nd, (cx, cy)
                    heapq.heappush(heap, (nd, n))
        self.flows[name], self.goals[name] = nxt, (goal["x"], goal["y"])

    def toward(self, name, x, y, ahead=4):
        """흐름장을 따라 ahead 칸 안에서 곧게 갈 수 있는 가장 먼 점(모서리를 질러 벽에 붙지 않게)."""
        nxt, cell = self.flows[name], self.cell(x, y)
        if cell not in nxt:
            return self.goals[name]
        point = cell[0] * STEP, cell[1] * STEP
        for _ in range(ahead):
            if nxt[cell] is None:
                return self.goals[name]
            cell = nxt[cell]
            if not self.world.clear({"x": x, "y": y}, {"x": cell[0] * STEP, "y": cell[1] * STEP}):
                break
            point = cell[0] * STEP, cell[1] * STEP
        return point

    def ranked(self, x, y, tx, ty):
        dx, dy = tx - x, ty - y
        n = math.hypot(dx, dy) or 1
        return sorted(((self.velocity[c][0] * dx + self.velocity[c][1] * dy) / n, c) for c in COMBOS)[::-1]

    def visible_point(self, x, y, rng):
        """곧게 걸어갈 수 있는 300px 안의 점(사람이 보이는 곳으로 걷듯). 못 찾으면 아무 칸."""
        for _ in range(5):
            cx, cy = rng.choice(self.cells)
            point = {"x": cx * STEP, "y": cy * STEP}
            if math.hypot(point["x"] - x, point["y"] - y) < 300 and self.world.clear({"x": x, "y": y}, point):
                return point["x"], point["y"]
        cx, cy = rng.choice(self.cells)
        return cx * STEP, cy * STEP


def build_floors():
    sys.path.insert(0, "/app")
    from campus.motion import geometry
    data = geometry()
    for name in ("campus", "rooftop"):
        floor = floors[name] = Floor(data["worlds"][name])
        for portal in floor.data["portals"]:
            floor.add_goal("portal:" + portal["objectId"], portal["x"] + portal["w"] / 2, portal["y"] + portal["h"] / 2)
        for obj in floor.data["objects"]:
            if obj.get("action") == "booth":
                floor.add_goal("booth:" + obj["id"], *obj["interactionPoint"])
    for gate in data["gates"]:  # 출입구 선을 아래로 넘어 교실 안쪽 점까지(서버가 넘는 순간 교실로 들인다)
        floors["campus"].add_goal("gate:" + gate["subject"], (gate["left"] + gate["right"]) / 2, gate["y"] + 30)
    for subject, room in data["classrooms"].items():
        floor = floors[subject] = Floor(room)
        floor.add_goal("exit", *room["exit"]["interactionPoint"])
        for kind in ("multiple_choice", "fill_blank"):
            obj = next(o for o in room["objects"] if o.get("action") == "learning" and o.get("contentType") == kind)
            floor.add_goal("learn:" + kind, *obj["interactionPoint"])


def pick(weighted, rng):
    r = rng.random() * sum(w for _, w in weighted)
    for name, w in weighted:
        r -= w
        if r <= 0:
            return name
    return weighted[-1][0]


def gap(mean, rng):
    return rng.expovariate(1 / mean) if math.isfinite(mean) else math.inf


def later(coroutine):
    task = asyncio.create_task(coroutine)
    background.add(task)
    task.add_done_callback(background.discard)


def count(counter, key):
    if measuring:
        counter[key] += 1


def scope(user):
    return {"context": "classroom", "subject": user.interior} if user.interior else {"context": "world", "floor": user.floor}


def command(user, action, data=None):
    user.sequence += 1
    request_id = str(user.sequence)
    future = asyncio.get_running_loop().create_future()
    user.pending[request_id] = (future, action, time.monotonic())
    send(user, {"type": "control", "requestId": request_id, "action": action, "data": data or {}}, "control")
    return future


async def expect(user, action, data=None):
    """조작 하나를 보내고 결과(control_result)를 기다린다. 결과·시간·오류는 onMessage 가 적는다."""
    try:
        return await asyncio.wait_for(command(user, action, data), 10)
    except TimeoutError:
        count(stats.action_errors, f"{action}: 응답 없음(10초)")
        return None


async def call(user, path, data=None, label=None):
    """HTTP 하나(브라우저처럼 edge → 프론트 → 백엔드). (상태, JSON 또는 None)."""
    status, seconds, body = await asyncio.get_running_loop().run_in_executor(None, fetch, path, user.key, data)
    label = label or path
    if measuring:
        stats.http_status[f"{label} {status}"] += 1
        stats.http_ms.setdefault(label, []).append(seconds)
    try:
        return status, json.loads(body) if body else None
    except ValueError:
        return status, None


async def open_panel(user, name):
    """패널 하나를 연다(그 화면이 부르는 요청을 그대로). 실패한 요청은 오류로 센다."""
    user.http_busy = True
    started = time.monotonic()
    statuses = []
    try:
        if name == "menu":
            statuses.append((await call(user, "/api/board/menu/", label="menu"))[0])
        elif name == "messages":
            for path in ("/api/messages/status/", "/api/messages/conversations/"):
                statuses.append((await call(user, path, label="messages"))[0])
        elif name == "dm_send":
            status, body = await call(user, "/api/messages/recipients/?q=" + urllib.parse.quote("부하"), label="dm_send")
            statuses.append(status)
            others = [row["id"] for row in (body or {}).get("recipients", []) if row.get("id")]
            if others:
                statuses.append((await call(user, "/api/messages/send/", {"recipient": user.rng.choice(others), "requestId": str(uuid.uuid4()),
                                                                          "body": "부하 시험 쪽지"}, label="dm_send"))[0])
        elif name == "community":
            for path in ("/api/community/", "/api/community/posts/?page=1"):
                statuses.append((await call(user, path, label="community"))[0])
        elif name == "wallet":
            for path in ("/api/learning/wallet/", "/api/learning/wallet/history/"):
                statuses.append((await call(user, path, label="wallet"))[0])
        elif name == "lunch":
            statuses.append((await call(user, "/api/campus/lunch/spin/", {}, label="lunch"))[0])
    finally:
        user.http_busy = False
    if measuring:
        stats.action_ms.setdefault("panel:" + name, []).append(time.monotonic() - started)
        for status in statuses:
            if status not in (200, 201):
                stats.action_errors[f"panel:{name} {status}"] += 1


async def learning(user, errand):
    """교실 학습 자리에서 E(interact) → 학습 창이 부르는 요청 → 한 문제 풀기. 예제 문제은행은 python 초급뿐이라 sql 은 창만 연다."""
    try:
        result = await expect(user, "interact")
        if not result or (result.get("result") or {}).get("type") != "learning_open":
            return
        await call(user, "/api/learning/csrf/", label="learning")
        await call(user, "/api/learning/wallet/", label="learning")
        if errand["subject"] != "python":
            await asyncio.sleep(user.rng.uniform(1, 2))
            return
        status, session = await call(user, "/api/learning/sessions/", {"subject": "python", "question_type": errand["question"],
                                                                        "difficulty": "beginner"}, label="learning")
        if status != 201:
            count(stats.action_errors, f"learning: 세션 {status}")
            return
        base = f"/api/learning/sessions/{session['session_id']}/questions/1/"
        status, question = await call(user, base, label="learning")
        await asyncio.sleep(user.rng.uniform(2, 4))  # 문제를 읽고 고른다
        choice = user.rng.choice(question["choices"]) if errand["question"] == "multiple_choice" and question else None  # 빈칸은 글로 답한다
        status, answer = await call(user, base + "answers/", {"answer": choice["choice_text"] if choice else "print",
                                                              "submission_request_uuid": str(uuid.uuid4()),
                                                              "choice_uuid": choice["choice_uuid"] if choice else None}, label="learning")
        count(stats.actions, "learning")  # 답 제출(클릭)
        if status != 201:
            count(stats.action_errors, f"learning: 답 {status} {(answer or {}).get('error')}")
        else:
            count(stats.errands, "learning")
    finally:
        user.busy = False
        errand["phase"] = "exit"


async def leave_classroom(user, errand):
    result = await expect(user, "interact")
    if not result or "error" in result:
        await asyncio.sleep(1)
        errand["phase"] = "exit"


async def take_transfer(user, offer):
    """계단·포탈 안으로 걸어 들어가면 서버가 transfer_offer 를 보낸다: 확인(필요하면 1초 남짓) → begin_transfer → 화면 전환 → transfer."""
    user.transferring = True
    try:
        if user.keys:
            set_keys(user, [])
        await asyncio.sleep(user.rng.uniform(.8, 1.5) if offer.get("confirm") else .1)
        count(stats.actions, "transfer")
        result = await expect(user, "begin_transfer", {"floor": offer["floor"]})
        if result and "error" not in result:
            await asyncio.sleep(.8)  # 층 이동 화면
            result = await expect(user, "transfer", {"floor": offer["floor"]})
            if result and "error" not in result:
                count(stats.errands, "transfer")
                return
        await expect(user, "cancel_transfer")
    finally:
        user.transferring = False
        if user.errand and user.errand["kind"] == "portal":
            user.errand = None


def next_errand(user, now):
    rng, floor = user.rng, floors[user.floor]
    errand = {"kind": pick(ERRANDS[user.floor], rng), "started": now}
    if errand["kind"] == "wander":
        errand.update(until=now + rng.uniform(3, 10), point=floor.visible_point(*user.pose, rng))
    elif errand["kind"] == "portal":
        errand["flow"] = "portal:" + rng.choice(floor.data["portals"])["objectId"]
    elif errand["kind"] == "classroom":
        subject = rng.choice(("python", "python", "sql"))
        errand.update(subject=subject, phase="gate", flow="gate:" + subject)
    else:
        errand.update(flow="booth:" + rng.choice([o["id"] for o in floor.data["objects"] if o.get("action") == "booth"]))
    user.errand = errand


def stuck(user, now):
    """키를 누르는데 1초 동안 6px 도 못 갔다(벽에 붙음)."""
    (px, py), since = user.progress
    if not user.keys or math.hypot(user.pose[0] - px, user.pose[1] - py) > 6:
        user.progress = (user.pose, now)
        return False
    if now - since > 1.0:
        user.progress = (user.pose, now)
        count(stats.errands, "stuck")
        return True
    return False


def errand_target(user, floor, now):
    """지금 할 일을 한 걸음 진행한다. 조작을 보냈으면 그 행동 이름, 아니면 걸어갈 점(None 이면 멈춤)."""
    errand, (x, y) = user.errand, user.pose
    if user.interior and (errand is None or errand["kind"] != "classroom"):  # 걷다가 교실 출입구를 넘었다
        errand = user.errand = {"kind": "classroom", "subject": user.interior, "phase": "learn", "started": now}
    if errand is None or (errand["kind"] != "classroom" and now - errand["started"] > ERRAND_LIMIT):
        if errand is not None:
            count(stats.errands, "timeout:" + errand["kind"])
        next_errand(user, now)
        errand = user.errand
    blocked = stuck(user, now)
    kind = errand["kind"]
    if kind == "wander":
        if now > errand["until"]:
            user.errand = None
            return None
        if blocked or math.hypot(errand["point"][0] - x, errand["point"][1] - y) < 20:
            errand["point"] = floor.visible_point(x, y, user.rng)
        return errand["point"]
    if blocked:  # 벽 모서리에 걸리면 한 번 옆으로 비킨다
        return x + user.rng.uniform(-80, 80), y + user.rng.uniform(-80, 80)
    if kind == "portal":
        return floor.toward(errand["flow"], x, y)
    if kind == "booth":
        gx, gy = floor.goals[errand["flow"]]
        if math.hypot(gx - x, gy - y) >= 25:
            return floor.toward(errand["flow"], x, y)
        if "opened" not in errand:
            errand["opened"] = now
            later(expect(user, "open_booth", {"objectId": errand["flow"].removeprefix("booth:")}))
            return "booth"
        if now - errand["opened"] > 1.5:
            count(stats.errands, "booth")
            user.errand = None
        return None
    # 교실: 출입구 → 학습 자리 → E·한 문제 → 출구 → E(나가기)
    phase = errand["phase"]
    if phase == "gate":
        if not user.interior:
            return floor.toward(errand["flow"], x, y)
        errand.update(phase="learn", entered=now)
        count(stats.errands, "classroom_enter")
        return None
    if not user.interior:
        if phase == "leaving":
            count(stats.errands, "classroom_exit")
        user.errand = None
        return None
    errand.setdefault("entered", now)
    if phase == "learn":
        errand.setdefault("question", user.rng.choice(("multiple_choice", "fill_blank")))
        flow = "learn:" + errand["question"]
        gx, gy = floor.goals[flow]
        if math.hypot(gx - x, gy - y) >= 16:
            return floor.toward(flow, x, y)
        errand["phase"], user.busy = "panel", True
        if user.keys:
            set_keys(user, [])
        later(learning(user, errand))
        return "interact"
    if phase == "exit":
        gx, gy = floor.goals["exit"]
        if math.hypot(gx - x, gy - y) >= 16:
            return floor.toward("exit", x, y)
        if now - errand["entered"] < 2.3:  # 입장 2초 뒤에 나갈 수 있다
            return None
        errand["phase"] = "leaving"
        later(leave_classroom(user, errand))
        return "interact"
    return None


def steer(user, floor, target):
    """가려는 점 쪽으로 가장 맞는 키를 누른다. 이미 누르고 있으면 둘째 키로 고쳐 누르거나(쓸 만하면) 잠깐 뗀다 — 사람이 키를 고쳐 누르듯."""
    if target is None:
        if user.keys:
            set_keys(user, [])
            return "move"
        return None
    ranked = floor.ranked(*user.pose, *target)
    best, second = list(ranked[0][1]), list(ranked[1][1])
    set_keys(user, best if user.keys != best else second if ranked[1][0] > .3 else [])
    return "move"


def slot(user, now):
    """행동 슬롯 하나: 할 차례인 것 하나를 하고 그 이름을 돌려준다(없으면 None)."""
    if user.pose is None:
        return None
    rng = user.rng
    if user.poking and now >= user.poke_until:
        user.poking = False
        send(user, {"type": "input", "keys": user.keys}, "input")
        return "poke"
    if now >= user.next_chat and now - user.last_chat >= 1.5:
        user.next_chat, user.last_chat = now + gap(CHAT_EVERY, rng), now
        user.chat_count += 1
        user.chat_sent = now
        send(user, {"type": "chat", "text": f"안녕하세요 {user.chat_count}"}, "chat")
        return "chat"
    if now >= user.next_panel and not user.http_busy:
        user.next_panel = now + gap(PANEL_EVERY, rng)
        later(open_panel(user, pick(PANELS, rng)))
        return "panel"
    if user.transferring or user.busy:  # 층 이동 중·학습 창
        return None
    floor = floors[user.interior or user.floor]
    target = errand_target(user, floor, now)
    if isinstance(target, str):
        return target
    if user.busy:
        return None
    r = rng.random()
    if r < JUMP_SHARE and now - user.last_jump >= .8:
        user.last_jump = now
        later(expect(user, "jump", scope(user)))
        return "jump"
    if r < JUMP_SHARE + POKE_SHARE and not user.poking:
        user.poking, user.poke_until, user.poke_scope = True, now + rng.uniform(.3, .8), scope(user)
        send(user, {"type": "input", "keys": user.keys, "poking": True, "pokeContext": user.poke_scope}, "input")
        return "poke"
    return steer(user, floor, target)


async def real_user(user):
    """초당 ACTION_RATE 번 행동한다: 할 수 있을 때마다 쌓인 몫(최대 2)만큼. 층 이동·학습 창처럼 못 하는 동안 밀린 것을 몰아서 하지 않는다."""
    now = last = time.monotonic()
    user.next_chat, user.next_panel = now + gap(CHAT_EVERY, user.rng), now + gap(PANEL_EVERY, user.rng)
    credit = user.rng.random()
    while True:
        await asyncio.sleep(user.rng.uniform(.03, .07))
        now = time.monotonic()
        credit, last = min(credit + (now - last) * ACTION_RATE, 2.0), now
        if credit >= 1 and (kind := slot(user, now)):
            credit -= 1
            count(stats.actions, kind)


async def watch_loop_lag():
    while True:
        started = time.monotonic()
        await asyncio.sleep(0.1)
        if measuring:
            stats.loop_lag.append(time.monotonic() - started - 0.1)


async def process_main(keys, args, index, start_at, end_at):
    global measuring
    rng = random.Random(1000 + index)
    users = [User(key, random.Random(rng.random()), watch=i < args.watchers) for i, key in enumerate(keys)]
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(32))
    asyncio.create_task(watch_loop_lag())
    for i, user in enumerate(users):
        asyncio.create_task(run_user(user, args.ramp * (i * args.procs + index) / max(1, args.users), args))
    await asyncio.sleep(max(0, start_at - time.time()))
    measuring = True
    await asyncio.sleep(max(0, end_at - time.time()))
    measuring = False


def worker(keys, args, index, start_at, end_at, queue):
    asyncio.run(asyncio.wait_for(process_main(keys, args, index, start_at, end_at), timeout=end_at - time.time() + 5))
    queue.put(stats.__dict__)


def percentiles(values, scale=1000):
    if not values:
        return None
    values = sorted(values)
    pick = lambda q: round(values[min(len(values) - 1, int(q * len(values)))] * scale, 1)  # noqa: E731
    return {"n": len(values), "p50": pick(.5), "p95": pick(.95), "p99": pick(.99), "max": round(values[-1] * scale, 1)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--moving", type=float, default=0.2)
    parser.add_argument("--client", choices=("current", "new"), default="current")
    parser.add_argument("--behavior", choices=("walk", "real"), default="walk", help="real = 실사용 모방(사람마다 초당 행동 10건)")
    parser.add_argument("--mix", default="", help="원인 나누기: jump=0,poke=0,chat=0,panel=0 처럼 몫(점프·찌르기)·간격(채팅·패널, 0 이면 끔)을 바꾼다")
    parser.add_argument("--ramp", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--measure", type=float, default=60)
    parser.add_argument("--procs", type=int, default=4)
    parser.add_argument("--polls", type=float, default=15, help="HTTP 조회 셋의 간격(초). 0 이면 하지 않는다")
    parser.add_argument("--watchers", type=int, default=2, help="프로세스마다 다른 사람의 move 간격을 재는 사용자 수")
    args = parser.parse_args()
    with open("/data/sessions.json", encoding="utf-8") as f:
        keys = json.load(f)[:args.users]
    global JUMP_SHARE, POKE_SHARE, CHAT_EVERY, PANEL_EVERY
    mix = dict(item.split("=") for item in args.mix.split(",") if item)
    JUMP_SHARE, POKE_SHARE = float(mix.get("jump", JUMP_SHARE)), float(mix.get("poke", POKE_SHARE))
    CHAT_EVERY, PANEL_EVERY = float(mix.get("chat", CHAT_EVERY)) or math.inf, float(mix.get("panel", PANEL_EVERY)) or math.inf
    if args.behavior == "real":  # 길찾기 지도(흐름장)는 fork 전에 한 번 만든다
        started = time.monotonic()
        build_floors()
        print(f"floors ready in {time.monotonic() - started:.1f}s", file=sys.stderr, flush=True)
    start_at = time.time() + args.ramp + args.warmup
    end_at = start_at + args.measure
    queue = mp.Queue()
    procs = [mp.Process(target=worker, args=(keys[i::args.procs], args, i, start_at, end_at, queue)) for i in range(args.procs)]
    for proc in procs:
        proc.start()
    time.sleep(max(0, start_at - time.time()))
    print("MEASURE_START", flush=True)
    time.sleep(max(0, end_at - time.time()))
    print("MEASURE_END", flush=True)
    parts = [queue.get(timeout=60) for _ in procs]
    for proc in procs:
        proc.join(timeout=10)
    total = Stats()
    for part in parts:
        for name, value in part.items():
            current = getattr(total, name)
            if isinstance(value, dict) and not isinstance(value, Counter):
                for key, items in value.items():
                    current.setdefault(key, []).extend(items)
            else:
                setattr(total, name, current + value if not isinstance(value, Counter) else current + Counter(value))
    seconds = args.measure
    print(json.dumps({
        "users": args.users, "moving": args.moving, "client": args.client, "behavior": args.behavior, "mix": args.mix, "welcomed": total.welcomed,
        "actions_per_user_s": round(sum(total.actions.values()) / seconds / args.users, 2),
        "actions_per_s": {k: round(v / seconds, 1) for k, v in sorted(total.actions.items())},
        "action_errors": dict(total.action_errors.most_common()),
        "action_ms": {k: percentiles(v) for k, v in sorted(total.action_ms.items())},
        "errands": dict(sorted(total.errands.items())),
        "recv_per_s": {k: round(v / seconds, 1) for k, v in sorted(total.recv.items())},
        "recv_total_per_s": round(sum(total.recv.values()) / seconds, 1),
        "sent_per_s": {k: round(v / seconds, 1) for k, v in sorted(total.sent.items())},
        "own_state_gap_ms": percentiles(total.state_gap), "input_to_moving_ms": percentiles(total.move_lag),
        "peer_move_gap_ms": percentiles(total.peer_gap),
        "http_per_s": round(sum(len(v) for v in total.http_ms.values()) / seconds, 1),
        "http_ms": percentiles([s for v in total.http_ms.values() for s in v]),
        "http_ms_by_path": {path: percentiles(v) for path, v in sorted(total.http_ms.items())},
        "http_status": {str(k): v for k, v in total.http_status.items()}, "closes": {str(k): v for k, v in total.closes.items()},
        "generator_loop_lag_ms": percentiles(total.loop_lag),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
