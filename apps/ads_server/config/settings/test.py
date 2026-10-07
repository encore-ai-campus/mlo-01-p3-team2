"""테스트 설정. **환경변수·.env 를 읽지 않는다**(개발자 로컬 값이 테스트 결과를 바꾸지 않게)."""
from .base import *  # noqa: F401,F403
from .base import sqlite_config

SECRET_KEY = "test-only-secret-key-" + "x" * 40
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {"default": sqlite_config(":memory:", wal=False)}
