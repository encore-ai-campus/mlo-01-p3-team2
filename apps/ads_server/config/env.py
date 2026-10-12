"""환경변수 로드. `.env`는 python-dotenv로 읽되 실제 환경변수가 우선한다(override=False)."""
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path=None):
    """`.env`가 없어도 오류가 아니다. manage.py·wsgi.py·asgi.py가 설정을 불러오기 전에 호출한다."""
    return load_dotenv(path or BASE_DIR / ".env", override=False)
