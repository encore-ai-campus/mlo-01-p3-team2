"""실험용: DB 연결을 재사용한다(CONN_MAX_AGE). 운영 설정이 아니다 — 연결 재사용의 효과를 잴 때만 쓴다."""
from config.settings import *  # noqa: F401,F403
from config.settings import DATABASES

DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
