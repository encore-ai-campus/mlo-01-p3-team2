"""Dispatch DB commits from HTTP/worker threads onto the WebSocket event loop."""
import asyncio
import threading

_lock = threading.Lock()
_loop = None
_layer = None


COALESCE_SECONDS = 1.0
# 묶음 창: 첫 변경은 바로 보내고 창을 연다. 창이 열린 동안의 변경은 창이 닫힐 때 최신 상태로 한 번 보낸다(계획 4c).
# 변경마다 모든 소켓이 개인 스냅샷을 DB 에서 다시 만들기 때문이다. 이벤트 루프 안에서만 바꾼다.
_window = {"open": False, "pending": False}


def bind_socket_loop(layer):
    global _loop, _layer
    with _lock:
        loop = asyncio.get_running_loop()
        if loop is not _loop:
            _window.update(open=False, pending=False)  # 새 이벤트 루프(재시작·시험)는 처음부터
        _loop, _layer = loop, layer


def publish_change():
    with _lock:
        loop, layer = _loop, _layer
    if loop is None or loop.is_closed() or not loop.is_running():
        return  # The next connection receives the persisted snapshot.

    def enqueue():
        if _window["open"]:
            _window["pending"] = True
            return
        _window["open"] = True
        asyncio.create_task(layer.group_send("campus.main", {"type": "raffle.changed"}))
        loop.call_later(COALESCE_SECONDS, close_window)

    def close_window():
        _window["open"] = False
        if _window["pending"]:
            _window["pending"] = False
            enqueue()

    try:
        loop.call_soon_threadsafe(enqueue)
    except RuntimeError:
        pass  # A reload can close the old loop between the checks.
