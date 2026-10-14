import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # apps/ads_server
ROUTE_PARAM = re.compile(r"<(?:(\w+):)?(\w+)>")  # 경로의 `<str:campaign_id>` 같은 자리


def every_route(patterns=None, prefix=""):
    """URL 설정 전체(포함한 하위 설정까지)의 경로 문자열. 정규식(관리자 사이트의 앱 목록 등)은 건너뛴다."""
    from django.urls import URLResolver, get_resolver
    from django.urls.resolvers import RoutePattern

    for p in patterns if patterns is not None else get_resolver().url_patterns:
        if not isinstance(p.pattern, RoutePattern):
            continue
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from every_route(p.url_patterns, route)
        else:
            yield route


def run_python(code, settings_module, env=None, cwd=BASE_DIR):
    """새 프로세스에서 코드를 실행한다. 설정 로딩 동작(환경변수·기본값)을 확인할 때 쓴다.

    개발자의 .env 나 셸 환경이 결과를 바꾸지 않도록 필요한 변수만 넘긴다. `settings_module` 이 `None` 이면 설정 모듈 환경변수를 넘기지 않는다(진입점이 정하는 값을 볼 때).
    """
    child_env = {"PATH": os.environ.get("PATH", "")}
    if settings_module is not None:
        child_env["DJANGO_SETTINGS_MODULE"] = settings_module
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=child_env, capture_output=True, text=True, timeout=60
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
    "CSRF_TRUSTED_ORIGINS": "https://ads.example.com",  # 브라우저가 여는 https 주소(prod 필수, 6-5d)
}
