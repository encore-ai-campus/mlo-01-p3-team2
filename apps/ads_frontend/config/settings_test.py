"""시험 설정: 운영 설정에 시험용 비밀값과 빈 임시 정적 폴더(WhiteNoise 는 없는 폴더를 경고한다)."""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("FRONTEND_SECRET_KEY", "test-only-frontend-key-" + "x" * 40)

from .settings import *  # noqa: E402,F403

STATIC_ROOT = tempfile.mkdtemp(prefix="ads-frontend-test-static-")
atexit.register(shutil.rmtree, STATIC_ROOT, ignore_errors=True)
