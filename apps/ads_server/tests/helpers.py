import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def run_python(code, settings_module, env=None):
    """새 프로세스에서 코드를 실행한다. 설정 로딩 동작(환경변수·기본값)을 확인할 때 쓴다.

    개발자의 .env 나 셸 환경이 결과를 바꾸지 않도록 필요한 변수만 넘긴다.
    """
    child_env = {"PATH": os.environ.get("PATH", ""), "DJANGO_SETTINGS_MODULE": settings_module}
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BASE_DIR, env=child_env, capture_output=True, text=True, timeout=60
    )


PROD_ENV = {
    "SECRET_KEY": "Zk3-Qm8vXr1TnB6yLp0aWd9sHc4eUj7fGi2oNx5uKb-Ye_Va8Rt1Mq",  # 50자 이상·문자 다양(Django W009)
    "ALLOWED_HOSTS": "ads.example.com",
    "DATABASE_PATH": "/tmp/ads-test.sqlite3",
}
