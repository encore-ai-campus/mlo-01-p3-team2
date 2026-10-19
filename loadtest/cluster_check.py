"""여러 프로세스 확인(계획 docs/metaverse-multiprocess-plan.md M4).

소켓 프로세스 둘(daphne 9101·9102)과 작업 프로세스 하나(campus_jobs)를 이 컨테이너 안에 띄우고,
서로 다른 프로세스에 붙은 두 사람(A·B) 사이에서 기능이 한 프로세스일 때와 같은지 본다. 이 스크립트 자신도
Redis 채널 계층을 쓰는 세 번째 프로세스라 HTTP·세션 정리 쪽 알림(쪽지·세션 만료)을 직접 보낸다.

사용(dev/ 에서): docker compose -f loadtest/compose.yaml --profile check run --rm cluster-check
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model  # noqa: E402
from django.middleware.csrf import _get_new_csrf_string  # noqa: E402
from importlib import import_module  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from accounts.avatars import DEFAULT_AVATAR  # noqa: E402
from accounts.models import Profile  # noqa: E402
from accounts.session_policy import notify_expiry, start_login  # noqa: E402
from campus import cluster  # noqa: E402
from campus.positions import get_position, save_position  # noqa: E402
from direct_messages.live import notify as notify_message  # noqa: E402

PORTS = (9101, 9102)
HOST = "localhost"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("OK   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def spawn(port):
    return subprocess.Popen(["daphne", "-b", "127.0.0.1", "-p", str(port), "config.asgi:application"], cwd="/app",
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def wait_port(port, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(.2)
    raise SystemExit(f"port {port} did not start")


def login(username, position):
    user, created = get_user_model().objects.get_or_create(username=username)
    if created:
        user.set_unusable_password()
        user.save()
    Profile.objects.update_or_create(user=user, defaults={"nickname": username, "avatar": DEFAULT_AVATAR, "setup_complete": True, "guide_completed": True})
    save_position(user, position)
    session = import_module(settings.SESSION_ENGINE).SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    start_login(session, user)
    return user, session.session_key


async def socket(port, key):
    ws = await connect(f"ws://{HOST}:{port}/ws/campus/?control=server", origin=f"http://{HOST}:{port}",
                       additional_headers={"Cookie": f"{settings.SESSION_COOKIE_NAME}={key}"}, open_timeout=10)
    welcome = await expect(ws, lambda m: m["type"] == "welcome", 10, "welcome")
    return ws, welcome


async def expect(ws, predicate, timeout=4.0, what=""):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(what)
        message = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        for candidate in [message, *message.get("effects", ())] if message.get("type") == "moves" else [message]:  # 점프·찌르기는 0.1초 묶음에
            if predicate(candidate):
                return candidate


async def attempt(name, coroutine, detail=""):
    try:
        check(name, await coroutine, detail)
    except (TimeoutError, asyncio.TimeoutError) as error:
        check(name, False, f"시간 초과: {error}")


async def drain(ws, quiet=.3):
    """쌓인 메시지를 비운다(앞선 확인이 남긴 상태가 다음 확인에 섞이지 않게)."""
    while True:
        try:
            await asyncio.wait_for(ws.recv(), quiet)
        except (TimeoutError, asyncio.TimeoutError):
            return


async def walk(ws, keys, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        await ws.send(json.dumps({"type": "input", "keys": keys}))
        await asyncio.sleep(.1)
    await ws.send(json.dumps({"type": "input", "keys": []}))


def logout_over_http(port, key):
    secret = _get_new_csrf_string()
    request = urllib.request.Request(f"http://127.0.0.1:{port}/accounts/logout/", data=b"", method="POST", headers={
        "Host": HOST, "X-CSRFToken": secret, "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": f"{settings.SESSION_COOKIE_NAME}={key}; {settings.CSRF_COOKIE_NAME}={secret}"})
    try:
        return urllib.request.urlopen(request, timeout=5).status
    except urllib.error.HTTPError as error:
        return error.code


async def main():
    assert settings.CAMPUS_REDIS_URL, "CAMPUS_REDIS_URL 이 필요하다"
    spot = {"floor": "campus", "x": 1998.75, "y": 910.5, "dir": "right"}
    alice, a_key = await sync_to_async(login)("check-a", spot)
    bob, b_key = await sync_to_async(login)("check-b", {**spot, "x": spot["x"] + 24, "dir": "left"})
    jobs = subprocess.Popen(["python", "manage.py", "campus_jobs"], cwd="/app", stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    procs = {port: spawn(port) for port in PORTS}
    for port in PORTS:
        wait_port(port)
    try:
        a, a_welcome = await socket(PORTS[0], a_key)
        b, b_welcome = await socket(PORTS[1], b_key)
        a_id, b_id = a_welcome["selfId"], b_welcome["selfId"]
        check("다른 프로세스 사람이 welcome 에 있다", any(p["id"] == a_id for p in b_welcome["players"]))
        await attempt("다른 프로세스의 입장(join)이 온다", expect(a, lambda m: m["type"] == "join" and m["player"]["id"] == b_id))

        async def moved():
            walker = asyncio.create_task(walk(a, ["d"], 1.0))
            message = await expect(b, lambda m: m["type"] == "moves" and any(p["id"] == a_id for p in m["players"]), 4, "moves")
            await walker
            return message
        await attempt("다른 프로세스 사람의 이동(moves)이 온다", moved())

        await a.send(json.dumps({"type": "chat", "text": "다른 프로세스에 인사"}))
        await attempt("채팅이 다른 프로세스에 간다", expect(b, lambda m: m["type"] == "chat" and m["message"]["text"] == "다른 프로세스에 인사"))

        scope = {"context": "world", "floor": "campus"}
        await asyncio.sleep(.8)  # 점프는 착지 시간이 지나야 다시 된다
        await a.send(json.dumps({"type": "control", "requestId": "jump-1", "action": "jump", "data": scope}))
        await attempt("점프가 다른 프로세스에 간다", expect(b, lambda m: m["type"] == "jump" and m["actorId"] == a_id))

        await a.send(json.dumps({"type": "control", "requestId": "poke-1", "action": "poke", "data": scope}))
        await attempt("찌르기가 가까운 다른 프로세스 사람에게 간다", expect(b, lambda m: m["type"] == "poke" and m["actorId"] == a_id))

        await sync_to_async(notify_message)(bob.pk, "check-conversation")
        await attempt("쪽지 알림(HTTP 쪽 프로세스에서 보냄)이 온다",
                      expect(b, lambda m: m["type"] == "private_message" and m["conversationId"] == "check-conversation"))

        # 같은 세션이 다른 프로세스에 다시 붙으면(세션 고정 배정이 장애로 바뀐 경우) 옛 연결이 4409 로 닫힌다
        b2, b2_welcome = await socket(PORTS[0], b_key)
        closed = None
        try:
            await expect(b, lambda m: False, 4, "old B closes")
        except Exception as error:  # noqa: BLE001
            closed = getattr(error, "rcvd", None)
        check("같은 세션의 다른 프로세스 연결은 교체된다(4409)", closed is not None and closed.code == 4409, f"close={getattr(closed, 'code', None)}")
        await attempt("교체 뒤 A 는 옛 B 의 퇴장을 받는다", expect(a, lambda m: m["type"] == "leave" and m["id"] == b_id))
        b, b_id = b2, b2_welcome["selfId"]

        # 프로세스가 죽으면 3초 안에 그 사람이 사라진다
        b3, b3_welcome = await socket(PORTS[1], (await sync_to_async(login)("check-c", {**spot, "y": spot["y"] - 30}))[1])
        c_id = b3_welcome["selfId"]
        await expect(a, lambda m: m["type"] == "join" and m["player"]["id"] == c_id, 4, "join C")
        procs[PORTS[1]].send_signal(signal.SIGKILL)
        started = time.monotonic()
        try:
            await expect(a, lambda m: m["type"] == "leave" and m["id"] == c_id, 6, "leave C")
            elapsed = time.monotonic() - started
            check("죽은 프로세스의 사람은 3~4초 안에 사라진다", cluster.SILENT_SECONDS <= elapsed <= cluster.SILENT_SECONDS + cluster.SNAPSHOT_SECONDS + .5,
                  f"{elapsed:.1f}초")
        except (TimeoutError, asyncio.TimeoutError):
            check("죽은 프로세스의 사람은 3~4초 안에 사라진다", False, "6초 안에 오지 않았다")
        procs[PORTS[1]] = spawn(PORTS[1])
        wait_port(PORTS[1])

        # 다른 프로세스(세션 정리·HTTP)에서 보낸 세션 만료가 소켓에 닿는다
        await sync_to_async(notify_expiry)(b_key, "idle")
        await attempt("다른 프로세스의 세션 만료 알림이 닿는다", expect(b, lambda m: m["type"] == "session_expired" and m["reason"] == "idle"))

        # 로그아웃 요청이 다른 프로세스로 가도 마지막 위치(Redis 의 최신 위치)를 저장한다
        await drain(a)
        await walk(a, ["s"], .8)
        last = await expect(a, lambda m: m["type"] == "control_state" and not m["state"]["main"]["moving"], 4, "A stops")
        await asyncio.sleep(.3)  # 0.1초 묶음이 Redis 에 쓴다. 5초 체크포인트보다 이르다
        status = await sync_to_async(logout_over_http)(PORTS[1], a_key)
        saved = await sync_to_async(lambda: get_position(get_user_model().objects.get(pk=alice.pk)))()
        main = last["state"]["main"]
        check("다른 프로세스로 간 로그아웃이 마지막 위치를 저장한다", status in (200, 302) and abs(saved["x"] - main["x"]) < .01 and abs(saved["y"] - main["y"]) < .01,
              f"status={status} 저장={saved['x']:.2f},{saved['y']:.2f} 마지막={main['x']:.2f},{main['y']:.2f}")
    finally:
        for proc in [*procs.values(), jobs]:
            proc.terminate()
        for proc in [*procs.values(), jobs]:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과", flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
