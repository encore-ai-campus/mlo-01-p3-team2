"""공통 설정. **환경변수를 읽지 않는다**(dev·prod 가 읽고, test 는 읽지 않는다)."""
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# dev 에서만 쓰는 임시 키. prod 가 이 값을 쓰면 기동 실패(prod.py).
INSECURE_DEV_KEY = "dev-only-insecure-key-do-not-use-in-production"

DEBUG = False

INSTALLED_APPS = [
    "foundation.apps.AuditedAdminConfig",  # = django.contrib.admin + 관리자 본인 비밀번호 변경 감사
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "foundation.apps.FoundationConfig",
    "assets.apps.AssetsConfig",
    "masters.apps.MastersConfig",
    "campaigns.apps.CampaignsConfig",
    "billing.apps.BillingConfig",
    "records.apps.RecordsConfig",
    "serving_api.apps.ServingApiConfig",
    "console.apps.ConsoleConfig",
]

MIDDLEWARE = [
    "foundation.middleware.RequestIdMiddleware",  # 가장 먼저: 모든 응답·로그에 요청 ID
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "foundation.middleware.RequestBodyLimitMiddleware",  # 본문을 읽는 모든 미들웨어(CSRF 등)보다 앞
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "foundation.middleware.CsrfExemptPrefixesMiddleware",  # CsrfViewMiddleware 앞
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "foundation.access.RoleGateMiddleware",  # 역할별 URL 게이트. 로그인 검사보다 앞(관리자 경로를 익명에게도 숨긴다)
    "django.contrib.auth.middleware.LoginRequiredMiddleware",  # 기본 거부: 공개 뷰만 @login_not_required 로 표시
    "foundation.middleware.ApiErrorMiddleware",
    "foundation.middleware.NoStoreMiddleware",
    "axes.middleware.AxesMiddleware",  # 반드시 마지막: 잠금 응답을 만든다
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",  # CSP nonce 를 템플릿에 전달(admin 의 인라인 <style>)
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_USER_MODEL = "foundation.User"

# --- 비밀번호 (설계 §5.1): Argon2, 최소 10자, 흔한 비밀번호·숫자만·아이디 유사 금지 ---
PASSWORD_MIN_LENGTH = 10
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("username", "nickname")}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- 로그인 잠금: 같은 (아이디 + IP) 로 5회 실패하면 5분 잠금 (설계 §5.1) ---
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # 잠금 검사. ModelBackend 보다 앞
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=5)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # 아이디만 기준이면 남이 계정을 잠가버릴 수 있다
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False  # 잠금 중 시도가 잠금을 연장하지 않는다("5분 뒤 재시도")
AXES_CLIENT_IP_CALLABLE = "foundation.net.client_ip"  # 가입 제한과 같은 IP 판정을 쓴다
AXES_LOCKOUT_TEMPLATE = "console/lockout.html"  # 응답 코드는 429

# 신뢰할 리버스 프록시 수. 0 이면 REMOTE_ADDR 만 신뢰한다(X-Forwarded-For 위조로 잠금을 피할 수 없다).
TRUSTED_PROXY_COUNT = 0

# --- 가입 (설계 §5.1, 열린 결정 §7-6: 수치는 설정값) ---
SIGNUP_MAX_PER_IP_PER_HOUR = 5

# --- 세션·쿠키: 게임 서버와 같은 호스트에서 돌 때 충돌하지 않도록 전용 이름 ---
SESSION_COOKIE_NAME = "ads_sessionid"
CSRF_COOKIE_NAME = "ads_csrftoken"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60  # 8시간
SESSION_COOKIE_SECURE = False  # prod 는 True
CSRF_COOKIE_SECURE = False  # prod 는 True
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"  # 별도 쿠키를 만들지 않는다

# --- HTTP 보안 (0-4, 설계 §3·위협 T9~T14) ---
from django.utils.csp import CSP  # noqa: E402  (이 블록의 설정에서만 쓴다)

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# 엄격한 CSP. 인라인 스크립트·스타일은 쓰지 않는다. Django admin 의 인라인 <style> 한 곳만 nonce 로 허용된다.
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

# 키 인증을 쓰는 서버 간 API 만 CSRF 에서 뺀다. 이 목록이 **유일한** 예외다.
CSRF_EXEMPT_PREFIXES = ["/api/media/"]
CSRF_FAILURE_VIEW = "foundation.http.csrf_failure"

# 요청 크기: 업로드 파일 제외 본문 1MiB, 폼 필드 100개. 이미지 용량은 0-5(assets), JSON API 본문은 parse_json(16 KiB).
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100
DATA_UPLOAD_MAX_NUMBER_FILES = 5

# --- 소재 이미지 (0-5, 설계 §8) ---
ASSET_MAX_BYTES = 2 * 1024 * 1024  # 업로드 용량 상한. 1~2MB 범위에서 팀이 정한다(설계 §7-5). env 로 바꿀 수 있다.
ASSET_MAX_PIXELS = 16_000_000  # 압축 폭탄 방어용 픽셀 수 상한(크기 규격 제한이 아니다)
ASSET_STORAGE = "assets.storage.LocalFileStorage"
ASSET_SERVABLE_CHECK = None  # 서빙 가능 여부 함수의 점 경로. Step 1 에서 campaigns 가 제공하고 config 가 연결한다.
# 업로드 전체 크기 가드는 foundation.middleware.RequestBodyLimitMiddleware 가 맡는다(본문을 읽기 전에 413).

