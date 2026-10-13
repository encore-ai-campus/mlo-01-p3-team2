"""Dispatch DB commits from HTTP/worker threads onto the WebSocket event loop."""
import asyncio
import threading

_lock = threading.Lock()
_loop = None
_layer = None


def bind_socket_loop(layer):
    global _loop, _layer
    with _lock:
        _loop, _layer = asyncio.get_running_loop(), layer


def publish_change():
    with _lock:
        loop, layer = _loop, _layer
    if loop is None or loop.is_closed() or not loop.is_running():
        return  # The next connection receives the persisted snapshot.

    def enqueue():
        asyncio.create_task(layer.group_send("campus.main", {"type": "raffle.changed"}))

    try:
        loop.call_soon_threadsafe(enqueue)
    except RuntimeError:
        pass  # A reload can close the old loop between the checks.
