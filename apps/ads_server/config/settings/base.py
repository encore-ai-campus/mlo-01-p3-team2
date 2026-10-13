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
    "events.apps.EventsConfig",
    "records.apps.RecordsConfig",
    "serving_api.apps.ServingApiConfig",
    "console.apps.ConsoleConfig",
]

MIDDLEWARE = [
    "foundation.middleware.RequestIdMiddleware",  # 가장 먼저: 모든 응답·로그에 요청 ID
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # 정적 파일(/static/)은 Django 가 서빙한다 — 앞단 nginx 는 통로만(설계 §10 "정적 파일 서빙", 6-5e). 보안 헤더(nosniff) 안쪽, 로그인·역할 검사 앞(공개 CSS·JS)
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

# --- 비밀번호 (설계 §5.1): Argon2, 10~128자(C6), 흔한 비밀번호·숫자만·아이디 유사 금지 ---
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("username", "nickname")}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "foundation.validators.MaximumLengthValidator", "OPTIONS": {"max_length": PASSWORD_MAX_LENGTH}},  # 화면 폼만이 아니라 서비스·서버 명령도(C6)
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
AXES_CLIENT_IP_CALLABLE = "foundation.net.client_ip"  # 감사 로그와 같은 IP 판정을 쓴다
AXES_LOCKOUT_TEMPLATE = "console/lockout.html"  # 응답 코드는 429
AXES_ENABLE_ADMIN = False  # axes 자체 등록(삭제·정리 동작이 열린 화면)을 끄고 foundation/admin.py 가 읽기 전용으로 다시 등록한다(위협 모델 T44)

# 신뢰할 리버스 프록시 수. 0 이면 REMOTE_ADDR 만 신뢰한다(X-Forwarded-For 위조로 잠금을 피할 수 없다). prod 는 필수·1 이상(앞단 nginx, 6-5c)
TRUSTED_PROXY_COUNT = 0

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
    "known-decision", "same-media", "media-period", "ad-shown", "click-source", "subject", "occurred-at", "campaign-open", "once-per-type",
    "funnel-window", "funnel-order",
)
REACTION_CLICK_WINDOW_SECONDS = 300  # 클릭은 결정 후 이 안에 있어야 한다(설계 §10 "반응 퍼널 규칙")
REACTION_DISPLAY_GRACE_SECONDS = 5  # 이전 광고의 표시 끝 = 같은 표시 단위의 이후 결정 중 **처음으로 노출이 도착한(접수된) 시각** + 이 값. 그 안의 클릭까지 인정한다(화면 반영 여유). 결정이 만들어진 시각은 쓰지 않는다(records/facts.py display_signal)
REACTION_CONVERSION_WINDOW_SECONDS = 30 * 24 * 3600  # 전환은 클릭 후 이 안에 있어야 한다
REACTION_OCCURRED_AT_TOLERANCE_SECONDS = 60  # 매체가 보낸 감지 시각이 수신 시각보다 이만큼 넘게 미래면 거부
REACTION_HOLD_SECONDS = 300  # 전제(노출·클릭)를 기다리며 보류하는 최대 시간. 끝내 오지 않으면 missing_prerequisite
REACTION_HOLD_RECHECK_SECONDS = 30  # 보류한 반응을 주기적으로 다시 판정하는 간격 = 기한 경과를 잡는 **안전망**. 앞 단계가 끝나면 같은 결정의 보류분을 바로 깨우므로(processing._wake_dependents) 평소엔 이 간격을 기다리지 않는다. 5초였을 때 보류 N 건을 5초마다 전부 다시 판정해 처리 프로세스가 보류분만 돌았다(DB-1d 측정)
REACTION_PROCESS_ON_RECEIPT = True  # 수신 커밋 뒤 한 번 바로 처리해 본다(실패해도 접수 응답은 그대로). 끄면 process_reactions 가 전부 처리한다
REACTION_MAX_ATTEMPTS = 5  # 이만큼 실패한 반응은 자동 재처리에서 빠지고 'stuck' 으로 보고된다(자동으로 거부·삭제하지 않는다: 돈이 걸려 있다)

# --- 이벤트 outbox (설계 §6.3, 계획 4-1) ---
EVENTS_OUTBOX_RETENTION_DAYS = 7  # MongoDB 로 보낸 outbox 행을 이만큼 지난 뒤 `purge_sent_events` 가 지운다(미전송은 지우지 않는다). 보존 기간 전반은 설계 §7-8 이 열려 있다

