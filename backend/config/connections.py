"""한 스레드가 DB 연결을 이어 쓰게 한다(계획 docs/metaverse-optimization-plan.md 4d·4f).

ASGI 는 `CONN_MAX_AGE=0` 이라 연결을 쓰고 바로 닫고, 다음에 새로 연다. 운영에서는 새 연결마다 라우터와 TLS 핸드셰이크를 해서 비싸다.
이 설정은 **부른 스레드의 연결 객체에만** 적용된다(HTTP 요청·다른 스레드는 그대로). 연결이 끊기거나 오류가 나면
`close_old_connections()` 가 닫고 다음에 새로 연다(건강 검사).
"""
from django.db import connections

KEEP_SECONDS = 60


def keep_thread_connection():
    database = connections["default"]
    if database.settings_dict.get("CONN_MAX_AGE") != KEEP_SECONDS:
        database.settings_dict = {**database.settings_dict, "CONN_MAX_AGE": KEEP_SECONDS, "CONN_HEALTH_CHECKS": True}
