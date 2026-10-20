"""소켓의 DB 호출을 스레드 하나·연결 하나로(계획 docs/metaverse-optimization-plan.md 4f).

Channels 의 `database_sync_to_async` 는 ASGI 의 `CONN_MAX_AGE=0` 때문에 호출마다 DB 연결을 새로 연다. 운영에서는 연결마다 라우터와
TLS 핸드셰이크를 해서, 부하 시험에서 백엔드 CPU 의 가장 큰 몫이 이것이었다(20명: 운영 코어 70% 중 약 36%p).
소켓의 DB 호출은 원래도 스레드 하나에서 차례로 돌았으므로(thread_sensitive) 그 순서는 그대로 두고, 그 스레드의 연결만 이어 쓴다.
연결이 끊기거나 오류가 나면 다음 호출 전에 Django 가 닫고 새로 연다(건강 검사). HTTP 요청의 연결 정책은 바꾸지 않는다.
"""
import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections

from config.connections import keep_thread_connection

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="campus-socket-db")


def _call(fn, args, kwargs):
    keep_thread_connection()  # 이 스레드의 연결만 이어 쓴다(HTTP 요청은 그대로)
    close_old_connections()  # 오래됐거나 오류가 난 연결만 닫는다
    return fn(*args, **kwargs)


async def run(fn, *args, **kwargs):
    """`fn(*args, **kwargs)` 를 소켓 DB 스레드에서 실행한다(`database_sync_to_async(fn)(...)` 대신)."""
    return await asyncio.get_running_loop().run_in_executor(_executor, functools.partial(_call, fn, args, kwargs))
