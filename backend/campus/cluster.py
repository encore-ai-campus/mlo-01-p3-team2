"""여러 프로세스가 캠퍼스 한 곳을 나눠 맡을 때 서로의 사람을 알리는 흐름(계획 docs/metaverse-multiprocess-plan.md M3).

Redis 주소(settings.CAMPUS_REDIS_URL)가 없으면 아무 일도 하지 않는다: 한 프로세스가 모든 사람을 가진다.

프로세스마다 채널 계층(campus.cluster 그룹)에 '프로세스 채널' 하나를 두고 서로 알린다.
- 입장·퇴장: 생기는 즉시. 받은 프로세스는 자기 소켓에 join·leave 를 보낸다(welcome 과 join 사이에 빈틈이 없게).
- 이동: 0.1초 묶음(flush_moves)마다 이 프로세스 사람의 변경만. 받은 쪽은 다음 자기 묶음에 합친다.
- 전체 목록: 1초마다. 새로 뜬 프로세스는 이것을 받을 시간을 기다린 뒤 첫 소켓을 받는다.
- 3초 동안 소식이 없는 프로세스의 사람은 지운다(프로세스가 죽었을 때 유령 방지).
Redis 연결 풀에서는 같은 프로세스의 메시지도 순서가 바뀔 수 있다. 그래서 메시지마다 번호(seq)를 달고,
떠난 사람의 번호를 기억해 그보다 앞선 목록·입장이 늦게 와도 되살리지 않는다. 이동은 아는 사람만 고친다.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from channels.layers import get_channel_layer
from django.conf import settings

GROUP = "campus.cluster"
PROC = uuid4().hex  # 다시 뜨면 새 번호: 죽은 프로세스의 사람은 소식이 끊겨 지워진다
SNAPSHOT_SECONDS = 1.0
SILENT_SECONDS = 3.0
READY_SECONDS = 1.2  # 다른 프로세스의 전체 목록을 한 번 받을 시간
TOMBSTONE_SECONDS = 10.0
POSITION_TTL_SECONDS = 3600
logger = logging.getLogger(__name__)


def enabled():
    return bool(getattr(settings, "CAMPUS_REDIS_URL", ""))


def session_hash(key):
    return sha256(key.encode()).hexdigest()


class Cluster:
    """한 방(room)의 다른 프로세스 사본과 이 프로세스의 알림."""

    def __init__(self):
        self.remote = {}  # player_id → {"state", "channel", "session", "proc"}
        self.remote_moves = {}  # 다음 자기 묶음에 실을 다른 프로세스 사람의 상태
        self.heard = {}  # proc → 마지막으로 소식을 들은 시각
        self.tombstones = {}  # player_id → (떠난 메시지의 proc, seq, 시각)
        self.seq = 0
        self.started = None
        self.tasks = []
        self.channel = None
        self.async_redis = None

    # ── 보내기 ──────────────────────────────────────────────
    def message(self, kind, **fields):
        self.seq += 1
        return {"type": "cluster.message", "kind": kind, "proc": PROC, "seq": self.seq, **fields}

    async def send(self, kind, **fields):
        try:
            await get_channel_layer().group_send(GROUP, self.message(kind, **fields))
        except Exception:  # noqa: BLE001 — Redis 가 잠깐 안 되어도 이 프로세스의 사람은 계속 움직인다. 1초 목록이 다시 맞춘다
            logger.warning("Could not publish campus cluster %s", kind, exc_info=True)

    @staticmethod
    def entry(consumer):
        return {"id": consumer.player_id, "state": consumer.seen_by_peers or consumer.state, "channel": consumer.channel_name,
                "session": session_hash(consumer.session_key)}

    async def joined(self, consumer):
        if enabled():
            await self.send("join", entry=self.entry(consumer))

    async def left(self, player_id):
        if enabled():
            await self.send("leave", id=player_id)

    async def moved(self, states):
        if enabled() and states:
            await self.send("moves", players=states)

    # ── 받기 ────────────────────────────────────────────────
    def stale(self, player_id, proc, seq):
        tomb = self.tombstones.get(player_id)
        return tomb is not None and tomb[0] == proc and tomb[1] > seq

    def apply(self, message):
        """다른 프로세스의 메시지를 사본에 반영하고, 이 프로세스의 소켓에 보낼 join·leave 를 돌려준다."""
        proc, seq, kind = message["proc"], message["seq"], message["kind"]
        out = []
        if proc == PROC:
            return out
        tell = out.append
        self.heard[proc] = time.monotonic()
        if kind == "join":
            self.add(message["entry"], proc, seq, tell)
        elif kind == "leave":
            self.tombstones[message["id"]] = (proc, seq, time.monotonic())
            self.drop(message["id"], tell)
        elif kind == "moves":
            for state in message["players"]:
                row = self.remote.get(state["id"])
                if row is not None and row["proc"] == proc:
                    row["state"] = state
                    self.remote_moves[state["id"]] = state
        elif kind == "snapshot":
            listed = {entry["id"] for entry in message["players"]}
            for player_id in [pid for pid, row in self.remote.items() if row["proc"] == proc and pid not in listed]:
                self.drop(player_id, tell)
            for entry in message["players"]:
                self.add(entry, proc, seq, tell)
        return out

    def add(self, entry, proc, seq, tell):
        if self.stale(entry["id"], proc, seq):
            return
        known = entry["id"] in self.remote
        self.remote[entry["id"]] = {"state": entry["state"], "channel": entry["channel"], "session": entry["session"], "proc": proc}
        if not known:
            tell({"type": "join", "player": entry["state"]})

    def drop(self, player_id, tell):
        self.remote_moves.pop(player_id, None)
        if self.remote.pop(player_id, None) is not None:
            tell({"type": "leave", "id": player_id})

    def expire(self, now=None):
        """소식이 끊긴 프로세스의 사람과 오래된 퇴장 기록을 지우고, 보낼 leave 를 돌려준다."""
        now = time.monotonic() if now is None else now
        out = []
        tell = out.append
        for proc in [p for p, at in self.heard.items() if now - at > SILENT_SECONDS]:
            del self.heard[proc]
            for player_id in [pid for pid, row in self.remote.items() if row["proc"] == proc]:
                self.drop(player_id, tell)
        for player_id in [pid for pid, tomb in self.tombstones.items() if now - tomb[2] > TOMBSTONE_SECONDS]:
            del self.tombstones[player_id]
        return out

    # ── 한 프로세스에서 한 번 ─────────────────────────────────
    async def start(self, room, deliver):
        """처음 붙는 소켓이 부른다. 듣기·1초 목록을 시작하고, 다른 프로세스 목록을 받을 시간을 기다린다.
        deliver(payloads) 는 이 프로세스의 모든 소켓에 보낸다."""
        if not enabled():
            return
        if self.started is None:
            self.started = time.monotonic()
            layer = get_channel_layer()
            self.channel = await layer.new_channel()
            await layer.group_add(GROUP, self.channel)
            self.tasks = [asyncio.create_task(self.listen(layer, deliver)), asyncio.create_task(self.heartbeat(room, deliver))]
        wait = READY_SECONDS - (time.monotonic() - self.started)
        if wait > 0:
            await asyncio.sleep(wait)

    async def listen(self, layer, deliver):
        # PubSub 계층의 receive 는 취소되면 구독을 끊는다: 시간 제한 없이 기다리고, 끊김 확인은 heartbeat 가 한다
        while True:
            message = await layer.receive(self.channel)
            try:
                await deliver(self.apply(message))
            except Exception:  # noqa: BLE001 — 메시지 하나가 듣기를 멈추게 하지 않는다
                logger.exception("Could not apply a campus cluster message")

    async def heartbeat(self, room, deliver):
        while True:
            await asyncio.sleep(SNAPSHOT_SECONDS)
            await deliver(self.expire())
            if room.players:
                await self.send("snapshot", players=[self.entry(socket) for socket in list(room.sockets.values())])

    # ── 세션별 최신 위치(로그아웃·세션 만료가 다른 프로세스에서 일어나도 마지막 위치를 저장한다) ──
    async def save_positions(self, rows):
        if not enabled() or not rows:
            return
        try:
            if self.async_redis is None:
                from redis import asyncio as aioredis
                self.async_redis = aioredis.Redis.from_url(settings.CAMPUS_REDIS_URL)
            pipe = self.async_redis.pipeline(transaction=False)
            for key, user_id, position, observed_at in rows:
                pipe.set(position_key(key), json.dumps({"user": str(user_id), "position": position, "observedAt": observed_at.isoformat()}),
                         ex=POSITION_TTL_SECONDS)
            await pipe.execute()
        except Exception:  # noqa: BLE001 — 저장하지 못한 위치는 다음 묶음에서 다시 쓴다(이 프로세스의 사본은 그대로다)
            logger.warning("Could not save live campus positions to Redis", exc_info=True)


def position_key(session_key):
    return "campus:pos:" + session_hash(session_key)


_sync_redis = None


def stored_position(session_key, user_id):
    """다른 프로세스가 쓴 최신 위치(동기 — HTTP·DB 스레드에서 부른다)."""
    global _sync_redis
    if not enabled():
        return None
    try:
        if _sync_redis is None:
            import redis
            _sync_redis = redis.Redis.from_url(settings.CAMPUS_REDIS_URL, socket_timeout=1)
        raw = _sync_redis.get(position_key(session_key))
    except Exception:  # noqa: BLE001 — Redis 가 안 되면 DB 의 5초 체크포인트로 갈음한다
        logger.warning("Could not read the live campus position from Redis", exc_info=True)
        return None
    if not raw:
        return None
    data = json.loads(raw)
    if data["user"] != str(user_id):
        return None
    return data["position"], datetime.fromisoformat(data["observedAt"])
