"""테스트 설정. 동작을 바꾸는 환경변수·.env 는 읽지 않는다(개발자 로컬 값이 테스트 결과를 바꾸지 않게). **DB 접속 값(DB_*)만 읽는다** — 접속 대상은 동작이 아니라 환경이다."""
import atexit
import shutil
import tempfile
import uuid

from .base import *  # noqa: F401,F403
from config.access_map import build_access_map

from ._env import env_int, env_list, env_str
from .base import mongo_config, mysql_config

SECRET_KEY = "test-only-secret-key-" + "x" * 40

# 테스트는 같은 알고리즘(argon2)의 가벼운 설정을 쓴다. 해시 접두사는 운영과 같다.
PASSWORD_HASHERS = ["tests.hashers.FastArgon2PasswordHasher"]
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

ADMIN_URL_PATH = "test-admin/"
ACCESS_MAP = build_access_map(ADMIN_URL_PATH)

# 테스트용 임시 저장소(프로세스 종료 시 정리)
MEDIA_ROOT = tempfile.mkdtemp(prefix="ads-test-media-")
atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
ASSET_PUBLIC_BASE_URL = "http://testserver"

# 접근 통제 테스트용 더미 모델 앱(소유자가 있는 모델)
INSTALLED_APPS = [*INSTALLED_APPS, "tests.support_app"]

# 시험용 MySQL 8.4 (계획 S3: 개발 PC의 컨테이너, 공유 인프라 서버에서는 돌리지 않는다). Django 가 `test_<DB_NAME>` 을 만들고 끝나면 지운다.
DATABASES = {"default": mysql_config(
    env_str("DB_NAME", default="ads_server"),
    env_str("DB_USER", required=True),
    env_str("DB_PASSWORD", required=True),
    env_str("DB_HOST", default="127.0.0.1"),
    env_int("DB_PORT", 3306),
)}

# 시험용 MongoDB (DB-2). 접속 값(MONGO_*)만 읽고, 데이터베이스 이름은 프로세스마다 무작위로 정한다(남의 데이터와 겹치지 않게).
# 만든 데이터베이스는 시험이 끝날 때 tests.mongo_support 가 이 이름만 지운다.
EVENT_STORE = mongo_config(
    env_list("MONGO_HOSTS", default=["127.0.0.1:27017"]),
    f"ads_events_test_{uuid.uuid4().hex}",
    env_str("MONGO_USER"),
    env_str("MONGO_PASSWORD"),
    env_str("MONGO_AUTH_SOURCE", default="admin"),
    env_str("MONGO_REPLICA_SET"),
)

# 테스트 출력을 읽기 쉽게: axes 의 INFO 로그만 낮춘다.
# django.request 는 일부러 일으키는 500 로그로 출력이 어지러워지지 않게 CRITICAL 로 둔다.
LOGGING = {**LOGGING, "loggers": {"axes": {"level": "ERROR"}, "django.request": {"level": "CRITICAL"}}}
