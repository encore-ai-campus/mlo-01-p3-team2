import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def run_python(code, settings_module, env=None):
    """새 프로세스에서 코드를 실행한다. 설정 로딩 동작(환경변수·기본값)을 확인할 때 쓴다.

    개발자의 .env 나 셸 환경이 결과를 바꾸지 않도록 필요한 변수만 넘긴다. `settings_module` 이 `None` 이면 설정 모듈 환경변수를 넘기지 않는다(진입점이 정하는 값을 볼 때).
    """
    child_env = {"PATH": os.environ.get("PATH", "")}
    if settings_module is not None:
        child_env["DJANGO_SETTINGS_MODULE"] = settings_module
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BASE_DIR, env=child_env, capture_output=True, text=True, timeout=60
    )


# 접속 값 자리표시자: 설정 로딩만 시험하므로 실제로 연결하지 않는다(설정은 연결을 만들지 않는다).
DB_ENV = {"DB_NAME": "ads_x", "DB_USER": "u", "DB_PASSWORD": "p", "DB_HOST": "db.example.com"}

PROD_ENV = {
    "SECRET_KEY": "Zk3-Qm8vXr1TnB6yLp0aWd9sHc4eUj7fGi2oNx5uKb-Ye_Va8Rt1Mq",  # 50자 이상·문자 다양(Django W009)
    "ALLOWED_HOSTS": "ads.example.com",
    **DB_ENV,
    "ADMIN_URL_PATH": "ops-9f3a/",
    "MEDIA_ROOT": "/tmp/ads-test-media",
    "ASSET_PUBLIC_BASE_URL": "https://ads.example.com",
    "TRUSTED_PROXY_COUNT": "1",  # 앞단 nginx 1단(prod 필수, 6-5c)
}
