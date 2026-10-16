"""실험용: DB 연결에 TLS 를 쓰지 않는다. 운영 설정이 아니다 — 연결마다의 TLS 비용을 잴 때만 쓴다."""
from config.settings import *  # noqa: F401,F403
from config.settings import DATABASES

DATABASES["default"]["OPTIONS"] = {**DATABASES["default"]["OPTIONS"], "ssl_mode": "DISABLED"}
