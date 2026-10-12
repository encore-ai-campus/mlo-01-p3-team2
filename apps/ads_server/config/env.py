"""환경변수 로드. `.env`는 python-dotenv로 읽되 실제 환경변수가 우선한다(override=False)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_SETTINGS_MODULE = "config.settings.prod"


def load_env(path=None):
    """`.env`가 없어도 오류가 아니다. manage.py·wsgi.py·asgi.py가 설정을 불러오기 전에 호출한다."""
    return load_dotenv(path or BASE_DIR / ".env", override=False)


def load_env_for_web(path=None):
    """웹 진입점(`wsgi`·`asgi`)의 `load_env`. **설정 모듈만은 `.env`를 따르지 않는다**(설계 §10 "웹 진입점의 설정 모듈", 6-3a):
    `.env`를 읽기 전에 실제 환경변수에 있던 값을 쓰고, 없으면 prod다. 예시 `.env`를 복사한 운영 웹 서버가 dev(공개된 개발 키, Secure 쿠키·HTTPS 없음)로 조용히 뜨지 않게 한다.
    `manage.py`는 그대로 `.env`를 따르고 기본은 dev다(로컬 실행. 운영 호스트의 명령은 실제 환경변수로 prod를 지정한다)."""
    explicit = os.environ.get("DJANGO_SETTINGS_MODULE")
    load_env(path)
    os.environ["DJANGO_SETTINGS_MODULE"] = explicit or WEB_SETTINGS_MODULE
