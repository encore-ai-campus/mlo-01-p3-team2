"""광고 서버 프론트(설계 §6.6 "6-15 분리"): DB 없는 Django. 템플릿·정적 파일로 화면을 그리고, 요청(입력·쿠키)은 바꾸지 않고 백엔드로 넘긴다.
판단(CSRF·로그인·권한·검증)은 모두 백엔드가 한다 — 그래서 세션·인증·CSRF 미들웨어와 DB 가 없다."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import django
from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def env(name, default=""):
    return os.environ.get(name) or default


DEV_KEY = "dev-only-frontend-key-do-not-use-in-production"
DEBUG = env("FRONTEND_DEBUG", "0") == "1"
SECRET_KEY = env("FRONTEND_SECRET_KEY", DEV_KEY if DEBUG else "")
if not DEBUG and (SECRET_KEY == DEV_KEY or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("운영(FRONTEND_DEBUG=0)에서는 FRONTEND_SECRET_KEY(50자 이상)가 필요합니다.")
ALLOWED_HOSTS = [h.strip() for h in env("FRONTEND_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

BACKEND_URL = env("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
_backend = urlsplit(BACKEND_URL)
if _backend.scheme not in {"http", "https"} or not _backend.hostname or _backend.username or _backend.password or _backend.path or _backend.query or _backend.fragment:
    raise ImproperlyConfigured("BACKEND_URL 은 경로 없는 http(s) 서버 주소여야 합니다(예: http://10.0.0.5:8000).")
BACKEND_TIMEOUT = float(env("BACKEND_TIMEOUT", "30"))

ADMIN_URL_PATH = env("ADMIN_URL_PATH", "dev-admin/")  # 백엔드와 같아야 한다 — 관리 사이트·운영 화면의 경로
if ADMIN_URL_PATH.startswith("/") or not ADMIN_URL_PATH.endswith("/"):
    raise ImproperlyConfigured("ADMIN_URL_PATH 는 'ops-xxxx/' 처럼 / 로 끝나고 / 로 시작하지 않아야 합니다.")

# 본문 상한: 백엔드의 업로드 상한(ASSET_MAX_BYTES) + multipart 여유와 같게. 넘으면 백엔드로 흘려보내지 않고 같은 문구의 413 화면을 그린다
MAX_BODY_BYTES = int(env("ASSET_MAX_BYTES", str(2 * 1024 * 1024))) + 64 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_BODY_BYTES

INSTALLED_APPS = ["django.contrib.staticfiles", "ui"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # /static/ — 콘솔·운영 화면·Django admin 의 CSS·JS
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES = {}
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []  # ui.rendering 이 화면 전용 엔진을 쓴다(백엔드 시험도 같은 엔진으로 그린다)

STATIC_URL = "static/"
STATIC_ROOT = env("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [("admin", Path(django.__file__).parent / "contrib/admin/static/admin")]  # 통과시키는 관리 사이트도 이 정적 파일을 쓴다

LANGUAGE_CODE = "ko-kr"  # 백엔드와 같게(관리 템플릿의 번역 문구)
LOCALE_PATHS = [Path(django.__file__).parent / "contrib/admin/locale"]  # 운영 화면이 상속하는 관리 템플릿의 한국어 문구(admin 앱 없이)
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# 보안 헤더는 백엔드와 같은 값. 이미 붙은 헤더는 덮지 않는다(통과시킨 응답은 백엔드 것이 그대로)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF, CSP.NONCE],
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
# 끄는 배포 점검(사유):
# - W003 CSRF 미들웨어 없음: CSRF 는 백엔드가 검사한다 — 프론트는 입력·쿠키·토큰을 그대로 넘긴다
# - W004·W008 HSTS·HTTPS 리다이렉트: 앞단 nginx 가 맡는다(백엔드와 같다, 설계 §10 "배포 구성")
# - W027 nonce: 화면 전용 엔진(ui.rendering)이 요청의 nonce 를 문맥에 직접 넣는다 — 설정의 TEMPLATES 를 쓰지 않아 검사가 그것을 보지 못한다
SILENCED_SYSTEM_CHECKS = ["security.W003", "security.W004", "security.W008", "security.W027"]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"ui": {"handlers": ["console"], "level": "INFO"}},
}
