"""Validated live positions available to HTTP and WebSocket session expiry."""
from hashlib import sha256
from threading import RLock

from .cluster import enabled as shared, stored_position

_lock = RLock()
_players = {}
_dirty = set()  # Redis 에 아직 쓰지 않은 최신 위치(여러 프로세스일 때만, 계획 M3)


def session_group(key):
    return "campus.session." + sha256(key.encode()).hexdigest()


def register(player_id, key, user_id):
    with _lock:
        _players[player_id] = {"key": key, "user_id": user_id, "position": None, "observed_at": None}


def update(player_id, position, observed_at):
    with _lock:
        if player_id in _players and observed_at is not None:
            _players[player_id].update(position={name: position[name] for name in ("floor", "x", "y", "dir")}, observed_at=observed_at)
            if shared():
                _dirty.add(player_id)


def latest(key, user_id):
    with _lock:
        candidates = [item for item in _players.values() if item["key"] == key
                      and str(item["user_id"]) == str(user_id) and item["observed_at"] is not None]
        if not candidates:
            # 이 프로세스에 없으면 다른 프로세스가 0.1초마다 쓴 값(로그아웃·만료가 다른 프로세스에서 일어난 경우)
            return stored_position(key, user_id)
        item = max(candidates, key=lambda item: item["observed_at"])
        return item["position"].copy(), item["observed_at"]


def unregister(player_id):
    with _lock:
        _players.pop(player_id, None)
        _dirty.discard(player_id)


def drain_dirty():
    """Redis 에 쓸 (세션 키, 사용자, 위치, 관측 시각) — 묶음(0.1초)마다 한 번 가져간다."""
    with _lock:
        rows = [(item["key"], item["user_id"], item["position"].copy(), item["observed_at"])
                for player_id in _dirty if (item := _players.get(player_id)) and item["observed_at"] is not None]
        _dirty.clear()
        return rows


def active_keys():
    with _lock:
        return {item["key"] for item in _players.values()}
