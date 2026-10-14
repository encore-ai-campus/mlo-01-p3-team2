"""시험 설정: 운영 설정에 시험용 비밀값과 빈 임시 정적 폴더(WhiteNoise 는 없는 폴더를 경고한다).
관리 사이트 경로·본문 상한은 환경과 상관없이 고정한다 — 시험이 셸·`.env` 의 값에 따라 깨지지 않게(6-16i, R21. 백엔드 시험 설정도 `.env` 를 읽지 않는다)."""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("FRONTEND_SECRET_KEY", "test-only-frontend-key-" + "x" * 40)

from .settings import *  # noqa: E402,F403

STATIC_ROOT = tempfile.mkdtemp(prefix="ads-frontend-test-static-")
atexit.register(shutil.rmtree, STATIC_ROOT, ignore_errors=True)
ADMIN_URL_PATH = "dev-admin/"  # 백엔드 시험 설정과 같은 값
MAX_BODY_BYTES = DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024 + 64 * 1024  # 업로드 상한 기본값 + multipart 여유
