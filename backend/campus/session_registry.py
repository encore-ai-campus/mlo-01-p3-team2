"""Validated live positions available to HTTP and WebSocket session expiry."""
from hashlib import sha256
from threading import RLock

_lock = RLock()
_players = {}


def session_group(key):
    return "campus.session." + sha256(key.encode()).hexdigest()


def register(player_id, key, user_id):
    with _lock:
        _players[player_id] = {"key": key, "user_id": user_id, "position": None, "observed_at": None}


def update(player_id, position, observed_at):
    with _lock:
        if player_id in _players and observed_at is not None:
            _players[player_id].update(position={name: position[name] for name in ("floor", "x", "y", "dir")}, observed_at=observed_at)


def latest(key, user_id):
    with _lock:
        candidates = [item for item in _players.values() if item["key"] == key
                      and str(item["user_id"]) == str(user_id) and item["observed_at"] is not None]
        if not candidates:
            return None
        item = max(candidates, key=lambda item: item["observed_at"])
        return item["position"].copy(), item["observed_at"]


def unregister(player_id):
    with _lock:
        _players.pop(player_id, None)


def active_keys():
    with _lock:
        return {item["key"] for item in _players.values()}
