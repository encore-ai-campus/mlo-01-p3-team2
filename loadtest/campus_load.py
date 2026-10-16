"""메타버스 백엔드 부하 생성기. 브라우저와 같은 주기로 N명을 흉내 낸다(load 컨테이너 안에서 run.py 가 실행).

브라우저 동작(frontend/dist):
- presence.js: 접속 후 5초마다 ping. 입력은 화면 프레임마다 publish(t)를 부르고 100ms 제한만 있어서, 키를 안 눌러도
  0.1초마다 input 을 보낸다(`--client current`). 키가 바뀌면 바로 보낸다. `--client new`는 계획 1c(키·찌르기가 있을 때만 0.1초마다).
- session-policy.js·raffle.js·messages.js: 15초마다 HTTP 조회 세 개(`--client current`). `new` 는 계획 4g: 소켓이 붙어 있으면 조회하지 않는다.
- session-policy.js: 키·마우스 입력이 있으면 활동 POST(15초에 한 번까지). 여기서는 이동 중인 사람이 보낸다.
- 끊기면 1→2→4→…→10초 간격으로 다시 연결하고, 4401·4409 면 멈춘다.

이동은 사용자마다 "쉬기 → 2~4초 이동"을 되풀이한다. `--moving` 은 이동 중인 시간의 비율이다.
측정 구간의 시작·끝에 `MEASURE_START`·`MEASURE_END` 를 찍고(run.py 가 이때 서버 CPU·DB 를 읽는다) 마지막 줄에 JSON 요약을 낸다.
"""
import argparse
import asyncio
import json
import math
import multiprocessing as mp
import random
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from autobahn.asyncio.websocket import WebSocketClientFactory, WebSocketClientProtocol

HOST, PORT = "backend", 9003
MOVE_KEYS = (["d"], ["a"], ["w"], ["s"], ["d", "w"], ["a", "s"])
POLLS = ("/accounts/session/status/", "/api/raffle/", "/api/messages/status/")
ACTIVITY = "/accounts/session/activity/"
CSRF = "a" * 32  # 부하 시험용 CSRF 비밀(쿠키와 헤더에 같은 값)
MOVE_PREFIX = b'{"type": "move"'  # move 와 moves(0.1초 묶음) 둘 다
MOVES_PREFIX = b'{"type": "moves"'


class Stats:
    def __init__(self):
        self.recv, self.sent, self.closes, self.http_status = Counter(), Counter(), Counter(), Counter()
        self.state_gap, self.move_lag, self.peer_gap, self.loop_lag = [], [], [], []
        self.http_ms = {}  # 경로 → 응답 시간들
        self.welcomed = 0


stats = Stats()
measuring = False


class User:
    def __init__(self, key, rng, watch):
        self.key, self.rng, self.watch = key, rng, watch
        self.proto, self.ready, self.keys = None, False, []
        self.last_state = self.move_started = None
        self.peers = {}
        self.closed = None


class Client(WebSocketClientProtocol):
    def onOpen(self):
        self.factory.user.proto = self

    def onMessage(self, payload, is_binary):
        user, now = self.factory.user, time.monotonic()
        if payload.startswith(MOVE_PREFIX) and not user.watch:
            if measuring:
                stats.recv["moves" if payload.startswith(MOVES_PREFIX) else "move"] += 1
            return
        message = json.loads(payload)
        kind = message.get("type")
        if measuring:
            stats.recv[kind] += 1
        if kind == "welcome":
            user.ready = True
            stats.welcomed += 1
        elif kind == "control_state":
            if user.keys and user.last_state is not None and measuring:
                stats.state_gap.append(now - user.last_state)
            user.last_state = now if user.keys else None
            if user.move_started is not None and message["state"]["main"].get("moving"):
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
    send(user, {"type": "input", "keys": keys}, "input")  # 바뀌면 바로(presence.js setInput)


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
        if user.keys:
            send(user, {"type": "input", "keys": user.keys}, "input")


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


def fetch(path, key):
    headers = {"Cookie": f"campus_sessionid={key}; campus_csrftoken={CSRF}"}
    data = None
    if path == ACTIVITY:
        headers.update({"X-CSRFToken": CSRF, "Origin": f"http://{HOST}:{PORT}", "Content-Type": "application/json"})
        data = b"{}"
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", data=data, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except OSError:
        status = "error"
    return status, time.monotonic() - started


async def request(user, path):
    status, seconds = await asyncio.get_running_loop().run_in_executor(None, fetch, path, user.key)
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
                     asyncio.create_task(behave(user, args.moving))]
        code = await user.closed
        for task in tasks:
            task.cancel()
        user.keys = []
        if code in (4401, 4409):
            return
        await asyncio.sleep(retry)
        retry = min(retry * 2, 10)


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
    parser.add_argument("--ramp", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--measure", type=float, default=60)
    parser.add_argument("--procs", type=int, default=4)
    parser.add_argument("--polls", type=float, default=15, help="HTTP 조회 셋의 간격(초). 0 이면 하지 않는다")
    parser.add_argument("--watchers", type=int, default=2, help="프로세스마다 다른 사람의 move 간격을 재는 사용자 수")
    args = parser.parse_args()
    with open("/data/sessions.json", encoding="utf-8") as f:
        keys = json.load(f)[:args.users]
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
        "users": args.users, "moving": args.moving, "client": args.client, "welcomed": total.welcomed,
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
