"""테스트 설정. **환경변수·.env 를 읽지 않는다**(개발자 로컬 값이 테스트 결과를 바꾸지 않게)."""
from .base import *  # noqa: F401,F403
from .base import sqlite_config

SECRET_KEY = "test-only-secret-key-" + "x" * 40

# 테스트는 같은 알고리즘(argon2)의 가벼운 설정을 쓴다. 해시 접두사는 운영과 같다.
PASSWORD_HASHERS = ["tests.hashers.FastArgon2PasswordHasher"]
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {"default": sqlite_config(":memory:", wal=False)}

# 테스트 출력을 읽기 쉽게: axes 의 INFO 로그만 낮춘다.
# django.request 는 일부러 일으키는 500 로그로 출력이 어지러워지지 않게 CRITICAL 로 둔다.
LOGGING = {**LOGGING, "loggers": {"axes": {"level": "ERROR"}, "django.request": {"level": "CRITICAL"}}}