# --- 포인트·예산 (설계 §4.7) ---
SIGNUP_GRANT_POINTS = 50_000  # 가입 지급 포인트(설계 §10). dev/prod 는 환경변수로 바꿀 수 있다
BUDGET_DAY_OFFSET_HOURS = 0  # 예산 "그날"의 경계. 0 = UTC 자정(KST 09:00), 9 = KST 자정. 바꾸면 recompute_spend 를 실행한다
BILLING_CHARGE_POLICY = "by-unit/v1"  # 과금 정책 이름(billing/policies)

# --- 반응 처리 (설계 §4.4, 계약 C1). 규칙은 records/rules/, 순서가 곧 판정 순서 ---
REACTION_RULES = (  # 순서가 곧 판정 순서. 되돌릴 수 없는 거부(기간·형식)를 보류(전제 대기)보다 먼저 둔다
    "known-decision", "same-media", "ad-shown", "click-source", "subject", "occurred-at", "campaign-open", "once-per-type",
    "funnel-window", "funnel-order",
)
REACTION_CLICK_WINDOW_SECONDS = 300  # 클릭은 결정 후 이 안에 있어야 한다(설계 §10 "반응 퍼널 규칙")
REACTION_DISPLAY_GRACE_SECONDS = 5  # 같은 표시 단위의 다음 결정이 만들어진 뒤에도 이만큼은 이전 광고의 클릭을 인정한다(화면 반영 여유)
REACTION_CONVERSION_WINDOW_SECONDS = 30 * 24 * 3600  # 전환은 클릭 후 이 안에 있어야 한다
REACTION_OCCURRED_AT_TOLERANCE_SECONDS = 60  # 매체가 보낸 감지 시각이 수신 시각보다 이만큼 넘게 미래면 거부
REACTION_HOLD_SECONDS = 300  # 전제(노출·클릭)를 기다리며 보류하는 최대 시간. 끝내 오지 않으면 missing_prerequisite
REACTION_HOLD_RECHECK_SECONDS = 5  # 보류한 반응을 다시 판정하는 간격(대기열이 보류분으로 막히지 않게 마지막 확인 순으로 돌린다)
REACTION_PROCESS_ON_RECEIPT = True  # 수신 커밋 뒤 한 번 바로 처리해 본다(실패해도 접수 응답은 그대로). 끄면 process_reactions 가 전부 처리한다
REACTION_MAX_ATTEMPTS = 5  # 이만큼 실패한 반응은 자동 재처리에서 빠지고 'stuck' 으로 보고된다(자동으로 거부·삭제하지 않는다: 돈이 걸려 있다)

# --- 광고 선택 (설계 §4.3). 구현 선택은 config 한 곳(R4): 알고리즘·필터를 바꿔도 Decision 구조는 그대로다 ---
ADS_SELECTION_POLICY = "highest-bid/v1"
ADS_ENGINE_FILTERS = ("status", "period", "floor", "budget", "balance")  # 순서가 곧 판정 순서

# --- 매체 API 요청 제한(설계 §10, 계약 C1). (초당 토큰, 버스트). 150명 가정의 개발용 초기값이며 측정 결과가 아니다(2-6 에서 조정) ---
MEDIA_RATE_LIMITS = {
    "decisions": (150, 300),
    "reactions": (450, 600),
    "reads": (150, 300),
}

# --- 광고주 한도 (설계 §7-5는 열림: 아래는 제안 기본값, 모두 설정값) ---
MAX_CAMPAIGNS_PER_ADVERTISER = 20
MAX_AD_GROUPS_PER_ADVERTISER = 100
MAX_CREATIVES_PER_ADVERTISER = 100
MAX_CREATIVES_PER_AD_GROUP = 1  # V1. 모델은 1:N 이라 늘릴 수 있다(설계 §10)
MAX_UPLOAD_BYTES_PER_ADVERTISER = 100 * 1024 * 1024

# --- 접근 통제 (0-3). 접두사 → 역할 표는 config/access_map.py 한 곳에서 만든다 ---
# 환경별 설정(dev/prod/test)이 ADMIN_URL_PATH 와 ACCESS_MAP 을 정한다.

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/advertiser/"
LOGOUT_REDIRECT_URL = "login"

# 시간은 저장·계산 모두 UTC. KST 는 화면 표시 변환에서만 쓴다(foundation 의 `kst` 필터).
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # `collectstatic` 의 결과 폴더. 운영 웹서버가 서빙한다(prod 는 환경변수로 바꿀 수 있다).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SQLITE_BUSY_TIMEOUT_SECONDS = 5


def sqlite_config(name, wal=True):
    """SQLite 설정 (설계 §6.5).

    - WAL: 읽기와 쓰기가 서로 막지 않는다.
    - synchronous=FULL: 커밋이 디스크에 내려간 뒤에 확인한다. NORMAL 이면 정전 시 마지막 커밋을 잃을 수 있다.
    - timeout: 잠금 대기(busy_timeout). 넘으면 'database is locked' → 수신 단계는 503 으로 변환(Step 2).
    - transaction_mode=IMMEDIATE: 쓰기 트랜잭션을 시작할 때 잠금을 잡아 중간 교착을 피한다.
    """
    init = "PRAGMA synchronous=FULL;"
    if wal:
        init = "PRAGMA journal_mode=WAL; " + init
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(name),
        "OPTIONS": {
            "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
            "transaction_mode": "IMMEDIATE",
            "init_command": init,
        },
    }


# 로깅 원칙: 요청 본문·비밀번호·세션 키·매체 키는 기록하지 않는다(0-6 에서 필터로 강제).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "foundation.logging.RequestIdFilter"},
        "redact": {"()": "foundation.logging.RedactingFilter"},
    },
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain", "filters": ["request_id", "redact"]},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