EVENTS_HOP_GRACE_SECONDS = 120  # 구간별 정합 manifest(4-3b)의 창 닫힘 여유: 창이 끝나고 이만큼 지나야 그 창의 첫 세대를 낸다(설계 §10 H11 A안). 늦은 이벤트가 보이면 B안으로 다시 정한다

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
STATIC_ROOT = BASE_DIR / "staticfiles"  # `collectstatic` 의 결과 폴더. 운영에서는 WhiteNoise 가 시작할 때 읽어 Django 가 서빙한다 — 모은 뒤 재시작(prod 는 환경변수로 바꿀 수 있다).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

def mysql_config(name, user, password, host, port, isolation_level="read committed"):
    """MySQL 8.4 접속 설정 (계획 §7.3 S5·S7). 값은 호출한 쪽이 환경변수에서 읽어 넘긴다.

    - STRICT_ALL_TABLES: 잘리거나 잘못된 값을 경고로 넘기지 않고 오류로 한다.
    - READ COMMITTED **[DB-1c 측정으로 확정 2026-10-09]**: 150 동시 부하(`scripts/load_test.py`, MySQL 8.4.11 단일 노드)를 격리 수준만 바꿔 돌렸다.
      READ COMMITTED 는 두 번 모두 교착 0·잠금 초과 0·불변식 전부 통과, REPEATABLE READ 는 교착 8건(1213)이 나고 불변식 2건이 실패했다
      (같은 `reaction_id` 재전송 폭주에서 201 이 하나가 아니었고, 결정마다 퍼널이 인정되지 않은 결정이 있었다).
      간격 잠금이 같은 유일 키를 노리는 동시 INSERT 를 교착으로 몰기 때문이다. 판정은 유일 제약과 행 잠금에 기대므로 READ COMMITTED 로도 의미가 같다.
      환경변수 `DB_ISOLATION_LEVEL` 로 바꿔 다시 비교할 수 있다(dev·prod 만, 시험 설정은 고정).
    - 데이터 정렬 utf8mb4_0900_as_cs: 8.4 기본(`_ai_ci`)은 대소문자·악센트를 구분하지 않아, 대소문자가 의미인 값(키·토큰·사용자 이름)의 유일 제약과 비교가 달라진다.
      DB 를 만들 때 같은 값을 쓴다(README).
    - CONN_MAX_AGE=0: 요청마다 연결을 닫는다. 150 동시 부하(DB-1d)에서 연결 수 = 동시 요청 수라 서버 `max_connections`(기본 151)에 닿아 일부가 503 + 재시도를 겪었다
      (앱의 처리는 올바르다). 영속 연결·풀은 배포 구성(워커 수 × 스레드 수)과 인프라의 `max_connections` 가 정해진 뒤에 정한다(계획 7.3.4 #4).
    """
    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": str(port),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET SESSION sql_mode='STRICT_ALL_TABLES'",
            "isolation_level": isolation_level,
            "connect_timeout": 5,
        },
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_0900_as_cs"},
    }


def mongo_config(hosts, database, user=None, password=None, auth_source="admin", replica_set=None):
    """MongoDB 8.0 이벤트 저장소 접속 설정 (계획 DB-2). 값은 호출한 쪽이 환경변수에서 읽어 넘기고, 연결은 `events/` 가 처음 쓸 때 만든다(기동 때 연결하지 않는다).

    - hosts: `host:port` 목록(레플리카셋이면 구성원 몇 개), replica_set: 레플리카셋 이름(없으면 단일 서버 접속).
    - 비밀번호는 URI 에 넣지 않고 따로 둔다(로그·오류 메시지에 URI 가 찍혀도 새지 않게).
    """
    return {"HOSTS": list(hosts), "NAME": database, "USER": user, "PASSWORD": password,
            "AUTH_SOURCE": auth_source, "REPLICA_SET": replica_set}


# 로깅 원칙: 요청 본문·비밀번호·세션 키·매체 키는 기록하지 않는다(0-6 에서 필터로 강제).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "foundation.logging.RequestIdFilter"},
        "redact": {"()": "foundation.logging.RedactingFilter"},
    },
    "formatters": {
        "plain": {"class": "foundation.logging.UtcFormatter", "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},  # 시각은 UTC ISO 8601 Z
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain", "filters": ["request_id", "redact"]},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
