# 광고 서버 구현 계획

> Status: Approved (2026-10-07 `intake/`에서 승격). 구현은 `apps/ads_server/`에서 진행하며 진행 상태는 §10에 기록한다.
> 작성: 2026-10-07
> 기준 문서: [ads-server-design.md](ads-server-design.md) (구조·계약·결정), [console-ui-benchmark.md](console-ui-benchmark.md) (화면)
> 상세도: **Step 0은 구현 수준으로 상세(완료), Step 1도 상세(2026-10-07 작성)**, Step 2는 개요, Step 3~5는 요약. 뒤 단계는 앞 단계 결과에 따라 바뀔 수 있어 그때 상세화한다.
> 경로는 `apps/ads_server/` 기준이다.

---

# 1. 진행 원칙

1. **하위 단계마다 "완료 증거"가 통과해야 다음으로 간다.** 증거는 파일이 있다는 사실이 아니라 **테스트 통과와 실제 실행 결과**다.
2. **앞 단계가 끝나기 전에 다음 단계 코드를 섞지 않는다.** 각 단계가 끝날 때마다 서버가 뜨는 상태를 유지한다.
3. **안쪽부터 만든다.** 순수 로직(`engine`)과 도메인을 먼저 테스트로 닫고, 바깥(`serving_api`, `console`)은 마지막에 얹는다.
4. **경계 규칙(R1~R8)은 첫날부터 테스트로 강제한다**(0-6의 경계 검사). 위반을 나중에 한꺼번에 고치지 않는다.
5. **설계와 어긋나는 사실을 발견하면 코드를 고치기 전에 설계 문서를 먼저 고친다.** 확정된 열린 결정은 설계 §10으로 옮긴다.
6. **작업 환경**: 프로젝트 가상환경 `apps/ads_server/.venv`(Python 3.14 — `python3.14 -m venv .venv` → `source .venv/bin/activate` → `pip install -r requirements.txt`, README "실행"). 2026-10-10까지는 개인 conda 환경(`mamba activate claude`, Python 3.14.7)을 썼고, 다른 사람이 같은 환경을 만들 수 있도록 바꿨다. **코드에서 import하는 모든 라이브러리는 `requirements.txt`에 적는다**(§3 표).
7. **테스트는 Django 기본 러너**(`python manage.py test`)를 쓴다. 별도 테스트 프레임워크를 들이지 않는다. 보안 회귀 테스트는 `@tag("security")`로 표시해 `--tag security`로 따로 돌릴 수 있게 한다.
8. **커밋 단위**: 하위 단계(예: 0-2) 하나 이상. 완료 증거가 통과한 상태로만 커밋한다.

---

# 2. 단계 개요와 의존 관계

```
Step 0  플랫폼 기반 + 보안 베이스라인
  0-0 ─┐
  0-1 ─┼─▶ 0-2 ─▶ 0-3 ─▶ 0-4 ─▶ 0-6
       └─▶ 0-5 ──────────────────▲      (0-5 assets는 0-1 이후 독립적으로 진행 가능)

Step 1  도메인 코어 (0-3, 0-5 이후)
  1-1 masters ─▶ 1-2 campaigns ─▶ 1-5 records ◀─ 1-4 engine (1-1·1-2와 독립)
                      └──────▶ 1-3 billing ───▲

Step 2  Serving API (1-5 이후)   2-1 ─▶ 2-2 ─▶ 2-3 ─▶ 2-4 ─▶ 2-5 ─▶ 2-6
        C1 v1.1 (2-6 이후, Step 3 전)   2-7 ─▶ 2-8 ─▶ 2-9 ─▶ 2-10 ─▶ 2-11 ─▶ 2-12 ─▶ 2-13
Step DB DB 전환 (Step 2 마무리 직후, Step 3 전)   DB-1 MySQL ─▶ DB-2 MongoDB 연결
Step 3  화면 (Step DB 이후. 3-1 관리자와 3-2 광고주는 서로 독립)
Step 4  이벤트 내보내기 (Step DB 이후)   4-1 outbox → 중계 → MongoDB ─▶ 4-2 NDJSON manifest·검증 ─▶ 4-3 백필·구간별 정합 manifest ─▶ 4-4 코드 정리
Step 5  확장 (조건부: 조회 시간·부하 지표가 한계일 때. 지금은 기록만)
```

| 병렬로 나눠 맡을 수 있는 지점 | 조건 |
|---|---|
| 0-5(`assets`)와 0-2~0-4 | 0-1(골격) 이후. 서로 import하지 않는다 |
| 1-4(`engine`)와 1-1·1-2·1-3 | `engine`이 정의하는 `Candidate`·`Eligible`·`SelectionPolicy` 시그니처만 먼저 합의(필드 목록은 설계 §4.3에서 확정) |
| 1-3(`billing`)과 1-1·1-2 | 캠페인을 ID 값으로만 다룬다 |
| 3-1(관리자)과 3-2(광고주) | Step 1 이후 |

---

# 3. 라이브러리 계획 (`requirements.txt`)

버전은 **구현 시점에 최신 패치를 다시 확인해 `~=`로 고정**한다(설계 §9). 표의 버전은 현재 확인된 값이다.

| 라이브러리 | 용도 | 도입 단계 | 비고 |
|---|---|---|---|
| `Django~=6.1.2` | 프레임워크 | 0-1 | axes 게이트 실패 시 `~=5.2`로 내림(0-2) |
| `python-dotenv` (1.x) | 로컬 `.env`를 환경변수로 로드 | 0-1 | 구현 시점에 `~=`로 고정. 실제 환경변수가 `.env`보다 우선(`override=False`) |
| `django-axes~=8.3` | 로그인 5회 실패 시 5분 잠금 | 0-2 | 선언 지원이 Django 6.0까지 — **6.1 검증이 게이트** |
| `argon2-cffi` | Argon2 비밀번호 해시 | 0-2 | Django의 `Argon2PasswordHasher`가 요구 |
| `Pillow` | 이미지 판별·재인코딩 | 0-5 | |
| `pip-audit` | 의존성 취약점 점검 | 0-6 | 개발용이지만 스크립트가 쓰므로 파일에 적는다 |
| `bandit` | 정적 보안 점검 | 0-6 | 위와 같음 |
| `PyYAML` | 계약 파일(`serving.openapi.yaml`) 로드 | 2-1 | 완료 내용은 §10 진행 상태의 2-1 |
| `jsonschema` | 실제 응답을 계약 스키마에 대조(provider 계약 테스트) | 2-1 | OpenAPI 3.1 스키마는 JSON Schema 2020-12 |
| `openapi-spec-validator` | 계약 파일이 올바른 OpenAPI 3.1인지 검증 | 2-1 | 검증 스크립트용 |

**쓰지 않는 것**: `djangorestframework`(C1은 엔드포인트가 몇 개라 직접 작성하고 계약은 OpenAPI 파일이 맡는다), `pytest`·`factory_boy`(Django 기본 러너), `celery`·`redis`(재처리는 관리 명령으로).

---

# 4. 구현 시점에 공식 문서로 확인할 것

이 계획의 설정 이름 일부는 기억에 의존했다. **해당 단계 시작 전에 Django 6.1 / axes 8.x 공식 문서로 확인하고, 다르면 계획을 고친다.**

| 단계 | 확인할 것 |
|---|---|
| 0-1 | SQLite `OPTIONS`의 `transaction_mode`, `init_command`, `timeout` 이름·동작 |
| 0-2 | axes 8.x의 설정 이름(`AXES_FAILURE_LIMIT`, `AXES_COOLOFF_TIME`, 아이디+IP 조합 잠금 옵션), 백엔드·미들웨어 등록 방식, Django 6.1과의 호환 |
| 0-3 | 내장 `LoginRequiredMiddleware`와 `login_not_required` 데코레이터의 이름·동작 |
| 0-4 | 내장 CSP(`SECURE_CSP`, CSP 미들웨어, 상수 이름), `SECURE_*` 헤더 설정 |
| 0-5 | Pillow의 `MAX_IMAGE_PIXELS`·`DecompressionBombError` 동작, 애니메이션 PNG 판별 방법 |

---

# 5. Step 0: 플랫폼 기반 + 보안 베이스라인 (상세)

**Step 0 합격선**: 광고 기능이 하나도 없어도 `scripts/check.sh`가 전부 통과하고, 빈 플랫폼이 뜨며, 가입·로그인·로그아웃·권한 분리·이미지 업로드 검증이 동작한다.

**Step 0 끝에 존재하는 모듈**: `config`, `foundation`(계정·접근 통제·HTTP 보안·감사), `assets`(이미지 검증·저장·서빙), `console`(가입·로그인 화면과 기본 템플릿만).

## 0-0. 위협 모델 한 장

- **산출물**: `threat-model.md` (승격 후 `docs/ads-server/`). 자산 × 행위자 × 위협 × 대응 단계 × 검증 테스트 표.
- **자산**: 계정·세션, 포인트(원장), 소재 파일, 입찰 정책, 결정·반응 기록, 매체 키, 비밀값.
- **행위자**: 익명 방문자(가입 전), 광고주(가입자), 관리자, 매체 서버, 외부 공격자.
- **초기 위협 목록** (출발점이었다. 번호·내용을 다듬은 **정식 표는 [threat-model.md](threat-model.md)** 이고, 이후 갱신은 그쪽에서 한다):

| # | 위협 | 대응 | 단계 |
|---|---|---|---|
| T1 | 무차별 대입으로 계정 탈취 | 5회 실패 5분 잠금, Argon2, 비밀번호 검증기 | 0-2 |
| T2 | 대량 가입·계정 남용 | 가입 IP 제한, 광고주당 상한 | 0-2, 3 |
| T3 | 권한 상승 (가입 폼 `role` 조작, 광고주가 관리자 화면 접근) | 가입 폼은 역할을 받지 않음, 역할별 URL 게이트 | 0-3 |
| T4 | 남의 객체 접근(IDOR) | 소유권 검사 헬퍼, 기본 거부 | 0-3, 1 |
| T5 | 악성 업로드(위장 파일, 압축 폭탄, SVG, 경로 조작, EXIF 개인정보) | 내용 판별·재인코딩·해시 이름 | 0-5 |
| T6 | 이동 주소 피싱 | `https`만, 도메인 표시, 중단 | 3 |
| T7 | 광고주 입력의 XSS(제목 등) | 템플릿 자동 이스케이프, CSP | 0-4 |
| T8 | CSRF | 전역 CSRF, 예외 허용 목록 한 곳 | 0-4 |
| T9 | 비밀값 유출 | 환경변수만, `.env` 미커밋, 로그에 비밀 금지 | 0-1, 0-6 |
| T10 | 매체 키 유출·위조 요청 | 키 해시 저장, 교체, 요청 제한 | 2 |
| T11 | 반응 위조·중복·타 매체 보고 | 규칙 체인, 멱등, 유형별 1회 | 2 |
| T12 | 거대·기형 요청으로 서버 압박 | 본문 크기·JSON 깊이 제한, 입력 오류는 4xx | 0-4 |
| T13 | 관리자 행위 추적 불가 | 감사 로그 | 0-6 |
| T14 | 취약한 의존성 | 패치 고정, `pip-audit` | 0-6 |
| T15 | 포인트 정합성 훼손 | 원장 추가 전용, 잔액=합계 점검 | 1-3 |
| T16 | 캐시로 인한 세션·개인 정보 노출 | 인증 페이지 `no-store` | 0-4 |

- **완료 증거**: 표의 모든 행에 대응 단계가 있고, 0-1~0-6의 각 항목이 최소 한 행에 대응한다. 문서 리뷰로 확인.

## 0-1. 골격·설정·비밀값·SQLite·User 모델

**산출물**

```
apps/ads_server/
  manage.py
  requirements.txt
  .env.example                 # 이름만. 값은 넣지 않는다
  .gitignore                   # .env, db.sqlite3, media/, __pycache__
  README.md                    # 실행 방법(.venv, 환경변수, 명령)
  config/
    settings/{__init__,base,dev,prod,test}.py
    env.py                     # load_env(): .env 로드(python-dotenv). 설정보다 먼저 호출
    urls.py  wsgi.py  asgi.py
  foundation/
    apps.py                    # label = "foundation" 고정
    models.py                  # User (필드만, 동작은 0-2)
    templatetags/kst.py        # UTC → KST 표시 필터
    migrations/0001_initial.py
  tests/
```

**할 일**

1. **설정 분리**: `base`(공통) / `dev`(DEBUG 허용, 로컬) / `prod`(엄격) / `test`. 어떤 설정을 쓸지는 `DJANGO_SETTINGS_MODULE`, 기본값은 `prod`가 **아니라** `dev`가 되면 위험하므로 `manage.py`는 환경변수가 없으면 `dev`로 시작하되 `wsgi.py`/`asgi.py`는 `prod` 기본으로 둔다.
2. **비밀값**: `SECRET_KEY`, `ALLOWED_HOSTS`, `DJANGO_ENV` 등은 **환경변수**로 읽는다. 로컬에서는 `.env` 파일을 **`python-dotenv`** 가 읽는다. 로드는 `config/env.py`의 `load_env()` **한 곳**에서 하고, `manage.py`·`wsgi.py`·`asgi.py`가 설정을 불러오기 **전에** 호출한다.
   - **`override=False`**: 실제 환경변수(인프라가 주입한 값)가 `.env`보다 우선한다. `.env`가 없어도 오류가 아니다.
   - `.env`는 `.gitignore`에 넣고 권한 600을 권장한다. `.env.example`을 복사해서 쓴다(README에 적는다).
   - `test` 설정은 `.env`에 의존하지 않도록 필요한 값을 **직접 지정**한다(개발자 로컬 `.env`가 테스트 결과를 바꾸지 않게).
   - `prod`는 `SECRET_KEY`가 없거나 `dev` 기본값이면 **기동 실패**(`ImproperlyConfigured`). `dev`에만 임시 키를 둔다.
3. **`DEBUG`**: 기본 `False`. `dev`에서만 환경변수로 켠다.
4. **시간대**: `USE_TZ = True`, `TIME_ZONE = "UTC"`. `foundation/templatetags/kst.py`에 `{{ value|kst }}` 필터(`zoneinfo.ZoneInfo("Asia/Seoul")`). **화면 표시에만** 쓰고, 계산·저장에는 쓰지 않는다.
5. **SQLite 설정**(설계 §6.5): `OPTIONS`에 **WAL**, **`synchronous=FULL`**(커밋이 디스크에 내려간 뒤 확인해야 "저장 후 확인"이 성립한다), `busy_timeout`(예: 5초), **쓰기 트랜잭션 즉시 시작**(`IMMEDIATE`). 이후 반응 수신 등에서 DB 잠금 오류가 나면 503으로 변환한다(2-4).
6. **앱 라벨 규칙(R3)**: `AppConfig.label`을 명시한다. 모든 모델은 `Meta.db_table = "<label>_<model>"`을 **명시**한다(0-6에서 테스트로 강제).
7. **User 모델과 `AUTH_USER_MODEL`**(**첫 마이그레이션 전에**): `AbstractBaseUser` + `PermissionsMixin`을 쓰고 필요한 필드만 둔다.

   | 필드 | 설명 |
   |---|---|
   | `username` | 아이디. 유니크 |
   | `password` | (상속) |
   | `role` | `admin` / `advertiser` (`TextChoices`) |
   | `nickname` | 표시 이름. 유니크하지 않음 [제안] |
   | `class_label` | 반. 자유 입력 짧은 문자열 |
   | `is_active` | 비활성화 |
   | `created_at` | UTC |

   `is_staff`는 **프로퍼티**(`role == admin and is_active`)다. 이메일·이름 필드는 없다. 커스텀 매니저에 `create_superuser`를 둔다(역할 `admin`).
8. **로깅 골격**: `LOGGING` 설정(콘솔 출력, 레벨), 요청 본문·비밀번호를 기록하지 않는다는 원칙만 먼저 문서화(구현은 0-6).

**테스트** (`tests/test_settings.py`, `tests/test_user_model.py`)

| 테스트 | 확인 |
|---|---|
| `test_prod_requires_secret_key` | 환경변수 없이 `prod` 설정을 불러오면 실패 (서브프로세스) |
| `test_debug_default_false` | 기본 `DEBUG`가 꺼짐 |
| `test_dotenv_loaded_when_present` | `.env`의 값이 환경변수로 로드됨 |
| `test_real_env_overrides_dotenv` | 같은 이름이면 실제 환경변수가 이김 |
| `test_missing_dotenv_is_not_an_error` | `.env`가 없어도 기동 |
| `test_test_settings_ignore_dotenv` | `.env`가 있어도 `test` 설정 값이 바뀌지 않음 |
| `test_timezone_is_utc` | `USE_TZ`, `TIME_ZONE`, 저장된 `created_at`이 UTC |
| `test_kst_filter_displays_plus_9` | UTC 값이 KST로 표시됨 |
| `test_sqlite_pragmas` | `PRAGMA journal_mode`가 `wal`, `synchronous`가 FULL |
| `test_user_has_no_email_fields` | 이메일·이름 필드 없음 |
| `test_is_staff_only_for_active_admin` | 광고주·비활성 관리자는 `is_staff` 거짓 |
| `test_create_superuser_sets_admin_role` | |

**완료 증거**: `python manage.py check` 통과, `python manage.py test` 통과, `python manage.py runserver`가 `127.0.0.1:8001`에서 뜸. `check --deploy`의 **경고 목록을 기록**한다(0-4에서 0으로 만든다).

## 0-2. 계정·인증·세션 (+ 가입·로그인 화면)

**산출물**

```
foundation/
  api.py                       # create_advertiser, authenticate 헬퍼 등 외부 공개 면
  accounts.py                  # 가입 서비스(검증 규칙의 유일한 위치)
  models.py                    # + SignupAttempt (IP, 시각)
  validators.py                # 아이디·닉네임·반 규칙
console/
  views/auth.py  forms.py  urls.py
  templates/console/{base,signup,login}.html   # 인라인 스크립트·스타일 없음(CSP 대비)
  static/console/*.css
tests/test_accounts.py  tests/test_lockout.py  tests/test_session_cookies.py
```

**할 일**

1. **비밀번호 해시**: `PASSWORD_HASHERS`의 첫 번째를 `Argon2PasswordHasher`로. `AUTH_PASSWORD_VALIDATORS`: 최소 길이(**10자**, 설정값), 흔한 비밀번호, 숫자만 금지, 아이디와 유사 금지.
2. **가입 서비스** `foundation.accounts.create_advertiser(username, password, nickname, class_label)`: 규칙은 **여기에만** 둔다(설계 §6.6 규칙 1).
   - 아이디 `[a-z0-9_]{4,20}`, 닉네임 2~20자, 반 1~30자(공백 정리, 제어 문자 금지). 아이디 중복은 일반적인 오류 문구(존재 여부를 과하게 알리지 않음).
   - 역할은 **항상 `advertiser`**. 서비스 함수가 역할 인자를 받지 않는다.
3. **가입 시도 제한**: `SignupAttempt(ip, created_at)` 행을 남기고, 최근 1시간 안의 시도가 `SIGNUP_MAX_PER_IP_PER_HOUR`(기본 5, 설정값, 설계 §7-5)를 넘으면 429. 오래된 행은 가입 처리 중 기회가 될 때 삭제(별도 스케줄러 없음). 프로세스가 여러 개여도 일관되도록 **메모리 캐시가 아니라 DB**를 쓴다.
4. **로그인 잠금(axes)**: `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 5분`, **아이디+IP 조합**으로 잠금(설계 §5.1). 백엔드 `AxesStandaloneBackend`를 `ModelBackend`보다 앞에 두고 미들웨어를 등록한다. 잠긴 사용자에게는 "5분 뒤 다시 시도" 안내 화면을 보여준다.
   - **IP 판정**: 기본은 `REMOTE_ADDR`만 신뢰한다. 리버스 프록시 뒤에 둘 때는 **신뢰할 프록시 수를 명시**한다. 그렇지 않으면 `X-Forwarded-For` 위조로 잠금을 피할 수 있다.
5. **세션·쿠키**: `SESSION_COOKIE_NAME = "ads_sessionid"`, `CSRF_COOKIE_NAME = "ads_csrftoken"`(게임 서버와 충돌 방지), `HttpOnly`, `SameSite=Lax`, prod에서 `Secure`, `SESSION_COOKIE_AGE`(8시간, 설정값). 로그아웃은 **POST만** 받고 세션을 폐기한다. 로그인 성공 시 세션 키를 새로 발급한다(Django 기본 동작 확인).
6. **화면**: 가입·로그인·로그아웃과 공통 `base.html`. 인라인 스크립트·`style=` 속성을 쓰지 않는다(0-4의 CSP). 오류 메시지는 필드별로 보여주되 계정 존재 여부를 로그인 화면에서 구분해 알리지 않는다("아이디 또는 비밀번호가 올바르지 않습니다").
7. **Django 6.1 게이트**: 잠금 테스트(아래)가 6.1에서 통과해야 다음으로 간다. **실패하면** `requirements.txt`를 `Django~=5.2`로 내리고 같은 테스트를 다시 돌린다(설계 §9). 결과를 설계 문서 §9에 기록한다.

**테스트**

| 파일 | 테스트 | 확인 |
|---|---|---|
| `test_accounts` | `test_signup_creates_advertiser_role` | 가입자는 `advertiser` |
| | `test_signup_ignores_role_field` | 폼에 `role=admin`을 넣어도 무시 |
| | `test_username_rules`, `test_nickname_class_label_rules` | 경계값 |
| | `test_password_validators_applied` | 짧은·흔한·아이디 유사 비밀번호 거부 |
| | `test_password_stored_as_argon2` | 저장 해시 접두사 |
| | `test_signup_rate_limit_per_ip` | 한도 초과 시 429, 다른 IP는 영향 없음 |
| | `test_duplicate_username_generic_error` | |
| `test_lockout` | `test_locked_after_5_failures` | 5회 실패 후 올바른 비밀번호도 거부 |
| | `test_lock_is_per_username_and_ip` | 다른 IP·다른 아이디는 영향 없음 |
| | `test_unlocked_after_5_minutes` | 시간을 앞당겨 5분 경과 시 해제 (**6.1 게이트**) |
| | `test_failed_login_message_is_generic` | |
| `test_session_cookies` | `test_cookie_names_and_flags` | 이름·`HttpOnly`·`SameSite`, prod 설정에서 `Secure` |
| | `test_logout_requires_post_and_flushes_session` | GET은 거부, 세션 폐기 |
| | `test_session_key_rotates_on_login` | |
| | `test_session_expires` | 만료 후 접근 불가 |

**완료 증거**: 위 테스트 통과(전부 `@tag("security")`), 브라우저로 가입 → 로그인 → 로그아웃 확인, 6.1 게이트 결과 기록.

## 0-3. 접근 통제

**산출물**: `foundation/access.py`(역할 게이트·소유권 헬퍼), `config/access_map.py`(접두사 → 역할 표, **한 곳**), `config/settings`의 미들웨어 목록, 테스트용 `tests_support` 앱(소유자가 있는 더미 모델), `tests/test_access.py`

**할 일**

1. **기본 거부**: Django 내장 `LoginRequiredMiddleware`를 켜고, 로그인 없이 열어야 하는 뷰(가입·로그인·정적·이미지 서빙·C1 API 등)만 **명시적으로 표시**한다.
2. **역할별 URL 게이트**: `config/access_map.py`에 `{"/advertiser/": "advertiser", "/<관리자 경로>/": "admin"}` 같은 표를 두고, **작은 미들웨어 하나**가 요청 경로의 접두사로 역할을 검사한다. 새 URL을 그 접두사 밑에 추가하면 자동으로 보호된다.
   - 관리자 화면에 광고주가 접근하면 **404**(존재를 알리지 않음), 광고주 화면에 관리자가 접근하면 403.
3. **Django admin 경로**: 환경변수 `ADMIN_URL_PATH`로 정한다. **`prod`에서 `admin/` 기본값이면 기동 실패.** 로그인한 `admin` 역할만 접근한다(`is_staff` 프로퍼티).
4. **소유권 헬퍼**: `foundation.api.owned_or_404(queryset, user)` — 소유자 필드 이름을 인자로 받고 남의 객체는 **404**(403이 아니라, 존재 여부를 알리지 않음). 이후 모든 광고주 객체 조회가 이 함수를 지나게 한다.
5. **URL 전수 점검 테스트**: URL 설정을 순회해 **모든 패턴이 ① 공개 표시가 있거나 ② 접두사 표 안에 있음**을 확인한다. 새 URL이 보호 없이 추가되면 테스트가 실패한다.

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_anonymous_redirected_to_login` | 공개 표시 없는 뷰는 로그인으로 |
| `test_public_views_are_explicit` | 가입·로그인·정적 등만 공개 |
| `test_advertiser_cannot_open_admin_area` | 404 |
| `test_admin_cannot_open_advertiser_area` | 403 |
| `test_admin_url_default_rejected_in_prod` | 기본 `admin/`이면 기동 실패 |
| `test_owned_or_404_hides_others_objects` | 광고주 A가 B의 객체를 요청하면 404 |
| `test_every_url_is_protected_or_marked_public` | URL 전수 점검 |
| `test_signup_cannot_escalate_role` | 0-2와 중복 확인 |

**완료 증거**: 테스트 통과, 광고주 계정으로 관리자 경로 접근 시 404, 새 URL 추가 시 전수 점검이 잡는 것을 의도적으로 확인.

## 0-4. HTTP 계층 보안

**산출물**: `foundation/http.py`(JSON 파싱 헬퍼·표준 오류 응답), `foundation/middleware.py`(요청 접두사 CSRF 예외, `no-store`), `config/settings/prod.py`의 보안 설정, 오류 템플릿(`400/403/404/500`), `tests/test_http_security.py`

**할 일**

1. **보안 헤더**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, HSTS(prod, TLS 종단이 프록시면 `SECURE_PROXY_SSL_HEADER`), `SECURE_SSL_REDIRECT`는 환경변수.
2. **CSP**(Django 6.x 내장): `default-src 'self'`, `img-src 'self' data:`, `script-src 'self'`, `style-src 'self'`, `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`. 인라인 스크립트가 필요한 곳은 nonce를 쓰고, 기본은 쓰지 않는다. 5.2로 내려갔다면 `django-csp`로 같은 정책.
3. **CSRF**: 미들웨어 전역 적용. **C1 API(`/api/media/`)처럼 키 인증을 쓰는 경로만** 접두사 허용 목록 **한 곳**(`CSRF_EXEMPT_PREFIXES`)에서 예외 처리하는 작은 미들웨어를 CSRF 미들웨어 앞에 둔다.
4. **요청 크기**: `DATA_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_NUMBER_FIELDS` 설정. 업로드 파일 크기는 0-5에서. 프록시의 `client_max_body_size`는 인프라 소관(문서에 명시).
5. **JSON 파싱 헬퍼** `foundation.http.parse_json(request, max_bytes, max_depth)`: 본문을 **한도까지만** 읽고, `json.loads`에 `parse_constant`로 **`NaN`·`Infinity` 거부**, 중첩 **깊이 제한**, 최상위가 객체인지 확인. 실패는 도메인 예외로 → **400**(한도 초과는 **413**, `Content-Type`이 JSON이 아니면 **415**). (Step 2의 C1이 그대로 쓴다.)
6. **표준 오류 응답**: `/api/` 접두사는 **`application/problem+json`**(RFC 9457: `type`·`title`·`status`·`code`·`detail`·`request_id`, 검증 오류는 `errors[]`. 계약 `serving.openapi.yaml`의 `Problem` 스키마와 같다), 그 외는 오류 템플릿. 스택트레이스·내부 경로·SQL을 응답에 싣지 않는다. 처리되지 않은 예외는 500이지만 **입력 오류가 500이 되지 않아야 한다**.
7. **캐시 금지**: 인증이 필요한 페이지에는 `Cache-Control: private, no-store`(이미지 서빙과 정적 파일은 제외, 0-5).
8. **`manage.py check --deploy` 경고 0**: prod 환경변수 샘플로 실행해 0-1에서 기록한 경고를 모두 해소한다.

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_security_headers_present` | nosniff, 프레임 금지, Referrer-Policy, (prod) HSTS |
| `test_csp_header_policy` | 정책 문자열의 핵심 지시어 |
| `test_no_inline_script_or_style_in_templates` | 템플릿에 인라인 `<script>`·`style=`이 없음 |
| `test_csrf_enforced_on_post_views` | 토큰 없이 POST하면 403 |
| `test_csrf_exempt_only_for_allowlisted_prefixes` | 허용 목록 밖은 예외 없음 |
| `test_parse_json_rejects_nan_infinity` | |
| `test_parse_json_depth_limit`, `test_parse_json_size_limit` | |
| `test_parse_json_non_object_rejected` | 배열·숫자·문자열 최상위 |
| `test_api_errors_are_problem_json` | `/api/` 오류가 `problem+json`이고 `code`·`request_id`를 가짐 |
| `test_malformed_inputs_never_500` | 깨진 JSON·잘못된 인코딩·거대 필드 수 등 입력 모음이 모두 4xx |
| `test_error_pages_do_not_leak_internals` | `DEBUG` 꺼진 상태의 500 응답 |
| `test_authenticated_pages_are_no_store` | |
| `test_check_deploy_has_no_warnings` | prod 설정으로 `check --deploy` 경고 0 |

**완료 증거**: 테스트 통과, `check --deploy` 경고 0, 브라우저 개발자 도구에서 응답 헤더 확인.

## 0-5. 파일 업로드·서빙 기반 (`assets`)

0-1 이후 **0-2~0-4와 독립적으로** 진행할 수 있다. `assets`는 다른 프로젝트 모듈을 import하지 않는다(L1).

**산출물**

```
assets/
  apps.py            # label = "assets"
  api.py             # validate_image, store, open_asset, exists  (외부 공개 면)
  validation.py      # Pillow 기반 판별·재인코딩
  storage.py         # AssetStorage(Protocol), LocalFileStorage
  views.py  urls.py  # GET /assets/<sha256>.<ext>
tests/test_assets_validation.py  tests/test_assets_storage.py  tests/test_assets_serving.py
```

**설정값**: `ASSET_MAX_BYTES`(기본 2MB, 1~2MB 범위에서 조정, 설계 §10 확정), `ASSET_MAX_PIXELS`(기본 16,000,000. 압축 폭탄 방어, 크기 규격 제한이 아니다), `MEDIA_ROOT`(코드·정적 경로 밖), `ASSET_SERVABLE_CHECK`(선택. 서빙 가능 여부를 판정하는 함수의 점 경로), `ASSET_PUBLIC_BASE_URL`(결정 응답의 `image_url`을 만들 때 쓰는 광고 서버의 공개 주소).

**할 일**

1. **검증**(`validate_image(fileobj)`): ① **`ASSET_MAX_BYTES + 1`바이트까지만** 읽어 초과를 판정(전부 읽지 않음) ② **내용으로 형식 판별** — Pillow가 판별한 형식이 **JPEG 또는 PNG**일 때만 허용(확장자·`Content-Type`은 신뢰하지 않음, SVG·GIF·WebP·BMP 거부) ③ 가로×세로가 `ASSET_MAX_PIXELS` 이하(Pillow의 폭탄 방어도 켬) ④ **애니메이션(다중 프레임) 거부** ⑤ 손상된 파일은 거부.
2. **재인코딩**: 디코딩한 뒤 **새로 인코딩해서 저장**한다(위치 정보 등 개인 정보 방지). **색은 먼저 sRGB로 변환한다**: 내장 ICC(Display P3·Adobe RGB·CMYK·그레이 등)로 sRGB 픽셀 값을 계산한 뒤, **픽셀만 새 이미지로 옮겨 저장**해 ICC·EXIF·XMP·텍스트 청크·dpi를 모두 버린다(Pillow 인코더는 `info`의 ICC를 되살리므로 새 이미지로 옮긴다). 프로필이 없거나 이미 sRGB면 변환하지 않고, **1MiB를 넘거나** 깨졌거나 이미지 모드와 색 공간이 안 맞는 프로필은 **거부하지 않고 sRGB로 간주**한다(조작된 프로필의 공격면은 위협 T27, 잔여 위험 §6). 투명도·알파는 보존. 형식은 유지한다(JPEG → JPEG, PNG → PNG). JPEG은 품질 고정, PNG는 최적화. 원본 바이트를 그대로 저장하지 않는다.
3. **저장 이름**: 재인코딩한 바이트의 **SHA-256 해시 + 확장자**(`<hash>.jpg|png`). 사용자 입력 이름은 어디에도 쓰지 않는다. 같은 내용은 같은 파일이 된다(중복 제거). 저장 위치는 해시 앞 2자 디렉터리로 나눈다.
4. **저장소**: `AssetStorage` 프로토콜(`put`, `open`, `exists`)과 `LocalFileStorage`. **임시 파일에 쓰고 `os.replace`로 확정**(반쯤 쓴 파일이 노출되지 않게), 권한은 소유자 읽기·쓰기 중심.
5. **서빙**: `GET /assets/<64자 hex>.<jpg|png>`. URL 패턴이 **형식을 정규식으로 제한**하므로 `..` 같은 경로 조작이 라우팅 단계에서 막힌다.
   - 응답 헤더: 확장자에서 정한 **고정 `Content-Type`**, `X-Content-Type-Options: nosniff`, **`Cache-Control: no-cache` + `ETag`(해시)**(설계 §10: 중단이 즉시 반영됨), `If-None-Match`가 맞고 서빙 가능하면 **304**, `Cross-Origin-Resource-Policy: cross-origin`(다른 출처 페이지가 이미지를 삽입해야 하므로).
   - **쿠키 없음**: 이 뷰는 세션을 건드리지 않고 `Set-Cookie`를 내지 않는다. 로그인 없이 열리는 공개 뷰로 표시한다(0-3).
   - **서빙 가능 여부**: `ASSET_SERVABLE_CHECK`로 지정된 함수가 있으면 호출하고, 거짓이면 **404**. 기본(Step 0)은 "파일이 있으면 가능"이다. 중단된 캠페인의 이미지를 막는 규칙은 Step 1에서 `campaigns`가 함수를 제공하고 `config`에서 연결한다 — **`assets`가 `campaigns`를 import하지 않으므로 계층 규칙(R1)이 지켜진다.**

**테스트**

| 파일 | 테스트 | 확인 |
|---|---|---|
| validation | `test_accepts_valid_png_and_jpeg` | |
| | `test_format_decided_by_content_not_extension` | PNG 내용에 `.jpg` 이름 → PNG로 저장 |
| | `test_rejects_svg_gif_webp_bmp` | |
| | `test_rejects_text_file_renamed_to_png` | |
| | `test_rejects_over_size_without_reading_all` | 초과 파일을 끝까지 읽지 않음 |
| | `test_rejects_decompression_bomb` | 작은 파일이 거대한 해상도를 선언 |
| | `test_rejects_animated_images` | |
| | `test_rejects_truncated_or_corrupt_image` | |
| | `test_reencode_strips_exif` | EXIF가 든 JPEG를 넣으면 저장본에 없음 |
| storage | `test_name_is_content_hash` | 입력 이름과 무관 |
| | `test_same_content_same_file` | |
| | `test_atomic_write_leaves_no_partial_file` | 중간 실패 시 최종 경로에 파일 없음 |
| serving | `test_serves_with_fixed_content_type_and_nosniff` | |
| | `test_etag_and_304` | |
| | `test_cache_control_no_cache` | |
| | `test_no_set_cookie_header` | |
| | `test_path_traversal_returns_404` | `..`, 이중 인코딩, 잘못된 해시 형식 |
| | `test_servable_check_false_returns_404` | |
| | `test_cross_origin_resource_policy_header` | |

**완료 증거**: 테스트 통과(`@tag("security")`), 실제 이미지 한 장을 업로드 서비스 함수로 저장하고 브라우저에서 URL로 열어 헤더 확인.

## 0-6. 감사·로깅·점검 스크립트·경계 검사

**산출물**: `foundation/audit.py`·`AuditLog` 모델, `foundation/middleware.py`(요청 ID), `scripts/check.sh`, `tests/boundaries/{test_layers,test_model_conventions}.py`, `tests/test_audit.py`, `tests/test_logging.py`

**할 일**

1. **감사 로그**: `AuditLog(actor, action, target_type, target_id, detail, ip, request_id, created_at)` — **추가만**(수정·삭제 시 예외). `foundation.api.record_audit(request, action, target, detail)`가 `detail`에서 `password|token|key|secret`이 든 키를 **제거**한다. Step 0에서 기록하는 사건: 가입, 로그인 성공·실패·잠금(axes 신호), 로그아웃, 비밀번호 변경·초기화, 사용자 역할·활성 상태 변경. 이후 단계가 정책 변경·중단·포인트 조정 등을 같은 함수로 추가한다. 관리자 화면에서는 **읽기 전용**.
2. **요청 ID**: 미들웨어가 요청마다 UUID를 만들고(들어온 `X-Request-ID`는 **UUID 형식일 때만** 수용), 응답 헤더로 돌려주며, 로그 레코드에 `request_id`를 붙인다.
3. **로그 위생**: 요청 본문·비밀번호·세션 키·`X-Media-Key`를 기록하지 않는다. 로그 필터로 민감 헤더를 가린다.
4. **`scripts/check.sh`**: 한 명령으로 아래를 차례로 실행하고 하나라도 실패하면 비정상 종료한다.
   `python manage.py check --deploy`(prod 샘플 환경) → `makemigrations --check --dry-run` → `python manage.py test`(경계 검사 포함) → `pip-audit -r requirements.txt` → `bandit -r . -x tests`.
   (`pip-audit`은 네트워크가 필요하다. 오프라인이면 실패 원인을 구분해 출력한다.)
5. **경계 검사**(R6): `tests/boundaries/test_layers.py`는 `ast`로 모든 `*.py`의 import를 읽는다. 층 정의는 **파일 위쪽 딕셔너리 하나**(`LAYERS = {"foundation": 0, "assets": 1, ..., "console": 4}`)다.
   - R1: 낮은 층이 높은 층을 import하면 실패, **같은 층끼리** import해도 실패
   - R2: 다른 모듈은 `<모듈>.api`만 import할 수 있다(`config`·`tests`는 예외)
   - (이후) `engine`은 `django`와 프로젝트 모듈을 import하지 않는다
6. **모델 규약 테스트**: 모든 앱이 **고정 `label`**을 갖고, 모든 모델이 **`db_table` 명시**(`<label>_<model>` 형식)를 갖는다(R3). 앱 사이 FK는 라벨 문자열이어야 한다.

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_audit_log_is_append_only` | 수정·삭제 시 예외 |
| `test_audit_detail_strips_secret_keys` | 비밀 키 제거 |
| `test_signup_and_login_events_recorded` | 가입·로그인 성공·실패·잠금이 기록됨 |
| `test_request_id_header_and_logging` | 형식이 맞는 ID만 수용, 로그에 포함 |
| `test_logs_never_contain_password_or_keys` | 로그인 실패 로그에 비밀번호가 없음 |
| `test_layer_rules`, `test_only_api_imports_across_modules` | 경계 검사 (위반 시 실패함을 의도적 위반 사례로 한 번 확인) |
| `test_all_models_have_explicit_db_table`, `test_app_labels_fixed` | |

**완료 증거**: `scripts/check.sh`가 한 번에 통과한다.

## Step 0 종료 점검표

- [x] `scripts/check.sh` 통과 (`check --deploy` 경고 0, 전체 테스트, `pip-audit`, `bandit`)
- [x] `python manage.py test --tag security` 단독 통과
- [x] 브라우저에서 가입 → 로그인 → 로그아웃, 5회 실패 잠금 확인 (5분 후 해제는 테스트로 확인: 브라우저로 5분을 기다리지는 않았다)
- [x] 광고주 계정으로 관리자 경로가 404, 새 URL이 보호 없이 추가되면 전수 점검이 실패 (의도적 변조로 확인)
- [x] 이미지 업로드 서비스 함수로 정상 이미지 저장·서빙, 위장·초과·폭탄 파일은 거부
- [x] Django 6.1 / axes 게이트 결과를 설계 §9에 기록 (통과, 5.2 LTS로 내리지 않음)
- [x] 설계 문서의 열린 결정 중 Step 0에서 확정된 것(가입 상한 값, 이미지 용량, 비밀번호 길이)을 §10으로 이동
- [x] `threat-model.md`가 현재 구현과 일치 (인용한 테스트가 실제로 존재하는지 `test_threat_model_sync`가 강제)

---

# 6. Step 1: 도메인 코어 (상세)

**Step 1 합격선**: HTTP 없이 **서비스 `api`만으로** 한 광고주의 전 과정이 돈다. 매체·슬롯·정책 등록 → 가입(지급) → 캠페인·광고그룹·소재·입찰 → 결정 한 건 저장. 그리고 `scripts/check.sh`가 계속 통과한다. 결정은 입찰·정책·소재를 나중에 고쳐도 변하지 않는다.

**Step 1 끝에 추가되는 모듈**: `masters`, `engine`, `campaigns`, `billing`, `records`(L1~L3, 설계 §6). `console`은 가입 흐름만 확장한다(지급 호출). 화면·HTTP API는 Step 2~3이다.

## 6.0 공통 규약 (Step 1 전체)

| # | 규약 | 이유 |
|---|---|---|
| 1 | **`api.py`는 ORM 모델이 아니라 불변 값 객체(`@dataclass(frozen=True)`)를 돌려준다.** 다른 모듈은 모델을 만지지 않는다 | 모듈 내부(필드·테이블)를 바꿔도 밖이 안 깨진다(R2). 모델을 넘기면 지연 조회로 N+1이 숨는다 |
| 2 | **규칙은 `services.py`(모듈 안)에만 둔다.** 모델 `save()`·뷰·관리자 화면에 규칙을 흩뿌리지 않는다. 광고주용 함수는 `user`를 받고 `foundation.api.owned_or_404`를 지난다(남의 것 404) | 설계 §6.6 규칙 1, T4 |
| 3 | **모델 규약**: 자원 모델은 UUID PK, **모든 테이블 PK는 UUIDv7(`uuid.uuid7`), 자동 증가 열 없음**(2026-10-08 적용. 순서가 필요한 원장은 `(지갑, seq)`), 고정 `label`, `db_table` 명시(`<label>_<model>`), 금액은 `PositiveBigIntegerField`(정수 포인트), 시각은 UTC. 앱 사이 FK는 라벨 문자열(`"masters.Slot"`)에 `on_delete=PROTECT`. 삭제 기능 없음 | R3, 설계 §3 C6 "삭제 없음" |
| 4 | **추가 전용 모델**(`BidPolicy`·`Bid`·`LedgerEntry`·`Decision`)은 `foundation.models.AppendOnlyModel`을 상속한다(Step 0 보완에서 만들었고 `AuditLog`가 이미 사용). 저장은 **항상 INSERT**(`force_insert`)이고, 같은 PK 새 인스턴스·`force_update`·`update_fields`·`bulk_create(update_conflicts=True)`·`update/delete`를 모두 막는다. 새 모델마다 "기존 PK로 덮어쓰기 불가" 회귀 테스트를 한 줄 추가한다 | 설계 §4.4-2·8·1 |
| 5 | **버전 번호**(`policy_version`·`bid_version`)는 한 트랜잭션에서 "현재 최대 + 1"을 저장하고, **호출자가 본 버전(`expected_version`)이 현재와 다르면 `StaleVersion`**(콘솔 계약의 409 `stale_version`)으로 거절한다. SQLite는 쓰기 트랜잭션이 직렬이라, `expected_version` 없이 "최대+1"만 쓰면 두 요청이 모두 성공(버전 n+1, n+2)해 나중 사람이 앞사람의 변경을 모르고 덮어쓴다. `(부모, 버전)` 유니크 제약은 다른 DB로 옮겼을 때를 위한 **안전망**이다 | 설계 §4.2, §6.5 |
| 6 | **감사**: 관리자 행위(정책 새 버전·중단/해제·포인트 조정 등)와 광고주의 주요 변경은 **서비스 안에서, 변경과 같은 트랜잭션에** 감사 로그를 남긴다(뷰가 빼먹을 수 없게, 커밋 뒤 감사 기록이 실패해 "감사 없는 변경"이 남지 않게). 요청 없이 호출되면 `record_audit(None, …)`이 **요청 ID를 `foundation.logging.request_id_var`에서** 가져오도록 `foundation`을 보강한다 | T13 |
| 7 | **시계는 서비스 함수가 `now` 인자로 받는다**(안 주면 `_now()` 한 곳에서만 읽는다). 기간·종료·예산 일 경계 테스트가 시각을 고정할 수 있다 | `AdRequest.now` 주입(설계 §4.3) |
| 8 | **테스트 데이터는 `tests/factories.py`의 작은 헬퍼 함수**(매체·슬롯·광고주·캠페인…)로 만든다. `factory_boy`는 쓰지 않는다 | §3 "쓰지 않는 것" |
| 9 | 모든 모델이 `tests/boundaries`의 `test_all_models_have_explicit_db_table`·`test_app_labels_fixed`를 자동으로 지난다. 새 앱은 `config/settings/base.py`의 `INSTALLED_APPS`에 등록한다 | R3, R6 |

## 6.1 단계 순서와 병렬

```
1-1 masters ──▶ 1-2 campaigns ──┐
1-4 engine ─────────────────────┼──▶ 1-5 records ──▶ 6.7 통합 시나리오
1-3 billing ────────────────────┘
```

혼자 진행하면 **1-1 → 1-4 → 1-2 → 1-3 → 1-5** 순서를 권한다. `engine`을 일찍 하는 이유는 1-2의 입찰 저장 규칙과 콘솔 안내값이 모두 `engine`의 적용 금액 함수를 쓰기 때문이다. 1-3(`billing`)·1-4(`engine`)는 서로 독립이라 나눠 맡을 수 있다.

## 6.2 1-1 `masters` (매체·슬롯·입찰 정책)

**산출물**

```
masters/
  apps.py  models.py  services.py  api.py  admin.py(등록만, 화면은 Step 3-1)
  migrations/0001_initial.py
tests/test_masters_models.py  tests/test_masters_services.py
foundation/models.py  (AppendOnlyModel 믹스인, AuditLog 교체)  foundation/audit.py (요청 ID 보강)
```

**모델**

| 모델 | 필드 | 제약 |
|---|---|---|
| `Media` | `media_id`, `name`, `is_active`, `created_at` | `name` 유일 |
| `Slot` | `slot_id`, `media`(FK), `name`, `pricing_unit`(`IMPRESSION`·`CLICK`·`CONVERSION`), `is_active`, `created_at` | `(media, name)` 유일(제안: 매체 안에서 유일, 설계 §4 식별자 규칙). **`pricing_unit`은 만든 뒤 바꿀 수 없다**(`save()`가 변경을 거부) |
| `BidPolicy`(추가 전용) | `slot`(FK), `policy_version`, `floor_amount`, `base_amount`, `cap_amount`, `changed_by`(사용자 ID), `changed_at`, `reason` | `(slot, policy_version)` 유일, **DB `CHECK`: `0 < floor ≤ base ≤ cap`** |

**`masters.api` 함수** (모두 값 객체 반환)

| 함수 | 내용 |
|---|---|
| `create_media(actor, name)`, `set_media_active(actor, media_id, active)` | 관리자 전용. 감사 |
| `create_slot(actor, media_id, name, pricing_unit, floor, base, cap, reason)` | **슬롯과 최초 정책(버전 1)을 한 트랜잭션에 만든다.** 따라서 모든 슬롯은 항상 현재 정책을 가진다(`no_policy` 상태가 생기지 않는다) |
| `add_policy_version(actor, slot_id, floor, base, cap, reason, expected_version)` | 새 버전 추가(수정 아님). 서비스 검증 + DB 제약. **`expected_version`이 현재와 다르면 `StaleVersion`**(관리자 두 명이 같은 화면에서 저장하면 나중 쪽이 거절되어 앞 변경을 모르고 덮어쓰지 않는다) |
| `add_policy_version_bulk(actor, expected_versions, floor, base, cap, reason)` | **일괄 입력**(설계 §4.6). `expected_versions`는 `{slot_id: 본 버전}`. 한 트랜잭션, 슬롯마다 자기 버전이 쌓인다. 하나라도 어긋나거나 실패하면 전부 취소 |
| `get_slot(slot_id)`, `list_slots(active_only=True)` | 현재 정책 포함(`SlotView`, `PolicyView`) |
| `get_slots_with_policy(slot_ids)` | **한 번의 질의**로 여러 슬롯의 현재 정책(결정 조립용, N+1 방지) |
| `set_slot_active(actor, slot_id, active)` | 비활성 슬롯은 새 광고그룹이 못 고르고 후보에서 빠진다 |

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_policy_check_constraint_in_db` | 서비스를 우회해 `floor > base`를 직접 저장해도 DB가 거부 |
| `test_policy_service_rejects_zero_negative_and_order_violation` | 0·음수·순서 위반 거부(서비스 오류) |
| `test_policy_is_append_only` | 수정·삭제·`update()` 거부 |
| `test_add_policy_version_increments_per_slot` | 슬롯별로 1부터 증가, 슬롯끼리 영향 없음 |
| `test_policy_stale_expected_version_rejected` | 같은 `expected_version`으로 두 번 저장하면 두 번째가 `StaleVersion`, 버전은 n+1 하나만 생김(순차 호출) |
| `test_concurrent_policy_saves_only_one_wins` | 스레드 2개가 같은 `expected_version`으로 동시에 저장 → 정확히 한쪽만 성공(SQLite `IMMEDIATE` 직렬화 아래에서도) |
| `test_policy_cannot_be_overwritten_by_existing_pk` | 기존 PK의 새 인스턴스·upsert로 정책 행을 못 바꿈 |
| `test_slot_pricing_unit_immutable` | 변경 시도 거부 |
| `test_create_slot_creates_first_policy_atomically` | 정책 입력 오류면 슬롯도 안 생김 |
| `test_slot_name_unique_per_media_only` | 다른 매체에서는 같은 이름 가능 |
| `test_bulk_policy_is_all_or_nothing` | 일괄 입력 중 한 슬롯이 실패하거나 버전이 어긋나면 전부 취소 |
| `test_get_slots_with_policy_single_query` | `assertNumQueries(1)` |
| `test_admin_actions_are_audited` | 정책 추가·매체 변경이 감사 로그에 남고 요청 ID가 채워짐 |
| `test_non_admin_actor_rejected` | 관리자가 아니면 거부 |

**완료 증거**: 위 테스트 통과, `scripts/check.sh` 통과, 경계 검사가 `masters`를 `foundation` 외에는 import하지 않음을 확인.

## 6.3 1-4 `engine` (선택 로직, 순수)

`engine`은 **Django·프로젝트 모듈을 import하지 않는다**(경계 테스트가 강제). 설정은 읽지 않고 호출하는 쪽(`records`)이 정책 이름·필터 목록을 인자로 넘긴다(R4).

**산출물**

```
engine/
  api.py                 # decide(), effect_of(), is_expired(), 타입 재공개
  types.py               # Candidate, Eligible, AdRequest, Selection, Effect, DecisionResult
  pricing.py             # effect_of(bid, floor, cap), is_expired(ends_at, now)   ← 규칙이 사는 곳
  filters/{__init__,chain,status,period,floor,budget,balance}.py
  policies/{base,highest_bid}.py
  registry.py            # 이름 → 구현 (정책, 필터)
tests/test_engine_pricing.py  tests/test_engine_filters.py  tests/test_engine_policies.py
```

**할 일**

1. **타입**(설계 §4.3 필드 표 그대로): `Candidate`, `Eligible`(= `Candidate` + `applied_amount`), `AdRequest`(`subject_id`, `slot_id`, `now`), `Selection`(`chosen: Eligible | None`, `trace: dict`). 모두 불변. 금액은 `int`(`bool`·`float` 거부), 시각은 UTC 지정(naive 거부), 생성 시 검증.
2. **`effect_of(bid, floor, cap) -> Effect(eligible, applied_amount, reason)`**: 설계 §4.2 표를 코드로. `reason`은 C6 `SlotEffect`와 같은 값(`within_range`·`capped_at_cap`·`below_floor`). 콘솔의 `effects`·`bid-preview`는 이 함수를 그대로 부른다(`no_policy`·`slot_inactive`는 `masters` 값으로 콘솔이 붙인다).
3. **`is_expired(ends_at, now)`**: `ends_at`이 `None`이면 거짓, `ends_at ≤ now`이면 참(**종료 시각 포함**, C6의 "끝나는 시각(미포함)"과 같은 뜻). 선택 필터·`campaigns`의 전환 작업·수정 가드가 모두 이 함수를 쓴다.
4. **필터 체인**: 순서 고정, 각 필터는 `(Eligible, request) -> 거절 사유 | None`. 순서: ① `status`(캠페인 `ACTIVE`, 광고그룹 `enabled`) ② `period`(`period_start ≤ now`, `not is_expired`) ③ `floor`(`below_floor`) ④ `budget`(`remaining_daily_budget ≥ applied_amount`) ⑤ `balance`(`wallet_balance ≥ applied_amount`). 적용 금액은 필터 앞에서 `effect_of`로 계산한다. 거절은 사유별 **개수만** `DecisionResult.rejected`에 담는다(후보가 많아도 커지지 않게, `records`가 `Decision.rejected_counts`로 저장). 후보는 **처음 걸린 필터**의 사유로 한 번만 센다. 사유 값: `campaign_not_active`·`ad_group_disabled`·`not_started`·`expired`·`below_floor`·`budget_exhausted`·`insufficient_balance`.
5. **`SelectionPolicy` 프로토콜과 `highest-bid/v1`**: 적용 금액 최대, **동점이면 `rng`로 무작위**, `trace`에 동점 후보 ID 목록과 뽑힌 값. 후보가 없으면 `chosen=None`. `request`는 읽지 않는다.
6. **`decide(candidates, request, rng, policy="highest-bid/v1", filters=DEFAULT) -> DecisionResult(selection, considered, rejected)`**: 가격 계산 → 필터 → 정책 선택. 알 수 없는 정책·필터 이름은 즉시 오류(`UnknownName`, 조용히 기본값으로 바꾸지 않는다). 요청 슬롯과 다른 슬롯의 후보가 섞이면 오류. `floor` 필터 없이 `budget`·`balance`만 쓰면(하한 미만 후보가 적용 금액 없이 남음) 오류. 같은 시드면 **입력 순서와 무관하게** 같은 결과가 나오도록 동점 후보를 광고그룹 ID로 정렬한 뒤 뽑는다.

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_effect_table_design_example` | 입찰 30 → 슬롯 A(10~50) 30, B(10~20) 20, C(40~100) 제외 |
| `test_effect_boundaries` | `bid == floor` 노출, `bid == cap` 그대로, `cap + 1` → `cap`, `floor - 1` 제외 |
| `test_is_expired_boundaries` | `ends_at == now`는 종료, `None`은 무기한, `now - 1`초 |
| `test_types_reject_bad_values` | 소수·`bool`·음수·naive 시각 거부, 불변 |
| `test_each_filter_rejects_with_reason` | 상태·광고그룹 꺼짐·시작 전·종료·하한·예산·잔액 각각 |
| `test_budget_and_balance_boundary` | `remaining == applied`는 통과, 1 모자라면 거절 |
| `test_filter_order_first_failure_wins_and_counts_by_reason` | 처음 걸린 필터의 사유로 한 번만, 사유별 개수 |
| `test_highest_bid_picks_max_applied_amount` | 상한에 닿은 두 입찰은 동점 |
| `test_tie_break_reproducible_with_seed` | 같은 시드 → 같은 선택 |
| `test_tie_break_is_uniform` | 3자 동점 3,000회 → 각 후보 비율이 허용 범위 안 |
| `test_subject_id_does_not_change_result` | `subject_id`만 바꿔도 같은 입력 → 같은 결과 |
| `test_no_candidates_returns_none` | `chosen=None` |
| `test_policy_swappable_by_name` | 더미 정책을 등록해 이름만 바꾸면 다른 알고리즘이 돌고 `Selection` 구조는 같음 |
| `test_unknown_policy_or_filter_raises` | |
| 경계 검사(기존) | `engine`이 `django`·프로젝트 모듈을 import하지 않음 |

**완료 증거**: DB·Django 설정 없이 `engine` 테스트만 단독으로 통과(`python -m unittest tests.test_engine_*`가 마이그레이션 없이 돈다), 경계 검사 통과.

## 6.4 1-2 `campaigns` (캠페인·광고그룹·소재·입찰·재검토 요청)

**산출물**

```
campaigns/
  apps.py  models.py  services.py  api.py  transitions.py  queries.py  admin.py(등록만)
  management/commands/end_expired_campaigns.py
  migrations/0001_initial.py
tests/test_campaigns_models.py  tests/test_campaigns_transitions.py
tests/test_campaigns_services.py  tests/test_campaigns_ended.py  tests/test_campaigns_review.py
```

**모델**

| 모델 | 필드 | 제약·규칙 |
|---|---|---|
| `Campaign` | `campaign_id`, `owner`(FK `foundation.User`), `name`, `starts_at`, `ends_at`(없으면 `NULL`), `daily_budget`, `status`, `ended_from`, `suspended_reason`, `suspended_at`, `created_at`, `updated_at` | `daily_budget > 0`, `ends_at > starts_at`(있을 때) |
| `AdGroup` | `ad_group_id`, `campaign`, `name`, `pricing_unit`(생성 후 고정), `enabled`, `created_at` | |
| `AdGroupSlot` | `ad_group`, `slot`(FK `masters.Slot`) | `(ad_group, slot)` 유일. **슬롯의 과금 단위 = 광고그룹의 과금 단위**여야 저장 |
| `Creative` | `creative_id`, `ad_group`, `title`, `redirect_url`(https), `image_name`(assets 이름), `image_bytes`, `enabled`, `created_at`, `updated_at` | `image_name` 인덱스. 광고그룹당 개수는 설정 `MAX_CREATIVES_PER_AD_GROUP`(V1 = 1)로 서비스가 제한 |
| `Bid`(추가 전용) | `ad_group`, `bid_version`, `amount`, `created_by`, `created_at` | `(ad_group, bid_version)` 유일, `amount > 0`. **하한 미만·상한 초과도 저장** |
| `ReviewRequest`(추가 전용 기록, 상태만 닫힘) | `review_request_id`, `campaign`, `message`, `status`(`OPEN`·`RELEASED`·`REJECTED`·`CLOSED_ENDED`), `response_note`, `created_at`, `closed_at` | **캠페인당 `OPEN`은 하나**(`UniqueConstraint(condition=status=OPEN)`) |

**상태 전이 표 (`transitions.py` 한 파일, 상태를 쓰는 곳은 여기뿐 — 설계 §4.4-5)**

| 동작 | 이전 → 이후 | 누가 |
|---|---|---|
| `pause` | `ACTIVE → PAUSED` | 광고주 |
| `resume` | `PAUSED → ACTIVE` | 광고주 |
| `suspend` | `ACTIVE`·`PAUSED → SUSPENDED` | 관리자(사유 필수) |
| `release` | `SUSPENDED → ACTIVE` | 관리자 |
| `end` | `ACTIVE`·`PAUSED → ENDED` (`ends_at`을 현재로 확정) | 광고주 |
| `expire` | `ACTIVE`·`PAUSED`·`SUSPENDED → ENDED` | 시스템(`ends_at ≤ now`) |
| (그 밖) | `ENDED`에서 나가는 전이 없음 | — |

**서비스 규칙**

1. **`ENDED` 가드**: 캠페인과 그 하위(광고그룹·소재·입찰)의 모든 쓰기 앞에서 `status == ENDED` **또는** `is_expired(ends_at, now)`이면 `CampaignEnded`(409 `ended`). 저장된 상태가 갱신되기 전에도 막는다. 가드는 `services.py`의 **함수 하나**(`_assert_open`)이고 모든 쓰기 함수가 지난다.
2. **종료일 변경**: 종료 전에는 늘리거나 줄일 수 있고(`None` 허용), 새 값은 `now`보다 뒤여야 한다. 시작보다 뒤여야 한다.
3. **`end_expired_campaigns(now)`**: `ends_at ≤ now`이고 `ENDED`가 아닌 캠페인을 **조건부 `UPDATE`**로 `ENDED`로 바꾸고 `ended_from`을 기록, `OPEN` 재검토 요청을 `CLOSED_ENDED`로 닫는다. 멱등. 한 트랜잭션. 관리 명령으로도 실행한다(주기 실행은 §7-9와 함께 인프라가 정한다).
4. **입찰**: `add_bid(user, ad_group_id, amount, expected_version)` — `expected_version`이 현재와 다르면 `StaleVersion`(409). 입력은 거절하지 않고 저장한다(0 이하·최대값 초과만 400).
5. **광고그룹**: 슬롯 목록 변경 시 모두 같은 단위·활성 슬롯이어야 한다(`unit_mismatch`). `pricing_unit`을 보내면 항상 `unit_immutable`.
6. **소재**: 이미지는 `assets.api.validate_image` → `store`를 서비스가 호출한다(`ImageRejected`는 그대로 전달). `redirect_url`은 `https`만. 이미지 교체 시 새 이름으로 바꾸고 이전 파일은 지우지 않는다(과거 결정이 참조할 수 있다).
7. **관리자 동작**: `suspend_campaign(actor, campaign_id, reason)`, `release_campaign(actor, campaign_id)`(`OPEN` 요청이 있으면 `RELEASED`), `reject_review_request(actor, review_request_id, note)`(정지 유지, 사유 필수). 모두 감사.
8. **재검토 요청**: `create_review_request(user, campaign_id, message)`는 `SUSPENDED`일 때만(아니면 `not_suspended`), `OPEN`이 이미 있으면 `review_pending`.
9. **쿼터(광고주당)**: 캠페인·광고그룹·소재 개수와 이미지 총량. 기본값 **[제안, 설계 §7-5는 열림]**: 캠페인 20, 광고그룹 100, 소재 100, 이미지 100MB. 모두 설정값. 초과는 `LimitExceeded`(409 `limit_exceeded`).
10. **읽기 함수** (모듈 밖에서 쓰는 것): `get_campaign`, `list_campaigns(user)`, `get_ad_group`, `list_bids`, `current_bid`, `list_review_requests`, **`candidate_facts_for_slot(slot_id)`**, **`is_asset_servable(name)`**.
    - `candidate_facts_for_slot`은 한 번의 질의(`select_related`)로 (캠페인·광고그룹·소재·현재 입찰)을 돌려준다. **조회 조건은 구조적 소속만 쓴다**: 저장된 `status = ACTIVE`, 광고그룹 `enabled`, 소재 `enabled`, 그 슬롯을 고른 광고그룹. **기간·금액 판정은 조회에 넣지 않는다**(판정은 `engine` 한 곳, 설계 §4.3). 상태 갱신이 늦은 종료 캠페인이 섞여 와도 `engine`이 거른다.
    - `is_asset_servable(name)`은 그 이름을 쓰는 소재가 있고 캠페인이 `ACTIVE`·`PAUSED`이며 기간이 끝나지 않았을 때만 참. `config`가 `ASSET_SERVABLE_CHECK = "campaigns.api.is_asset_servable"`로 연결한다(Step 0-5의 설정 훅, `assets`는 `campaigns`를 import하지 않는다).

**테스트**

| 파일 | 테스트 | 확인 |
|---|---|---|
| `test_campaigns_transitions` | `test_transition_table_allows_only_listed` | 표에 없는 전이는 거부, `ENDED`에서 나가는 전이 없음 |
| | `test_suspended_blocks_advertiser_status_change` | 광고주의 `pause`·`resume`·`end`는 `suspended` |
| | `test_only_transitions_module_writes_status` | 소스 검사: `status`를 직접 대입하는 코드가 `transitions.py` 밖에 없음 |
| `test_campaigns_ended` | `test_end_expired_moves_all_three_states` | `ACTIVE`·`PAUSED`·`SUSPENDED` 모두 `ENDED`, `ended_from` 기록 |
| | `test_end_expired_is_idempotent_and_conditional` | 두 번 돌려도 한 번만, 아직 안 끝난 캠페인은 불변 |
| | `test_edit_rejected_when_expired_but_status_still_active` | **상태 갱신 전 구간**에서도 수정·재개·종료일 연장이 `ended` |
| | `test_ended_blocks_all_writes_below` | 광고그룹·소재·입찰 쓰기 모두 `ended`, 읽기는 가능 |
| | `test_early_end_sets_ends_at_now_and_is_irreversible` | 두 번째 호출은 `ended`, `SUSPENDED`는 `suspended` |
| | `test_ends_at_must_be_in_future_and_after_start` | |
| | `test_end_closes_open_review_request` | `CLOSED_ENDED`, 종료된 캠페인 해제는 `ended` |
| | `test_extend_vs_expire_race` | 연장 커밋이 먼저면 연장이 이기고 전환은 건너뜀, 전환이 먼저면 연장은 `ended` |
| `test_campaigns_services` | `test_ad_group_unit_must_match_slots` / `test_pricing_unit_immutable` | `unit_mismatch`·`unit_immutable` |
| | `test_bid_out_of_range_is_stored` | 하한 미만·상한 초과 입찰 저장 |
| | `test_bid_stale_version_conflict` | 동시 두 입찰 중 한쪽이 `StaleVersion` |
| | `test_bid_is_append_only` | |
| | `test_other_users_objects_are_404` (`@tag("security")`) | 모든 광고주용 함수가 남의 캠페인·광고그룹·소재를 404 |
| | `test_quota_limits` | 개수·총량 초과 `limit_exceeded` |
| | `test_creative_image_validated_and_https_only` | 위장·초과 이미지, `http://` 거부 |
| | `test_one_creative_per_ad_group_in_v1` | 설정을 올리면 늘어남 |
| | `test_candidate_facts_single_query_and_structure_only` | `assertNumQueries`, 기간이 끝난 캠페인도 조회에는 포함(판정은 engine) |
| | `test_is_asset_servable` | `ACTIVE`·`PAUSED` 참, `SUSPENDED`·`ENDED`·미등록 이름 거짓 → **중단된 캠페인 이미지가 서버에서 404** |
| `test_campaigns_review` | `test_review_request_only_when_suspended_and_one_open` | `not_suspended`·`review_pending` |
| | `test_release_and_reject` | 해제는 `ACTIVE`+`RELEASED`, 반려는 정지 유지+사유 |
| | `test_admin_actions_are_audited` | 중단·해제·반려 |

**완료 증거**: 테스트 통과, `check.sh` 통과, 이미지 서빙 URL이 중단 즉시 404가 되는 것을 `Client`로 확인(`assets` 뷰 + `ASSET_SERVABLE_CHECK`).

## 6.5 1-3 `billing` (지갑·원장·예산·과금 정책)

`billing`은 `campaigns`를 import하지 않고 캠페인을 **ID 값**으로만 다룬다.

**산출물**

```
billing/
  apps.py  models.py  services.py  api.py  budget_day.py  admin.py(등록만)
  policies/{base,by_unit}.py          # ChargePolicy, by-unit/v1
  management/commands/recompute_spend.py  management/commands/check_ledger.py
  migrations/0001_initial.py
tests/test_billing_ledger.py  tests/test_billing_budget.py  tests/test_billing_charge.py
console/views/auth.py (가입 흐름이 지급을 호출)
```

**모델**

| 모델 | 필드 | 제약 |
|---|---|---|
| `Wallet` | `owner`(FK `foundation.User`, 유일), `balance`, `created_at` | `balance ≥ 0`(DB `CHECK`) |
| `LedgerEntry`(추가 전용) | `entry_id`, `wallet`, `entry_type`(`SIGNUP_GRANT`·`CHARGE`·`ADMIN_ADJUST`·`TOPUP`), `amount`(부호 있는 정수), `balance_after`, `campaign_id`(UUID, FK 아님), `reaction_ref`(유일, 과금 멱등 키), `charge_policy`, `shortfall`, `note`, `created_at` | `(wallet) + SIGNUP_GRANT` 유일(부분 유니크), `reaction_ref` 유일(`NULL` 제외) |
| `CampaignSpend` | `campaign_id`, `budget_day`(날짜), `spent` | `(campaign_id, budget_day)` 유일. **원장에서 다시 계산할 수 있는 파생값** |

**`billing.api`**

| 함수 | 내용 |
|---|---|
| `grant_signup(user)` | 설정값 `SIGNUP_GRANT_POINTS`(기본 **50,000**)를 `SIGNUP_GRANT`로 지급, 지갑 생성. **한 사용자에 한 번만**(재호출은 변화 없음) |
| `adjust(actor, user_id, amount, note)` | 관리자 조정(부호 있는 정수, 사유 필수). 잔액을 0 밑으로 내리는 음수 조정은 거부. 감사 |
| `charge_for_reaction(owner_id, campaign_id, reaction_type, pricing_unit, applied_amount, reaction_ref, now)` | 설정된 `ChargePolicy`가 0이라고 하면 `None`(과금 없음). **멱등** 과금(Step 2-5에서 호출). 한 트랜잭션에서 ① `CHARGE` 항목 ② 잔액 ③ `CampaignSpend`. **남은 잔액만큼만 차감**하고 부족분은 `shortfall`에 기록. 같은 `reaction_ref`는 처음 결과 그대로 |
| `get_wallet(user, now)`, `list_ledger(user, before, limit)` | 잔액·`spent_today`(원장의 오늘 CHARGE 합)·`resets_at`, 원장 내역(최신순, `(항목, 다음 커서)` 반환) |
| `balances(owner_ids)`, `spend_today(campaign_ids, now)` | **한 번의 질의**로 여러 값(결정 조립용, N+1 방지) |
| `budget_day_of(instant)`, `next_reset(instant)` | **예산 일 경계 함수 한 곳.** `BUDGET_DAY_OFFSET_HOURS`(기본 0 = UTC 자정). 소진액 집계와 화면의 리셋 시각이 같은 함수를 쓴다 |
| `recompute_spend()` | 원장에서 `CampaignSpend`를 다시 만든다(경계 설정을 바꾼 뒤 실행) |
| `check_ledger()` | 모든 지갑에서 `balance == Σ amount`, `balance_after`의 연속성을 확인(어긋나면 목록 반환·명령은 비정상 종료) |
| `ChargePolicy` / `by-unit/v1` | 반응 유형이 광고그룹 과금 단위와 같을 때만 과금, 금액은 Decision의 적용 금액. 어떤 정책이었는지 `charge_policy`에 이름 기록(R8). 정책 이름은 설정으로 고른다 |

**가입 흐름 확장**: `console`의 가입 뷰가 **한 트랜잭션(`transaction.atomic`) 안에서** `foundation.api.create_advertiser` → `billing.api.grant_signup`을 차례로 부른다(`foundation`이 `billing`을 알지 않는다) [3-0c `4bebbe5`에서 이 묶음을 `billing.register_advertiser`로 옮기고 가입 뷰는 그것만 부른다 — 콘솔 경계 규칙]. 지급이 실패하면 가입도 취소된다. 감사 로그에 `account.signup`과 `billing.signup_grant`가 남는다.

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_signup_grants_configured_points_once` | 가입 → 잔액 = 설정값, 원장 `SIGNUP_GRANT` 1건, 재호출 무변화 |
| `test_signup_and_grant_same_transaction` | 지급 실패 시 사용자도 안 생김 |
| `test_balance_equals_ledger_sum_after_any_sequence` | 지급·과금·조정을 무작위로 섞은 뒤 `check_ledger`가 통과 |
| `test_balance_never_below_zero` | 잔액보다 큰 과금은 잔액만큼만, `shortfall` 기록 / DB `CHECK`가 직접 쓰기도 거부 |
| `test_charge_idempotent_by_reaction_ref` | 같은 키 2번 → 1건, 두 번째는 처음 결과 반환 |
| `test_charge_concurrent_same_ref_once` | 스레드 2개가 같은 키로 과금 → 원장 1건, 잔액 1번만 차감 |
| `test_ledger_is_append_only` | 수정·삭제·`update()` 거부 |
| `test_adjust_requires_admin_note_and_audited` | 비관리자·사유 없음 거부, 감사 |
| `test_budget_day_boundary_default_utc` | `00:00:00Z`가 새 날, `23:59:59Z`는 어제 |
| `test_budget_day_offset_and_recompute_matches_ledger` | 오프셋을 +9로 바꾸고 `recompute_spend` → 소진액이 원장 재집계와 일치 |
| `test_spent_today_resets_at_boundary` | |
| `test_charge_policy_by_unit` | 단위가 같은 반응만 과금, 다른 유형은 0, 정책 이름 기록 |
| `test_charge_policy_swappable_by_setting` | 더미 정책 이름으로 교체 |
| `test_balances_single_query` | `assertNumQueries` |

**완료 증거**: 테스트 통과, `check_ledger` 명령이 깨끗한 DB에서 0으로 종료, 브라우저로 새 가입 시 잔액 50,000(가입 → 지급 → `get_wallet`, 서버 로그 확인), `check.sh` 통과.

## 6.6 1-5 `records` (결정 유스케이스)

**산출물**

```
records/
  apps.py  models.py  services.py  api.py  assemble.py
  migrations/0001_initial.py
tests/test_records_decision.py  tests/test_records_assemble.py
```

**모델**: `Decision`(추가 전용 불변 스냅샷)

| 필드 | 설명 |
|---|---|
| `decision_id`, `media_id`, `slot_id`, `subject_id`, `decided_at`(= 요청의 `now`) | 요청 쪽 사실 |
| 선택된 광고 **열**: `owner_id`(과금할 지갑 주인), `campaign_id`, `ad_group_id`, `creative_id`, `bid_amount`, `applied_amount`, `pricing_unit`, `bid_version`, `policy_version` (모두 채워지거나 모두 `NULL` — DB `CHECK`) | **선택된 광고의 스냅샷**(없으면 `NULL`, "광고 없음"도 한 건으로 기록). 이후 반응 처리가 과금에 필요한 값을 결정에서 읽는다 |
| `selection_policy`(이름), `trace`(JSON), `candidate_count`, `rejected_counts`(JSON) | 어떤 알고리즘이 어떤 근거로 골랐는지 |
| `snapshot`(JSON) | 응답에 필요한 값: 소재 제목·이동 주소·이미지 이름 **그 시점 값** |

**`assemble.py` (후보 조립, 판정 없음)**: 슬롯 하나에 대해 ① `masters.api.get_slots_with_policy`(정책) ② `campaigns.api.candidate_facts_for_slot`(캠페인·광고그룹·소재·입찰) ③ `billing.api.balances`·`spend_today`(잔액·남은 일예산)를 **각각 한 번의 질의**로 읽어 `Candidate` 목록으로 조립한다. 총 질의 수는 후보 수와 무관하다.

**`records.api.decide(media_id, slot_id, subject_id, now, rng) -> DecisionView`** (Step 2-3의 `POST /decisions`가 부른다). 조회용 `get_decision(media_id, decision_id)`는 **그 결정을 만든 매체만** 볼 수 있다(아니면 404).

1. 슬롯이 해당 매체의 활성 슬롯인지 확인(아니면 `NotFound`).
2. `assemble` → `engine.api.decide(..., policy=settings.ADS_SELECTION_POLICY)`.
3. 결과를 `Decision`으로 **저장한 뒤에만** 값 객체를 돌려준다(설계 §4.4-12, 저장 실패는 예외로 전파되어 `decision_id`가 나가지 않는다).
4. 이미지 URL은 `assets.api.asset_url(image_name)`으로 응답 단계에서 붙인다(결정에는 이름만 저장).

**테스트**

| 테스트 | 확인 |
|---|---|
| `test_decision_snapshot_survives_edits` | 입찰 새 버전·정책 새 버전·소재 제목 수정·캠페인 중단·종료 **이후에도 과거 `Decision` 내용이 그대로** |
| `test_decision_is_append_only` | 수정·삭제 거부 |
| `test_decision_records_both_versions_and_policy_name` | `bid_version`·`policy_version`·`selection_policy` |
| `test_no_ad_is_recorded_as_decision` | 후보 없음도 한 건 저장, `chosen` 없음 |
| `test_assemble_query_count_independent_of_candidates` | 후보 1개와 50개에서 질의 수 같음 |
| `test_unit_aware_candidates` | 슬롯 단위와 다른 광고그룹은 후보가 되지 않음 |
| `test_ended_and_stale_active_campaign_excluded` | 상태가 아직 `ACTIVE`인 만료 캠페인은 `engine`이 거름 |
| `test_wallet_and_budget_gate_exposure` | 잔액 부족·일예산 소진 캠페인은 후보에서 빠지고, 충전/예산 증액 후 다시 노출 |
| `test_decision_not_saved_when_storage_fails` | 저장 예외 시 결정이 응답으로 나가지 않음 |
| `test_selection_policy_swap_by_setting_keeps_decision_shape` | 설정만 바꿔 다른 정책, `Decision` 열 구조 동일 |
| `test_only_engine_decides` | 소스 검사: `records`에 적용 금액·하한 판정 코드가 없음(`engine.api` 호출만) |

**완료 증거**: 테스트 통과, `check.sh` 통과.

## 6.7 Step 1 통합 시나리오 (광고 도메인은 서비스 `api`만, 가입만 console 뷰)

`tests/test_step1_scenario.py` 하나가 아래를 순서대로 실행한다. **이것이 Step 1의 합격 증거**다. 광고 도메인 흐름(2단계 이후)은 서비스 `api` 호출뿐이고, **가입(2단계)만 console 가입 뷰를 Django Client로** 부른다(지급이 가입과 한 트랜잭션임을 함께 보이려는 것). 서비스 조합 증거와 가입 뷰 증거는 `test_signup_flow_creates_wallet_with_points_and_audit`·`test_signup_and_grant_same_transaction`이 따로도 남긴다.

1. 관리자: 매체 1·슬롯 3(과금 단위 노출 둘, 클릭 하나) 등록, 정책 `A 10~50`, `B 10~20`, `C 40~100`.
2. 광고주 두 명 가입(각 50,000 지급, 감사 로그 2건씩).
3. 광고주 1: 캠페인(기간·일예산) → 광고그룹(슬롯 A·B·C 중 노출 단위) → 소재(실제 PNG) → 입찰 30. 광고주 2: 입찰 25 광고그룹.
4. 슬롯 A에 결정 → 광고주 1 선택(적용 30), 슬롯 B → 적용 20, 슬롯 C → 광고주 1 제외. 같은 적용 금액 동점 상황에서 두 광고주가 고르게 뽑힘(시드 고정).
5. 정책·입찰·소재 수정, 캠페인 중단 후 **첫 결정이 그대로**이고, 중단된 캠페인 이미지는 서빙 404.
6. 조기 종료 → 모든 쓰기 `ended`, 이후 결정에서 제외.
7. `check_ledger` 통과, 마지막으로 `scripts/check.sh` 전체 통과.

## 6.8 Step 1 종료 점검표

- [x] 1-1~1-5 테스트 통과, `scripts/check.sh` 통과(`check --deploy` 경고 0, 마이그레이션 최신, 테스트 356개, `pip-audit` 0, `bandit` 0)
- [x] `engine` 테스트가 Django 설정 없이 단독으로 통과(`env -i … python -m unittest tests.test_engine_*`), 경계 검사(R1·R2·`engine` 순수성) 통과. 경계 검사가 구현 중 R2 위반 2건을 실제로 잡음
- [x] 통합 시나리오(`tests/test_step1_scenario.py`) 통과, 두 광고주의 서로 다른 객체 접근이 모두 404(`test_other_users_objects_are_404`)
- [x] 상태를 쓰는 코드가 `campaigns/transitions.py`뿐(`test_only_transitions_module_writes_status`), 적용 금액·종료 판정 코드가 `engine`뿐(`test_pricing_and_expiry_rules_are_defined_only_in_engine`, `test_only_engine_decides`). DB 조건식(`expire_due`·`is_asset_servable`)은 `is_expired`를 쿼리로 다시 쓴 것이라 경계에서 일치함을 `test_db_predicates_agree_with_is_expired`로 대조
- [x] `threat-model.md` 갱신: T4·T19·T23, §5.2(원장 변조·이중 과금·결정 스냅샷), 신규 T28(정책)·T29(자격 필터)·T30(종료·중단 우회)·T31(포인트 정합성)·T32(결정 기록), 모두 실제 테스트 이름으로 연결(`test_threat_model_sync`가 강제)
- [x] C6 계약 리뷰: 아래 §6.8.1 대조표. 어긋난 곳은 없고, 서비스 밖(콘솔 구성)에서 채울 값은 Step 3으로 명시
- [x] 설계 문서 §10에 Step 1 결정 반영(쿼터 기본값은 **설정값 기본**으로 기록하고 §7-5는 CAPTCHA 때문에 열어 둠)
- [x] 진행 상태 표(§10) 갱신

### 6.8.1 C6 계약과 서비스 `api` 대조

| C6 (console.openapi.yaml) | 서비스 | 비고 |
|---|---|---|
| `POST /signup` | `console` 가입 뷰 → `foundation.create_advertiser` + `billing.grant_signup`(한 트랜잭션) | 지급 50,000(설정) |
| `GET /slots` | `masters.list_slots` | 현재 정책 포함(`SlotView.policy`) |
| `GET /wallet`, `/wallet/ledger` | `billing.get_wallet`, `list_ledger(before, limit)` | 계약의 `balance·spent_today·budget_day·resets_at`와 같은 값. 커서는 불투명 값 |
| 캠페인 `GET·POST`, `GET·PATCH /{id}` | `list_campaigns`·`create_campaign`·`get_campaign`·`update_campaign` | PATCH 필드 `name·ends_at·daily_budget·status(ACTIVE↔PAUSED)`. 응답의 `today`(소진·남은 예산·리셋 시각)는 **콘솔이 `billing.spend_today`·`next_reset`으로 채운다**(Step 3) |
| `POST /campaigns/{id}/end` | `end_campaign` | 되돌릴 수 없음, `ended_from` 포함 |
| 재검토 요청 `GET·POST` | `list_review_requests`·`create_review_request` | 상태 `OPEN·RELEASED·REJECTED·CLOSED_ENDED` |
| 광고그룹 `GET·POST`, `GET·PATCH` | `list_ad_groups`·`create_ad_group`(`bid_amount` 선택)·`get_ad_group`·`update_ad_group` | `pricing_unit`을 보내면 항상 `unit_immutable`. 응답의 `effects`는 **콘솔이 `masters`+`engine.effect_of`로 채운다**(Step 3) |
| 입찰 `GET`, `POST`(`expected_version`, 첫 입찰은 `null`) | `list_bids`·`add_bid` | `bid-preview`와 `effects`도 같은 방식으로 콘솔이 구성(적용 금액 계산은 `engine` 한 곳) |
| 소재 `GET·POST`(업로드), `GET·PATCH`, `PUT .../image` | `list_creatives`·`create_creative`·`get_creative`·`update_creative`·`replace_creative_image` | 업로드 검증 실패는 `assets.ImageRejected`(`reason`)로 전달, HTTP 변환(`invalid_image`)은 콘솔 몫 |
| 관리자 기능(중단·해제·반려·정책·조정) | `suspend_campaign`·`release_campaign`·`reject_review_request`, `masters.*`, `billing.adjust` | C6에는 없음(Django admin, 설계 §3) |
| `/reports/daily`, `/alerts` | **서비스 [구현 2-10 `records.api.daily_report`]**, 콘솔 JSON·`/alerts`는 Step 3 | 이벤트·반응 처리(Step 2) 이후. `alerts`는 현재 상태에서 계산하는 읽기 전용이라 Step 3 |
| 오류 코드 | `stale_version`·`unit_mismatch`·`unit_immutable`·`suspended`·`not_suspended`·`review_pending`·`ended`·`limit_exceeded` 모두 같은 `code` 값의 예외 | `invalid_transition`은 계약에 없는 내부 방어용(409 `conflict` 계열)이라 계약에 추가할지 Step 3에서 정함 |

## 6.9 Step 1 이후 남은 것

- **쿼터 기본값**(캠페인 20·광고그룹 100·소재 100·이미지 100MB)은 제안값이다. 설계 §7-5가 열려 있으므로 시연 규모에 맞게 조정해도 된다(설정값).
- **주기 작업 실행 방식**(`end_expired_campaigns` 등, 설계 §7-9): 1-2에서는 함수와 관리 명령까지 만든다.
- **관리자의 정지 소재 미리보기**: 중단된 캠페인 이미지는 C3 URL에서 404가 되므로, 관리자 모니터링 화면(Step 3-1)은 별도의 관리자 전용 경로가 필요하다. 이번 단계 범위가 아니며 3-1에서 정한다.

---

# 7. Step 2: Serving API (개요, 2-1 완료)

| 단계 | 핵심 | 완료 증거(요지) |
|---|---|---|
| 2-1 | **계약 확정**: `contracts/serving.openapi.yaml`(초안 작성됨, 설계 §3). `openapi-spec-validator`로 파일 검증, **provider 계약 테스트 틀**(`PyYAML`+`jsonschema`로 실제 응답을 계약 스키마에 대조) | 검증기 통과, 매체 쪽 담당자와 공유(재시도·`reaction_id`·접수/처리 분리 약속 포함) |
| 2-2 | 매체 인증(공유 키 `X-Media-Key`, 해시 저장·상수시간 비교·교체), **매체(UUID)별·경로군별 토큰 버킷** 요청 제한(결정 150/초·버스트 300, 반응 450/초·버스트 600, 조회 150/초·버스트 300. 키 교체 후에도 같은 버킷). 인증은 입력 검증보다 먼저. **키 없음·무효는 401(`WWW-Authenticate: MediaKey realm="ads-media-api"` 필수 — 공통 오류 변환 `problem_response`가 401에 이 헤더를 붙이도록 연결), 유효한 키지만 매체 비활성은 403, 제한 초과는 429 + `Retry-After`**. 인증이 필요한 모든 엔드포인트(결정·반응의 생성·조회)가 401·403·429·503을 같은 방식으로 낸다 | 인증 실패·제한·키 교체 테스트, 계약 테스트(401의 challenge 헤더 포함) |
| 2-3 | `POST /decisions`(**201 + `Location`**, 광고 없음도 201), `GET /decisions/{id}`(**본인 매체만, 아니면 404**), `GET /health`. **저장 뒤에만 `decision_id` 응답**. **DRD §10 D-1~D-3 반영**: ① **활성 매체가 소유한 비활성 슬롯**은 201 + `ad: null`로 결정을 기록하고, **없는 슬롯·다른 매체의 슬롯은 404**, 매체 자체가 비활성이면 2-2의 403(`records.decide`의 현재 비활성 슬롯 `NotFound` 동작과 그 테스트를 바꾼다) ② 매체 `context`를 결정에 JSON 열로 저장(크기 제한은 계약 그대로) ③ 응답의 `slot_name`은 serving 계층이 `masters`에서 붙인다(결정에 저장하지 않음) | 계약 테스트(C1의 상태 코드 표 전부: 401·403·201 비활성 슬롯·404·정상·광고 없음), 저장 실패 시 `decision_id`가 나가지 않음, 다른 매체의 결정은 404, **D-1~D-3 각각의 계약 테스트** |
| 2-4 | `PUT /decisions/{id}/reactions/{reaction_id}`(inbox): 원문 보존 + **(매체, `reaction_id`) 유니크** + `RECEIVED`를 한 트랜잭션에, **저장 뒤 2xx**(**201 처음 / 200 같은 내용 재전송 / 409 같은 ID 다른 내용**), 잠금·장애 시 503 + `Retry-After` | 중복·충돌(409)·저장 실패 테스트, 원문 보존, 다른 매체가 같은 `reaction_id`를 써도 충돌 없음 | **접수 2xx의 의미는 "inbox 저장 완료"로 고정**: 뒤의 처리 실패가 접수 성공을 뒤집지 않는다
| 2-5 | 반응 처리(+ `GET .../reactions/{reaction_id}`로 결과 조회, 본인 매체만): 별도 트랜잭션, 규칙 체인(`known-decision`·`same-media`·`once-per-type`), `ChargePolicy` 과금, `ACCEPTED`/`REJECTED`, **`process_reactions` 재처리 명령** | 타 매체 거부, 유형별 1회, 거부 반응 보존, 처리 중 실패 후 재처리해도 이중 과금 없음 | **재시작·중복 처리·자정 이후 재처리에서도 원래 `received_at`과 과금 멱등 키(`reaction_ref`)를 유지**한다(예산 일은 처리 시각이 아니라 반응의 시각 기준으로 일관되게). `process_reactions`는 **단일 관리 프로세스가 1초 주기·배치 100**으로 남은 `RECEIVED`를 재처리한다
| 2-6 | **동시성 검증**: 150개 동시 결정·150개 동시 반응 | 수신 확인한 건 전부 저장, 유실 0, 이중 과금 0, 잔액=원장 합계 |

**Step 2의 확정값(2026-10-07, 설계 §10)**: 요청 제한 수치는 위 2-2(**150명 가정의 개발용 초기값**이며 처리량 측정 결과가 아니다. 2-6에서 조정), `title`은 1~200자(구현·C1·C6가 이미 일치), `CONVERSION`은 매체가 사전에 정의한 목표 완료를 보고(광고 서버는 결정 존재·매체 일치·유형별 1회·결정의 과금 단위로만 판정, 연동 전에는 시연용 매체 사건으로 검증), `process_reactions`는 inbox 커밋 뒤 별도 트랜잭션으로 한 번 시도하고 남은 것은 관리 프로세스가 재처리. 매체 쪽 재시도 구현 여부는 [contracts/README.md](contracts/README.md)를 전달해 확인(사람의 일).

## 7.1 Step 2 종료 점검표

- [x] 2-1~2-6 구현, `scripts/check.sh` 통과(`check --deploy` 경고 0, 마이그레이션 최신, 테스트 565개, 소규모 부하 시험 20 동시, `pip-audit` 0, `bandit` 0)
- [x] **계약 ↔ 구현**: C1의 모든 operation(`health`, `POST·GET /decisions`, `PUT·GET .../reactions/{reaction_id}`)과 C3(`/assets`)을 실제 URL로 요청해 응답의 상태 코드·헤더·미디어 타입·본문을 계약 스키마에 대조(provider 계약 테스트). 계약이 선언한 응답 규칙표(401·403·201·404), 필수 헤더(`Location`·`Retry-After`·`WWW-Authenticate`·`X-Request-ID`), 입력 문법(`Uuid`·`DateTimeUtc`·`Context`)은 구현과 계약이 **같은 입력을 받는지** 대조하는 테스트로 고정
- [x] **인증·요청 제한(2-2)**: 인증 → 요청 제한 → 본문 순서, 401·403·429·503이 모든 operation에서 같은 모양. 저장소 장애는 503 + `Retry-After`
- [x] **수신의 의미(2-3·2-4)**: 결정·반응의 2xx는 **커밋 뒤에만** 나가고, 저장·조회·커밋 실패는 503이며 행이 없다(실제 커밋 실패 테스트). 같은 `reaction_id`는 201 → 200, 다른 내용은 409, 매체 범위 유일
- [x] **처리의 정합성(2-5)**: 반응 하나 = 트랜잭션 하나, 과금은 결정의 스냅샷(금액·광고주·캠페인)과 접수 시각 기준, 멱등 키 고정, 필수 권한 조건(결정 존재·매체 소유·광고 있음)은 규칙 설정과 무관하게 강제, 과금 호출·상태 변경은 `records/processing.py` 한 곳(소스 검사)
- [x] **동시성(2-6)**: 150 동시 결정·반응·같은 결정/유형 중복·같은 `reaction_id` 재전송·지속 유입 중 SIGTERM·재기동에서 유실 0·이중 과금 0·잔액=원장·소진액=원장·`RECEIVED` 잔류 0. 검사기는 결정의 **과금 근거(금액+부족분·광고주·캠페인·접수 시각·정책)와 수신 확인한 (매체, 반응, 결정, 유형) 연결**까지 대조하고, 변조 사례로 검사기 자체를 시험. 결과·한계: [load-test.md](load-test.md)
- [x] `threat-model.md` 갱신: T33(계약), T34(인증·요청 제한), T35(결정 입력·열람), T36(반응 수신), T37(반응 처리), SQLite 단일 노드 행(2-6 측정)
- [x] 설계 §10에 Step 2 결정 반영(결정 API·반응 수신·반응 처리 세부, 동시성 검증 결과, 요청 제한 유지), DRD 갱신(D-1~D-3·D-8 해결, 0.8), 진행 상태 표(§10) 갱신
- [ ] **사람의 일 — 매체 쪽 담당자와 계약 공유·확인**: [contracts/README.md](contracts/README.md)를 건네 재시도 구현(같은 `reaction_id` 재전송·`Retry-After` 존중)·접수/처리 분리 약속을 확인한다. 확인 전에는 "유실 0"이 **수신 이후 구간**에 한정된다
- [ ] **알려진 한계(후속 단계)**: 동시성 증거는 SQLite 결과이며 MySQL 재검증은 Step DB의 DB-1d · 요청 제한 버킷이 프로세스 메모리라 다중 워커에서 한도가 최대 N배로 느슨해짐 · 동시성은 SQLite 결과이며 조건부 유일 제약 3곳(`billing_charge_once_per_reaction`·`billing_one_signup_grant_per_wallet`·`campaigns_one_open_review_per_campaign`)은 MySQL·MariaDB에서 쓸 수 없음(반응 인정 1건은 2-9 보완에서 `accepted_key`로 바꿈, 나머지는 전환 시 같은 방식으로 재설계·재검증) · 보류된 반응은 처리 프로세스가 떠 있어야 풀림(운영 전제) · 이벤트 outbox(C2)는 Step 4 · C6의 `/reports/daily`·`/alerts`는 Step 3 · 부하는 단일 프로세스 `wsgiref` 서버 기준(운영 서버·프록시·장시간 미측정)

## 7.2 C1 v1.1: 퍼널 규칙·일괄 슬롯·클릭 관측 [계획, 결정 확정 2026-10-08]

결정은 설계 §10 "반응 퍼널 규칙"·"일괄 슬롯"·"클릭 출처"·"퍼널 집계"·"계약 v1.1"에, 계약은 [contracts/serving.openapi.yaml](contracts/serving.openapi.yaml) `1.1.0`에 있다(구현 중에는 `[v1.1]` 필드를 해당 단계가 끝날 때 `required`로 올렸다. 2-11에서 확정). **Step 3보다 먼저** 한다: 3-1a(슬롯 등록 화면)가 `audience`를, 3-2a(대시보드)가 퍼널 집계를 쓴다.

| 단계 | 핵심 | 완료 증거(요지) |
|---|---|---|
| 2-7 **[완료 2026-10-08]** | **슬롯 성격**(`masters`): 슬롯에 `audience`(`individual`·`shared`, **생성 뒤 변경 불가**)와 ~~`max_viewers`(`shared`일 때 필수, 양의 정수)~~ **(2-7 보완에서 제거)** 추가, 기존 슬롯은 `individual`. 결정 API: 응답에 `audience`(계약 `required`로), 결정 요청의 `subject_id`는 `individual` 필수·`shared` 금지(어기면 400), 결정 스냅샷에 `audience` 기록(이벤트·집계용) | 슬롯 생성·변경 불가 테스트, 결정 요청 400 두 경우, 계약 대조(`audience` 필수), 기존 결정 응답 회귀 없음 |
| 2-7 보완 | **`max_viewers` 제거**(설계 §10 "일괄 슬롯 노출 방어"): `Slot.max_viewers`·DB 제약·`MAX_VIEWERS`·서비스 검증·감사 상세·관리자 목록·`SlotView` 필드·C6 `Slot.max_viewers`·DRD 열·관련 시험을 지운다. 마이그레이션은 필드·제약 제거 하나(운영 데이터 없음) | 전체 시험 통과, `max_viewers`가 코드·계약·DRD에 남지 않음(`git grep`), `audience` 동작(변경 불가·`subject_id` 규칙) 회귀 없음 |
| 2-8 **[완료 2026-10-08]** | **클릭 관측** `GET /c/{token}`(`serving_api`, 루트 경로): Django `signing`(전용 salt) 토큰 = 서명된 `decision_id`뿐(`subject_id`는 싣지 않는다: 개인 슬롯의 사람은 결정에서 정해지고, `signing`은 암호화가 아니라 URL에 드러난다), 결정 응답 `ad.click_url`(계약 `required`로, `shared`는 `?s={subject_id}` 템플릿). 유효한 토큰은 **항상 302** → 결정에 저장된 `redirect_url`, 무효·없는 결정·광고 없는 결정은 404. 클릭을 수신함에 `CLICK`으로 기록: 매체 = 결정의 매체, `reaction_id` = (결정, 사람)에서 **서버 비밀(HMAC)로** 결정적으로 만든 UUID(중복 클릭 1건, 매체가 미리 계산해 선점할 수 없다), 시각 = 서버 수신, **출처 열 `source`(`media`·`server`)** 추가. `shared`에서 `s`가 없거나 틀리면 이동만. 헤더 `Cache-Control: no-store`·`Referrer-Policy: no-referrer`, 쿠키 없음, 인증 없음(URL 전수 점검 목록에 공개 뷰로 등록) | 302 대상이 요청 값과 무관함(열린 리다이렉트 없음), 위조·변조 토큰 404, 같은 사람 중복 클릭 1행·서로 다른 사람은 각각, `s` 누락 시 이동만, 쿠키·헤더 계약 대조, 기록 실패해도 이동은 되는지(사용자 경험)와 그 경우 로그 |
| 2-9 **[완료 2026-10-08]** | **반응 판정 확장**(`records`): ① 반응 요청 `subject_id`(선택, 저장, 재전송 비교 대상에 포함) ② 규칙 파일 추가: `click-source`(매체가 보고한 `CLICK` → `click_not_reported`, 유형별 1회 자리를 차지하지 않음), `subject`(`subject_required`·`subject_mismatch`), `campaign-open`(`campaign_ended`: 판정 시점의 캠페인 종료 시각 이후 수신), `occurred-at`(`invalid_occurred_at`), `funnel-order`(`missing_prerequisite`), `funnel-window`(`window_expired`·`display_ended`: "같은 표시 단위의 다음 결정 시각"을 처리 단계가 조회해 사실로 넘김 — 2-12에서 "이후 결정 중 처음으로 노출이 도착한 시각"으로 바뀜) ③ **보류**: 규칙이 "아직 판단 불가"를 돌려주면 `RECEIVED`로 두고 `attempts`를 올리지 않음, 보류 기한(300초)이 지나면 `missing_prerequisite`. `process_reactions`가 보류분을 다시 집음 ④ 판정 단위: `individual` = 결정, `shared` = (결정, 사람). 같은 결정·유형의 `ACCEPTED` 부분 유일 제약을 (결정, 사람, 유형)으로 확장 ⑤ 수치(300초·5초·30일·허용 오차 60초·보류 기한)는 설정값 ⑥ 응답 `subject_id`(계약 `required`로) | 규칙별 인정·거부 테스트(새 사유 8개), 보류 → 늦게 온 노출로 인정 / 기한 초과 거부, 매체 `CLICK`이 과금·전환 전제에 쓰이지 않음, 일괄 슬롯에서 A의 노출로 B의 클릭이 인정되지 않음(**`?s=`는 최종 사용자가 마음대로 바꿀 수 있으므로, 노출이 없는 사람의 임의 `s` 클릭이 거부되는 시험을 반드시 포함** — 이때 막는 장치는 `funnel-order` 하나다), 캠페인 종료 뒤 수신은 과금 없음(기존 빈틈 회귀 테스트), 규칙을 설정에서 빼도 필수 조건(`guard`)은 유지 |
| 2-10 **[완료 2026-10-08]** | **퍼널 집계** = Step 3의 S1을 앞당김: `records.api.daily_report`(노출·클릭·전환 수, CTR = 클릭/노출, 전환율 = 전환/클릭, 소진 포인트, 앞 구간 비교). 조회 시점 집계(별도 테이블 없음), `ACCEPTED`만 센다. 반응이 많아지면 함수 안쪽만 카운터·파이프라인 결과(C4)로 바꾼다(설계 §10 "퍼널 집계") | 개인·일괄 슬롯 섞인 데이터로 수치 대조, 다른 광고주 범위 차단, 질의 수 고정(N+1 없음) |
| 2-11 **[완료 2026-10-08]** | **마무리**: 계약 `info.version` `1.1.0`(draft 해제), `[v1.1]` 표시 정리, 부하 시험에 클릭 경유·보류(**보류 해소 지연** — 처리 프로세스가 돌아야 풀리는 운영 전제의 검증)·일괄 슬롯 **단계 추가**(소규모 20 동시, 유실 0·이중 과금 0 유지). **150 동시 재측정은 하지 않는다**: 곧바로 SQLite를 MySQL로 바꾸므로(Step DB) DB-1d에서 MySQL로 잰다 [합의 2026-10-08]. 변형 검사, 위협 모델 새 행(클릭 경유 공개 GET·토큰 위조·링크 미리보기·일괄 슬롯 노출 부풀리기(이상치 감지 전까지 알려진 한계)·보류 악용), DRD C1 절·[contracts/README.md](contracts/README.md)(매체 안내) v1.1로 갱신 | `scripts/check.sh` 통과, 계약 ↔ 구현 대조에 `/c/{token}` 포함, 매체 안내에 "광고를 바꿀 때마다 새 결정"·"이동은 `click_url`로"·"일괄 슬롯은 사람별 보고" 명시 |
| 2-12 **[완료 2026-10-09]** | **외부 검토 후속(정의 변경 2건)**: ① 표시 종료 기준을 "같은 표시 단위의 이후 결정 중 처음으로 **노출이 도착한** 시각 + 5초"로(`records/facts.py`의 다음 결정 조회. 판정과 무관하게 접수된 노출의 `received_at`) — 응답을 받지 못해 화면에 적용하지 못한 결정이 기존 광고의 클릭을 끊지 않게 ② 전환율을 **클릭 코호트 기준**으로(`daily_report`, `records/types.py`의 "1을 넘지 않는다" 주석과 계산을 일치) | 반례 시험: 다음 결정만 있고 노출이 없으면 기존 광고 클릭 인정, 다음 결정의 노출 도착 + 5초 뒤 클릭은 `display_ended`, 일괄 슬롯은 누구의 노출이든 교체 신호. 이전 기간 클릭의 전환이 있어도 전환율 ≤ 1, 변형 검사 |
| 2-13 **[완료 2026-10-09]** | **판정 사실의 매체 격리와 판정 근거 기록**(외부 검토 `65331e8`, 설계 §10 "판정 설계 기준"·"판정 사실의 범위"·"판정 근거 기록"): ① `records/facts.py`의 판정 사실 조회를 **결정 소유 매체의 반응**(개인 슬롯은 + 보고된 사람이 없거나 결정의 사람)으로 묶는 범위 함수 하나를 만들고 표시 교체 신호(`next_display_at`)·클릭의 앞 단계 노출·인정된 유형 조회를 모두 그것으로 바꾼다. 판정 상태가 아니라 접수 때 정해지는 값으로 거른다 ② **구조 검사**: 판정 사실 조회가 범위 함수를 거치지 않으면 실패(기존 "과금은 `processing.py`에서만" 소스 검사와 같은 방식) ③ `records_reaction.basis`(JSON) 추가: 판정(`ACCEPTED`/`REJECTED`)과 같은 트랜잭션에서 판정에 쓴 사실을 한 번 쓰고 바꾸지 않음, 보류에는 쓰지 않음. 마이그레이션은 MySQL·SQLite 둘 다에서 | 회귀 시험: 다른 매체의 노출은 표시 교체 신호가 되지 않음 · 다른 매체의 처리 전 노출이 클릭을 보류시키지 않음 · 개인 슬롯에서 다른 사람을 보고한 노출은 신호가 되지 않음 · 노출 없는 새 결정은 기존 표시 유지 · 정상 일괄 슬롯의 새 노출(같은 매체의 누구 것이든)은 교체 신호 · 인정·거부 모두 `basis`가 저장되고 판정 뒤 바뀌지 않음. 각 규칙을 끄면 실패하는 변형 검사 |
| 2-13 보완 **[완료 2026-10-09]** | **판정 근거의 두 결함**(외부 검토 `4f00598`, 설계 §10 "판정 근거 기록" ⓐ·ⓑ): ① `records/processing.py`: 결정이 없을 때 `basis.person`에 보고된 사람을 넣던 것을 `None`으로 — 판정 사람은 `person_of`(결정이 있을 때)만, 보고된 값은 `basis.reaction.reported_subject_id`에만 ② `records/facts.py`: 앞 단계를 **인정 근거**(`prerequisite_accepted`, `ACCEPTED`, 유일 제약으로 최대 1개, 상한 없음)와 **처리 전 후보**(`prerequisites_waiting`, `RECEIVED`, 상한 + 총 개수)로 나눠 `basis`에 남김. `basis` 스키마 버전 `v` 올림 | 시험: 없는 결정에 `subject_id`를 실은 보고 → `REJECTED/unknown_decision`, `basis.person`·`basis.audience` 모두 `null`, 보고된 값은 `basis.reaction.reported_subject_id`에만 · 처리 전 노출 21개 + 제때 도착해 인정된 노출 1개 → 클릭 `ACCEPTED`, `basis.prerequisite_accepted`가 그 노출의 `inbox_id`, 후보 목록은 상한·총 개수 · 일괄 슬롯 `subject_required`는 `person`만 `null`. 각 수정을 되돌리면 실패하는 변형 검사 |

**알려진 한계(설계 §10 "계약 v1.1")**: 클릭 주소는 공개 GET이라 링크 미리보기·프리페치가 클릭으로 기록될 수 있다(중복 1건·표시 중 5초 창으로 폭 제한, IP 단위 제한은 필요해지면). 일괄 슬롯의 "누가"와 노출·전환은 여전히 매체 보고이고, 일괄 슬롯의 사람별 노출 부풀리기는 이후 **이상치 감지**로 막는다(인원 상한은 두지 않음, 설계 §10 "일괄 슬롯 노출 방어").

## 7.3 Step DB 상세 계획 [초안 2026-10-08, 인프라 확인 반영]

### 7.3.1 인프라에서 확인한 사실 (`platform/`, [docs/platform/infra-automation-design.md](../platform/infra-automation-design.md))

| 항목 | 확인한 내용 | 이 단계에 미치는 영향 |
|---|---|---|
| MySQL | **8.4 LTS**(Server·Shell·Router). 1대 Standalone 또는 2대 **InnoDB ReplicaSet**(비동기 복제, **수동 failover**). GTID 켜짐. 문자셋·격리 수준·`sql_mode`는 서버 기본값(utf8mb4, `REPEATABLE READ`, strict) | 개발·시험도 **8.4**로 맞춘다. failover 중에는 연결이 끊기므로 앱이 503 + 재시도로 견뎌야 한다(지금 구조가 이미 그렇다) |
| 접속 경로 | 앱은 **Backend 서버**에서 접속한다. ReplicaSet이면 **MySQL Router**(설치까지만 됨, **설정(bootstrap)은 서비스 영역 = 우리 몫**)의 읽기·쓰기 포트로, Standalone이면 직접. 방화벽은 Backend·Spark·Bastion의 IP만 연다 | 개발자 PC는 **Bastion SSH 터널**로만 닿는다. 공유 서버라 테스트를 거기서 돌리지 않는다 |
| `dev` 계정 | 업무 DB 전역 `SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/INDEX/REFERENCES/TRIGGER/LOCK TABLES…`(`mysql`·`sys` 제외), 출처는 Backend·Spark·Bastion IP | 마이그레이션·`CREATE DATABASE`는 된다. 팀원이 같은 서버에 테스트 DB를 만들면 이름이 겹치므로 사람·환경별 이름을 쓴다 |
| MongoDB | **8.0**. 1대 Standalone 또는 3대 Replica Set(keyfile 인증). `dev` = `readWriteAnyDatabase`(컬렉션·색인 생성 가능). TLS 없음, 같은 방화벽 규칙 | DB-2 연결에 쓴다. 로컬 개발·시험용 mongod는 **단일 노드 Replica Set** 모드로 띄워야 같은 기능(트랜잭션·재시도 쓰기)을 쓴다 |
| 시간·통신 | 서버 시간은 UTC, 내부 통신은 **평문**(TLS 없음, 방화벽·Bastion으로만 보호) | Django `TIME_ZONE=UTC`와 맞는다. DB 비밀번호는 환경변수로 받고 코드·로그에 남기지 않는다 |
| 이 PC | Docker·Homebrew MySQL(**26.7**, 혁신 릴리스)·mongod 8.0이 설치돼 있다 | **MySQL이 운영(8.4)과 다르다.** 시험은 8.4 컨테이너(또는 `mysql@8.4`)로 한다 |

### 7.3.2 결정 (인프라에서 정해지는 것은 그대로 받았다. 아래는 근거와 함께 제안이며 이견이 없으면 이 값으로 간다)

| # | 결정 | 이유 |
|---|---|---|
| S1 | **MySQL 8.4 LTS**(MariaDB 아님) | 인프라와 같은 버전·같은 동작(조건부 제약·JSON·CHECK) |
| S2 | 드라이버 **`mysqlclient`**(MongoDB는 `pymongo`) | Django가 권장하는 드라이버. 빌드에 MySQL 클라이언트 개발 패키지가 필요: macOS `brew install mysql-client pkg-config`, Backend(AL2023)는 `mysql-community-devel` — **인프라 쪽 요청**(7.3.4). `PyMySQL`은 Django 공식 지원 밖이라 쓰지 않는다 |
| S3 | **시험·`check.sh`는 개발 PC의 8.4 컨테이너**(Docker `mysql:8.4`)에서. 공유 인프라 서버에서는 돌리지 않는다. 인프라 서버는 **통합 확인**(마이그레이션·`dev` 권한·Router·failover)에만 쓴다 | 공유·Bastion 터널·이름 충돌, 시험이 느려지고 남의 작업을 건드릴 위험 |
| S4 | **SQLite는 DB-1 끝에 제거**한다(두 DB를 함께 지원하지 않는다) — **[완료 DB-1e `f2e930b`]** | 설계가 "전환 뒤 운영·시험·테스트 모두 MySQL"로 정했고, 두 DB를 유지하면 분기 비용만 는다 |
| S5 | 격리 수준 **`READ COMMITTED`**(연결 초기화 명령) 시도, 부하 시험으로 확인하고 `REPEATABLE READ`(기본)와 비교해 확정 — **[확정 DB-1c: `READ COMMITTED` 유지, 측정은 §7.3.4b]** | `REPEATABLE READ`의 간격 잠금은 같은 유일 키를 노리는 동시 쓰기에서 교착을 늘린다. 판정은 유일 제약과 행 잠금에 기대므로 `READ COMMITTED`로도 의미가 같다 — 근거는 측정 |
| S6 | **교착(1213)·잠금 대기 초과(1205)는 일시 오류**로 다룬다: 반응 처리는 `attempts`를 올리지 않고 다음 주기에 다시 하며, API는 지금처럼 503 + `Retry-After` — **[구현 DB-1c `7aac929`]** | 지금은 모든 처리 예외가 실패 횟수를 올려 5번이면 자동 재처리에서 빠진다. MySQL에서는 교착이 정상 동작의 일부다 |
| S7 | 접속 설정은 환경변수(`DB_HOST`·`DB_PORT`·`DB_NAME`·`DB_USER`·`DB_PASSWORD`)로 받는다. 연결에 `SET SESSION sql_mode=STRICT_ALL_TABLES`·`init_command`로 격리 수준을 지정한다 | 비밀번호는 코드·로그에 없다(인프라의 Vault는 서버 구축용이고, 앱의 비밀번호는 앱이 받는다) |
| S8 | 조건부 유일 제약 3곳은 **조건 없는 유일 제약 + NULL 키**로 바꾼다(설계 §10 "MySQL 전환 점검"): 과금 멱등 키는 `reaction_ref` 자체가 NULL 허용이라 조건만 제거, 나머지 둘은 **DB가 계산하는 열(`GeneratedField`, STORED)** 을 키로 쓴다 [DB-1b 구현 2026-10-09] | MySQL은 조건부 유일 제약을 만들지 않는다(Django 경고 `W036`). 계산 열은 상태를 바꾸는 코드가 키를 신경 쓰지 않아도 되고(닫기·일괄 종료·`update()` 모두), 기존 행을 채우는 이전이 필요 없다 |

### 7.3.3 단계

| 단계 | 내용 | 완료 증거 |
|---|---|---|
| **DB-1a 준비 [완료 2026-10-08]** | `mysqlclient` 추가, `DATABASES`를 환경변수 기반으로, 8.4 시험용 컨테이너 정의와 사용법(README), 개발·시험 설정, `check.sh`의 시험·부하 단계가 MySQL을 쓰도록(없으면 **명확히 실패**, 건너뛰지 않는다), 전체 시험을 MySQL에서 한 번 돌려 **실패 목록**을 만든다 | 컨테이너 한 줄로 시험 환경이 뜬다. 실패 목록이 문서에 있다 |
| **DB-1b 제약·SQL 재설계 [완료 2026-10-09]** | 조건부 유일 제약 3곳 교체(데이터 이전 포함), SQLite 문법의 시험(원시 SQL `DROP INDEX` 등) 재작성, `W036` 경고 0. **기존 데이터 사전 검사**(보완 `0b23b86`): 새 유일 제약을 어기는 기존 데이터(같은 반응 키의 중복 과금, 한 지갑의 가입 지급 중복, 캠페인당 열린 재검토 요청 중복)를 **모든 DDL보다 먼저** 검사해 알리고 멈춘다 — 자동 삭제 없음 | `makemigrations --check`·`check --deploy` 경고 0, 제약을 빼면 실패하는 시험(MySQL에서), 위반 데이터가 있으면 스키마를 바꾸기 전에 멈추고 정리 뒤 같은 DB에서 재실행되는 시험 |
| **DB-1c 동시성 [완료 2026-10-09 `7aac929`]** | S5·S6: 격리 수준 결정, 교착·잠금 초과를 일시 오류로, 스레드 동시성 시험(과금·입찰·정책·반응 처리)을 MySQL에서 반복 실행, 원장 `seq`·지갑 잠금(`SELECT … FOR UPDATE`) 검증. **[필수, 검토 DB-1a P2] `recompute_spend`와 과금의 경쟁**: MySQL의 `atomic()`은 다른 연결의 과금을 막지 않아, 재계산이 원장 10을 읽은 뒤 다른 연결이 20을 과금·커밋하면 소진액이 10으로 교체된다(원장 30, `CampaignSpend` 10 — `check_ledger()`는 잡지 못한다). 과금과 재계산이 **공유하는 잠금 또는 배타 실행 규약**을 정하고(예: 재계산이 모든 지갑 행을 `FOR UPDATE` 순서대로 잠그거나, 소진액 갱신 자체를 원장 증가분 적용으로 바꿔 재계산을 점검 도구로 한정), **실제 두 연결의 순서를 제어하는 회귀 시험**(첫 과금 10 커밋 → 재계산이 읽은 직후 멈춤 → 다른 연결이 새 반응 키로 20 과금·커밋 → 재개 → 소진액 = 원장 합계)을 넣는다. **새 캠페인·새 날짜**의 소진액 행도 대상이다. 과금을 멈추고 재계산하는 운영으로 제한한다면 그 제약을 설계와 실행 절차에 명시한다 | 반복 실행(수십 회) 무실패, 교착 주입 시험(처리는 횟수 불변·재시도, API는 503). **접수·판정 경쟁**(설계 §10 "반응 판정 세부" ⑪): 같은 결정에 접수 여럿과 판정이 동시에 도는 시험을 MySQL에서 반복해, 진행 중인 이른 접수를 판정이 기다리고 인정 대표·클릭·전환·과금이 처리 순서와 무관한지 확인. **잠금 대기 초과 처리**: 접수의 결정 행 잠금이 대기 초과(1205)되면 503 + `Retry-After`이고 행이 남지 않으며 같은 ID 재시도가 처음 접수가 됨, 판정이 잠금 대기 초과·교착이면 `attempts`를 올리지 않고 다음 주기에 다시 판정함(`stuck`으로 빠지지 않음). **잠금의 소유 범위 [완료 2026-10-09 `a139e39`] (외부 검토 `974c28b`, 설계 §10 "반응 판정 세부" ⑪ (바))**: `records/ordering.py`의 접수 잠금은 보고 매체를 받아 잠그기 전 일반 조회로 소유를 확인하고 없는 결정·남의 결정은 잠금 없이 저장, 판정 앞 대기는 반응의 매체 = 결정 소유 매체일 때만. 실제 MySQL 두 연결 시험 3개: 다른 매체의 미커밋 보고가 소유 매체의 정상 접수를 막지 않음 · 소유 매체의 진행 중 접수가 남의 결정 보고의 판정을 기다리게 하지 않음 · 다른 매체의 진행 중 접수가 소유 매체 반응의 판정을 막지 않음(잠금 대기 초과·`attempts` 증가 없음). `FOR UPDATE`에 매체 조건만 붙인 변형은 첫 시험에서 실패해야 함 |
| **DB-1d 부하·장애 [로컬 완료 2026-10-09 `554391d`, 인프라 서버 항목 남음]** | 부하 시험(`scripts/load_test.py`)을 MySQL로, **150 동시 재측정**(2-11에서 넘어온 항목), 처리 프로세스 정지·재기동·보류 해소 지연, 인프라 서버(Backend)에서 통합 확인: 마이그레이션·Router 경유 접속·**계획된 전환 중 503과 복구**, **원본 노드 장애 모의 뒤 강제 failover에서 수신 확인한 ID의 생존 검사** | 유실 0·이중 과금 0·잔액=원장 불변식 통과(단일 노드·계획된 전환 기준), `load-test.md` 갱신(MySQL 수치와 한계), 강제 failover 때 유실될 수 있는 범위와 복구 절차의 기록. **결과(2026-10-09)**: 로컬(개발 PC 단일 노드) — 150 동시 재측정 불변식 통과·보류 해소 1.1초·재기동 처리 수 초~십수 초, 장애 시험 `scripts/failure_test.py`(재시작·강제 종료·처리 프로세스 강제 종료) 통과, `load-test.md` §2·§7 갱신. **로컬 클러스터 확인(2026-10-10, §7.3.4c)**: Router 경유 접속, 계획된 전환·primary 강제 종료 뒤 자동 failover에서 503과 복구, 확인한 쓰기의 생존을 InnoDB Cluster 3노드에서 확인했다. **남은 항목(인프라 서버)**: Router 경유 접속·마이그레이션 통합 확인, 계획된 전환 중 503과 복구, 원본 노드 장애 모의 뒤 강제 failover에서 수신 확인한 ID의 생존 검사와 유실 범위·복구 절차 기록(허용 유실 범위는 7.3.4-6, 사람이 정함) |
| **DB-1e 정리 [완료 2026-10-09 `f2e930b`]** | SQLite 설정·`sqlite_config`·PRAGMA 시험·임시 파일 DB 코드 제거, 위협 모델의 "SQLite 단일 노드" 행과 `load-test.md`·README·설계의 SQLite 전제 문구 갱신, `.gitignore`의 `db.sqlite3` | `git grep -i sqlite`에 이력·결정 기록만 남음, `check.sh` 통과 |
| **DB-2 MongoDB 연결 [로컬 완료 2026-10-10 `b01b425`, 인프라 서버 확인 남음]** | `pymongo`, 연결 설정(환경변수, 인증, 레플리카셋 이름), 관리 명령으로 `ad_events` 컬렉션·색인(`_id = event_id`) 생성, 상태 확인(연결·쓰기 권한·색인). **이벤트는 아직 쓰지 않는다**(Step 4) | 로컬 단일 노드 Replica Set과 인프라 서버 양쪽에서 연결·색인 확인, 연결 실패 시 앱이 영향을 받지 않음(아직 쓰지 않으므로). **결과(2026-10-10)**: 로컬 — 공유 컨테이너(Standalone·인증)와 임시 단일 노드 레플리카셋(인증 켜짐, `scripts/mongo_temp_rs.py`) 양쪽에서 시험 16개 통과(변형 검사로 확인). `ensure_event_store`는 컬렉션(공통 봉투 검증)과 색인 (`event_name`, `produced_at`)·(`payload.decision_id`, `produced_at`)을 만든다. 여러 번 불러도 같고, 같은 이름에 다른 키의 색인이 있으면 지우지 않고 멈춘다. `check_event_store`는 연결·8.x·레플리카셋 이름·쓰기 권한(별도 확인용 컬렉션, 계약 컬렉션은 건드리지 않음)·컬렉션·색인을 보고 하나라도 실패하면 비정상 종료한다. 쓰기는 과반 확인(`w=majority`), `_id = event_id`(UUID 표준 표현), 비밀번호는 URI 밖. 연결은 처음 쓸 때 만들고 앱 기동·요청 경로는 연결하지 않으며(`test_the_app_does_not_connect_at_all`), prod는 `MONGO_HOSTS`가 없어도 기동한다(Step 4에서 필수로). `check.sh`가 맨 앞에서 MongoDB 접속을 점검한다(없으면 멈춤). **남은 항목(인프라 서버)**: 3대 Replica Set(keyfile 인증)에서 연결·색인·쓰기 권한 확인 |

### 7.3.4 인프라 쪽에 요청·확인할 것 (사람의 일)

1. **Backend 서버에 `mysqlclient` 빌드 의존성**(`mysql-community-devel`, 컴파일러·`pkg-config`) 또는 미리 만든 wheel — `roles/backend`는 지금 `mysql-router-community`만 설치한다.
2. **MySQL Router 설정**: 누가 어떤 값으로 bootstrap하는가(포트 6446/6447, `router` 계정). ReplicaSet이면 앱은 읽기·쓰기 포트로 접속한다.
3. **앱 전용 데이터베이스 이름과 생성 방식**(`dev` 계정이 `CREATE DATABASE`를 할 수 있다). 개발·스테이징 서버가 따로 있는지.
4. **`max_connections`·`innodb_lock_wait_timeout` 기본값** 확인(Django 연결 수 = 워커 수 × 스레드 수).
5. **MongoDB `ad_events`용 데이터베이스 이름**과 `dev` 계정의 쓰기 권한 범위 확인(`readWriteAnyDatabase`라 충분하지만 이름을 정한다).
6. **강제 failover의 허용 유실 범위 결정**: 비동기 ReplicaSet은 원본 노드 장애 뒤 강제 승격에서 복제 지연분(수신 확인한 반응·결정 포함)을 잃을 수 있다. 허용할지, 매체가 2xx 뒤에도 `GET`으로 생존을 확인하는 절차를 둘지, 무손실 복제 구조(반동기·그룹 복제 — 서버 3대 이상이라 인프라 구성 변경)를 요청할지 정한다. 정하기 전에는 "유실 0"을 단일 노드 기준으로만 쓴다. — **(2026-10-10)** 8번(InnoDB Cluster)으로 바꾸면 자동 failover와 그룹 과반 인증으로 이 문제를 줄인다. 로컬 클러스터 시험에서는 primary 강제 종료에도 확인한 쓰기 유실 0이었다(§7.3.4c). 허용 범위의 결정 자체는 여전히 사용자 몫이다.
7. 앱 배포 방식(프로세스 관리자·`process_reactions`·`relay_events` 상시 실행, `purge_sent_events`·`export_hop_manifests` 주기 실행, 로그 위치)은 인프라가 "서비스 영역"으로 남겨 둔 부분이라 별도로 정해야 한다.
8. **[요청 후보 2026-10-10] 운영 MySQL을 InnoDB ReplicaSet에서 InnoDB Cluster로**: 서버 3대(그룹 복제, 단일 primary, **자동 failover**) + MySQL Router. 6번의 강제 failover 유실 문제를 구조로 줄이는 안이고, 로컬 3노드 클러스터에서 앱 코드 변경 없이 점검·부하·장애 시험이 모두 통과했다(§7.3.4c). 요청에 담을 것:
   - 노드 3대(과반 유지를 위해 홀수), 같은 8.4 LTS(Server·Shell·Router). 설정: GTID·ROW 바이너리 로그·`binlog_checksum=NONE`, InnoDB 외 엔진 비활성, `innodb_flush_log_at_trx_commit=1`·`sync_binlog=1`
   - 클러스터 옵션: 일관성 `BEFORE_ON_PRIMARY_FAILOVER`(failover 직후에도 확인한 쓰기를 읽음), `expelTimeout`(로컬 5초 — failover 시간과 오탐의 균형), 자동 재합류
   - 계정 분리: 클러스터 관리(`failover`), Router 부트스트랩 계정, 앱 계정(`dev`, DML·DDL). 앱은 **Router 읽기·쓰기 포트로만** 접속
   - 운영 수치 확인: 실제 failover 시간(로컬 약 22~26초)과 계획된 전환 시간(로컬 부하 중 약 53초), 네트워크 분리 때의 동작, `max_connections`(4번)
   - 앱 쪽 전제: 모든 표에 기본 키(이미 충족), 일시 오류는 503 + 재시도(이미 충족). 설계 §10 "그룹 복제(InnoDB Cluster) 전제"

### 7.3.4a DB-1a 결과: MySQL 8.4에서의 시험 실패 목록 (2026-10-08) — 아래 표의 7개는 DB-1b(2026-10-09)에서 모두 해결, 전체 692개 통과

시험 환경: 인프라가 준 `intake/db-standalone/`(MySQL **8.4.11** 컨테이너, `root`), 설정은 `DB_*` 환경변수·`mysql_config`(`STRICT_ALL_TABLES`, `READ COMMITTED`, `utf8mb4`·`utf8mb4_0900_as_cs`). 전체 시험 688개 중 **통과 681, 실패 7개**(보고는 8건: 한 시험이 실행·정리에서 두 번 오류). 처음에는 686개 중 17건 보고였고, 그 가운데 9건은 시험 도구가 `DATABASE_PATH`·SQLite를 전제한 것이라 DB-1a에서 고쳤다(시험 2개 추가). 소규모 부하 시험(20 동시)은 **불변식 전부 통과**(조건부 유일 제약 없이도 — 코드 쪽 점검만으로). 전체 시험 약 27초, 부하 시험 약 28초.

DB-1a에서 이미 고친 것(T25가 인용하던 `test_sqlite_pragmas`는 `test_commit_is_durable_on_this_server`로 교체, 위협 모델 갱신): 설정 시험이 환경을 다시 만드는 곳(`tests/helpers.py`의 `DB_ENV`·`PROD_ENV`), SQLite PRAGMA 시험을 MySQL 세션 시험으로 교체(`MysqlSessionTests`: strict·격리 수준·문자셋·정렬·UTC·**커밋 내구성(T25)**), `check.sh`·`load_test.py`의 DB 준비(`scripts/mysql_admin.py`: 접속 점검, 실행마다 새 `ads_load_*` DB).

**남은 실패 7개 — DB-1b에서 고친다(원인별)**

| 원인 | 시험 | DB-1b 처리 |
|---|---|---|
| ① **조건부 유일 제약 3곳이 만들어지지 않음**(`W036` 경고 3개 — `billing_charge_once_per_reaction`, `billing_one_signup_grant_per_wallet`, `campaigns_one_open_review_per_campaign`) | `test_ledger_db_constraints`, `test_only_one_open_review_request_per_campaign`, `test_charge_concurrent_same_ref_once`(**같은 반응 키로 과금 2건**), `test_check_deploy_has_no_warnings`(경고) | S8: 조건 없는 유일 제약 + NULL 키로 교체(데이터 이전 포함). **이 세 시험이 실제로 실패했다는 것은 이 제약이 없으면 DB가 이중 과금을 막지 못한다는 증거** |
| ② **원시 SQL이 SQLite 문법** (`?` 자리표시자, `DROP INDEX name`은 MySQL에서 `ON 테이블` 필요) | `test_a_double_charge_is_found`(부하 검사기 시험) | 제약을 빼는 시험을 `ALTER TABLE … DROP INDEX/CONSTRAINT`로, 자리표시자는 `%s`로 |
| ③ **범위를 벗어난 값의 오류 종류**: `PositiveBigIntegerField`가 MySQL에서 `UNSIGNED`라 음수 잔액이 CHECK(`IntegrityError`) 전에 `DataError`(1264)로 거부된다 | `test_balance_never_below_zero` | 거부 자체는 같다. 시험이 두 오류를 모두 받아들이게 하되 **어느 쪽이든 행이 바뀌지 않음**을 확인 |
| ④ **MySQL DDL은 트랜잭션이 아니다** — 마이그레이션이 중간에 멈추면 이미 적용된 열(`accepted_key`)이 남아 다음 실행이 `Duplicate column`으로 깨진다. `records 0007`은 `AddField` 뒤에 사람을 알 수 없는 인정 행을 검사해 멈추므로 **운영에서도 같은 상태가 된다** | `test_an_accepted_reaction_whose_person_cannot_be_known_stops_the_migration_with_a_clear_message`(보고 2건: 실행·정리) | **검사(`RunPython`)를 스키마 변경보다 앞에 둔다**(멈춰도 DB가 그대로). 이 순서를 지키는 시험 추가. 다른 마이그레이션도 데이터 검사가 스키마 변경 뒤에 있는지 점검 |

**알게 된 것(설정 쪽)**
- `manage.py check`·`check --deploy`는 MySQL에서 **DB 연결이 필요하다**(모델 필드 검사가 서버 정보를 읽는다). 오프라인 점검이 아니므로 `check.sh`는 맨 앞에서 접속을 점검하고, 없으면 **건너뛰지 않고 실패**한다.
- 컨테이너는 인프라 서버와 다르다: **GTID 꺼짐**, 서버 기본 정렬이 `_ai_ci`(앱은 DB를 `_as_cs`로 만든다). 인프라 `infra.cnf` 핵심(GTID·문자셋)은 DB-1d의 인프라 서버 통합 확인에서 맞춘다.
- 기본 정렬 `_ai_ci`에서는 대소문자만 다른 값이 같은 값으로 취급되어 유일 제약·조회가 SQLite와 달라지므로 **DB 생성 시 정렬을 지정한다**(README). 인프라 서버의 DB 생성 방식은 7.3.4 #3과 함께 확인한다.
- 요청 제한 단계(F)는 MySQL에서도 통과하지만 429가 0건이다(수신이 느려지는 동안 토큰이 다시 찬다 — `load-test.md` §4와 같은 성질). 계약 위반이 아니다.

### 7.3.4b DB-1c 결과 (2026-10-09, 구현 `7aac929`)

**S5 격리 수준 측정** — 150 동시 부하(`scripts/load_test.py`, MySQL 8.4.11 단일 노드)를 격리 수준만 바꿔 실행

| 격리 수준 | 실행 | 교착(1213) | 잠금 대기 초과(1205) | 불변식 | 판정 |
|---|---|---|---|---|---|
| `READ COMMITTED` | 2회 | 0 (두 번 모두) | 0 (두 번 모두) | 전부 통과 | **채택** |
| `REPEATABLE READ`(MySQL 기본) | 비교 실행 | 8 | — | **2건 실패**: 같은 `reaction_id` 재전송 폭주에서 201이 하나가 아님, 퍼널이 인정되지 않은 결정이 있음 | 기각 |

간격 잠금이 같은 유일 키를 노리는 동시 INSERT를 교착으로 몰기 때문이다. 판정은 유일 제약과 행 잠금에 기대므로 `READ COMMITTED`로도 의미가 같다. 환경변수 `DB_ISOLATION_LEVEL`(dev·prod만, 시험 설정은 고정)로 다시 비교할 수 있다. 잠금 대기 초과 열의 `—`와 `REPEATABLE READ`의 실행 횟수는 구현 기록(커밋 메시지·설정 주석)에 없어 적지 않았다.

**S6 일시 오류** — 교착(1213)·잠금 대기 초과(1205)는 서버가 트랜잭션을 되돌린 것이라 반응 처리는 `attempts`를 올리지 않고 다음 주기에 다시 한다(`foundation.is_transient_lock_error`, 드라이버 오류가 감싸져 있어도 원인으로 판별). 상한(5)을 넘게 교착을 만나도 자동 재처리에서 빠지지 않고, 처리 명령 요약에 일시 오류 건수를 따로 낸다. 판정 앞 대기(`records/ordering.py`)의 1205도 같다. API는 그대로 `OperationalError` → 503 + `Retry-After`.

**재계산·과금 경쟁** — 설계 §10 "소진액 재계산 규약"(소진액 행을 잠근 뒤 원장을 읽음, 과금은 키로 갱신하고 없을 때만 생성, `check_ledger`가 소진액도 대조). 두 연결의 순서를 고정한 시험 8개(읽은 직후 커밋된 과금, 잠금 중 도착한 과금, 행 없는 쌍, 재계산 중 새 캠페인, 오래된 행 삭제 중 과금, 행 삭제 직전 멈춘 과금, 행 생성 경쟁에서 진 과금, 어긋남 보고).

**검토 보완 두 번** — ① 검토 DB-1a P2(구현 `7aac929`): 재계산이 원장을 읽은 뒤 커밋된 과금을 소진액에서 잃던 경쟁(원장 30·소진액 10) — 위 재계산 규약. ② 외부 검토 `7aac929` P2 2건(구현 `6fc9664`): (가) `check_ledger`가 원장 합계와 소진액을 별도 SELECT로 읽어 사이에 커밋된 정상 과금을 거짓 불일치로 보고 → 검사 전체를 `REPEATABLE READ` 한 읽기 스냅샷(`consistent_read`)에서, 전역 격리 수준은 그대로 (나) 재계산이 행 조회와 잠금을 따로 해 다른 재계산이 그 사이 행을 지우면 중단 → `select_for_update().get_or_create()` 한 문장. 실제 두 연결 시험 3개(검사 도중 커밋된 과금은 불일치 아님, 진짜 불일치는 여전히 보고, 경계 변경 절차에서 겹친 재계산 둘 다 완료), 25회 반복 무실패.

**반복 실행** — 동시성 시험 41개를 **30회**, 위험한 3묶음을 **60회** 반복해 실패 0. 정상 경쟁에서 오류·503·교착이 나면 드러나도록 SQLite 시절의 재시도 루프를 시험에서 없앴다(낙관적 잠금의 패자는 `StaleVersion`이어야 함). 변형 검사(행 잠금·키 갱신·키 수집·삭제·검사 제거·분류 코드 등) 모두 검출. 전체 772개 + `check.sh` 통과(보완 뒤 775개).

### 7.3.4c InnoDB Cluster 로컬 시험 (2026-10-10, 구현 `b481024`)

운영 MySQL을 InnoDB Cluster로 바꾸는 요청(7.3.4 #8)의 근거로, 앱을 바꾸지 않고 같은 점검·부하·장애 시험을 클러스터 위에서 돌렸다.

**환경**
- **이미지·도구**: `docker/innodb-cluster/` 이미지(서버 8.4.11 generic tarball, Shell·Router 8.4.10)와 `scripts/mysql_cluster.py`.
- **구성**: 노드 3개(그룹 복제, 단일 primary, 일관성 `BEFORE_ON_PRIMARY_FAILOVER`, `expelTimeout` 5초, 자동 재합류) + Router 1대. 앱은 Router 읽기·쓰기 포트로만 접속한다.
- **계정**: `root`(노드 안)·`failover`(클러스터 관리)·`router`(부트스트랩)·`dev`(앱).
- **격리**: 포트·비밀번호는 무작위이고 공유 컨테이너는 건드리지 않는다.

**사용법**
- `scripts/cluster_check.sh`: 클러스터를 띄워 `check.sh`와 150 동시 부하를 돌리고 지운다.
- `--failure`: 클러스터 장애 시험 8개를 더 돌린다. 실행 예: `env -u DB_NAME scripts/cluster_check.sh --failure`(셸에 정해 둔 `DB_NAME`을 빼고 돌린다 — 클러스터에는 `ads_server`만 만들어진다, README).
- 기본 게이트는 단일 노드 `check.sh`이고, 이것은 운영 구성을 확인하는 추가 점검이다(README "InnoDB Cluster 시험 환경").
- `cluster_check.sh`는 시작 전에 환경에 남은 이전 클러스터 값을 비우고, 기동 명령의 종료 코드를 직접 확인한다. 기동에 실패하면 후속 시험 없이 비정상 종료하고, 정리는 **이번 실행이 만든 클러스터에만** 건다(이전 ID를 지우지 않는다) [보완 2026-10-10, 외부 검토 `b481024`].

**결과**
- **게이트**: 클러스터에서 `check.sh` 통과(시험 977개, 단일 노드 약 90초 대비 약 127초 — 구현 세션). 단일 노드 `check.sh`도 977개로 다시 통과했다.
- **150 동시**(문서 세션 재측정): 모든 불변식 충족, 모든 요청이 첫 시도에 성공했다. 쓰기 단계의 p95는 단일 노드보다 약 10~50% 길었다. 결정 POST의 서버 안쪽 중앙값은 약 11 ms로 단일 노드의 약 7~8 ms보다 길다. 이벤트 최대 지연은 4.5초이고 늦은 이벤트는 0건, 백필 훈련과 구간 manifest 일치도 통과했다(`load-test.md` §9.1).
- **장애 시나리오 8개**(문서 세션 재측정): 모두 통과했다. 확인한 쓰기 유실 0·이중 과금 0·500 0이고, 끝에서 모든 노드가 ONLINE·primary 하나·노드 간 GTID 집합과 표별 행 수가 같았다.
  - **primary-kill**: 24.7초 뒤 자동으로 새 primary, 끊김 114회. 죽은 노드는 재기동 뒤 스스로 합류했다. 이벤트 최대 지연은 22.3초로 여유 120초 안이다.
  - **switchover**: 53.5초, 끊김 8회.
  - **나머지**: primary-restart·router-restart는 끊김 8회, secondary-kill은 0회. processor-kill·mongo-restart·relay-kill은 단일 노드와 같았다.
  - 수치는 `load-test.md` §9.2.

**발견**
- **기본 키 없는 표**: 그룹 복제는 기본 키 없는 표를 거부한다(오류 3098). 앱의 표는 모두 기본 키가 있고, 시험이 임시로 만들던 표(`test_mysql_admin`)만 걸려 기본 키를 더했다.
- **failover 중 오류**: 앱이 본 오류는 연결 실패(2003)·연결 끊김(2013)뿐이었고, 기존 503 + 재시도가 처리했다. 읽기 전용(1290)·그룹 복제 롤백(3100·3101)은 관찰되지 않아 일시 오류 분류는 바꾸지 않았다.

**한계와 인프라에 알릴 점**
- **환경의 한계**: 한 호스트의 Docker 클러스터라 네트워크 분리·지연 주입이 없다. 인프라 서버의 실제 failover 시간과 유실 범위는 따로 확인한다.
- **failover 시간**: failover가 앱에 보이기까지 약 22~26초다(`expelTimeout` 5초 + 선출 + Router 갱신). 매체 재시도는 "2xx까지"라 견디지만, 그동안 결정 요청은 503이다.
- **계획된 전환**: 부하 중 약 53초가 걸렸다. 전환 전에 트래픽을 줄이는 운영 절차가 필요할 수 있다.
- **허용 유실 범위**: 강제 failover의 허용 유실 범위 결정(7.3.4 #6)은 사용자 몫으로 남는다.

### 7.3.5 위험

| 위험 | 대응 |
|---|---|
| MySQL에서 시험이 많이 깨진다 | DB-1a에서 먼저 **실패 목록만** 만들고 원인별(제약·원시 SQL·시간 정밀도·정렬)로 묶어 고친다 |
| 교착이 부하에서 늘어난다 | S5·S6, 부하 시험으로 격리 수준을 정하고 잠금 순서를 점검한다 |
| failover와 유실 | **두 경우를 구분한다.** ① **계획된 전환**(switchover, 두 노드가 모두 살아 있을 때): 복제를 따라잡은 뒤 바뀌므로 확인한 데이터는 유지되고, 진행 중인 요청은 503 + 재시도다. ② **원본 노드 장애 뒤 강제 failover**: 저장소가 **비동기 복제**(InnoDB ReplicaSet)라 기본 노드에서 커밋·2xx까지 끝났지만 복제 전에 노드를 잃으면 **이미 수신 확인한 반응·결정이 사라질 수 있다**(매체는 2xx를 받아 재시도를 끝낸 뒤라 503 재시도로 설명되지 않는다. MySQL Shell 8.4 매뉴얼 §9.8). 수신 2xx의 약속은 **"노드 하나의 내구성(커밋, `synchronous`)"까지**다. DB-1d에서 ①을 실측하고 ②는 모의(원본 중지 후 강제 승격)해 **확인한 ID의 생존 검사**로 유실 범위를 재며, **허용 유실 범위와 복구 절차는 사람이 정한다**(7.3.4) |
| 로컬(8.4)과 운영의 설정 차이 | 컨테이너에 인프라의 `infra.cnf` 핵심(GTID·문자셋)을 같이 두고, 통합 확인을 인프라 서버에서 한다 |

---

# 8. Step 3~6 (요약)

| 단계 | 내용 |
|---|---|
| Step 3-1 **[승인 2026-10-12, 외부 검토 `13f3bc2` 통과]** | 관리자(Django admin): 입찰 정책 새 버전 입력과 **일괄 입력 동작**, 매체·슬롯, 광고 모니터링(썸네일·이동 주소 도메인), 중단/해제(사유), **재검토 대기 목록(해제/반려)**, 광고주 비활성화·비밀번호 초기화, 포인트 조정, 감사 로그 열람 |
| Step 3-2 **[승인 2026-10-12(a~f), 외부 검토 `13f3bc2` 통과]** | 광고주 콘솔: 대시보드(포인트 위젯), 캠페인·광고그룹 목록, 광고 만들기(단계형), **정지 사유·재검토 요청 버튼**, 포인트 내역, 내 정보. **콘솔 뷰에 비즈니스 규칙을 두지 않는다**(설계 §6.6). **규칙의 원본은 `contracts/console.openapi.yaml`(C6 초안)** — 서비스가 이 규칙을 지키고 화면은 그대로 따른다 |
| Step 3-4 **[완료 2026-10-12]** | 코드 정리 — 리팩터링 3차. Step 4-4 정리 뒤(`4de457f`)부터 Step 3 승인(`4fcb2ef`)까지의 반복·쓰지 않는 코드를 정리하고(동작 불변), 화면의 중복 읽기(B1)와 광고그룹 목록 N+1은 3-4g 한 단계로 따로 고쳤다(의도한 동작 변화). **8단계**(3-4a → … → 3-4h), 상세는 §8.3. 구현 `a9a5a38`~`4d42b7e` |
| Step DB | **DB 전환(Step 2 마무리 직후, Step 3 전)** — 상세는 §7.3. DB-1: MySQL 이전 — 설정·마이그레이션, SQLite 전용 동작(조건부 유일 제약 등) 재설계, 동시성 재검증(부하 시험 재실행), **테스트를 MySQL에서**. DB-2: MongoDB 연결(레플리카셋)·`ad_events` 컬렉션·색인(아직 쓰지 않음). 결정 근거는 설계 §10 "저장소 단계" |
| Step 4-1 **[완료 2026-10-10, 로컬]** | outbox(MySQL, 업무 데이터와 같은 트랜잭션, 열은 Debezium outbox 라우터 기본 모양과 맞춤) + 중계 → MongoDB `ad_events`(`_id = event_id` 멱등: 같은 내용 통과·다른 내용 충돌로 멈춤), 이벤트 스키마(C2) 확정. 파이프라인 쪽 경계는 이 컬렉션(MySQL 직접 읽기 없음). 하위 단계: 4-1a outbox 표·쓰기 규약, 4-1b 결정 이벤트, 4-1c 접수·판정 이벤트, 4-1d 과금 이벤트, 4-1e 중계·보존 정리, 4-1f 부하·장애 시험의 이벤트 검증(§10 진행 표). 남은 것: 3대 레플리카셋 failover(인프라 서버 확인) |
| Step 4-2 **[완료 2026-10-10, 외부 검토 보완 반영]** | NDJSON manifest·검증 도구(정합성 점검 결과, 재처리·백필 대상 목록. 게시 = 내용 해시가 이름에 들어간 불변 데이터 파일 + manifest 포인터의 원자적 교체, manifest = 파일 이름·SHA-256·행 수·`schema_version`·`source_kind`·checkpoint(범위 서술, 재개 위치 아님)). 백필 대상 **목록까지** 만들었다 — 이 목록(`event_gaps`)이 4-3a 백필의 입력이다 |
| Step 4-3 **[완료 2026-10-10, 로컬]** | 이벤트 백필과 구간별 정합 manifest(설계 §6.3a, 결정 설계 §10 "Step 4-3 백필·구간 manifest 결정"). 4-3a → 4-3b → 4-3c → 4-3d 순으로 하나씩 구현·검증·커밋하고, d05d681 위에 쌓는다. **4-3a 백필 실행** `backfill_events`: 검증을 통과한 `event_gaps` manifest를 입력으로 원본 행에서 이벤트를 다시 만들어 outbox에 쓴다(중계가 평소처럼 보냄). 멱등(결정적 이벤트 ID), 기본 `--dry-run`, 청크 단위 트랜잭션, 결과 `backfill_result`(새로 쓴 건수·이미 있던 건수·해석 불가) + 감사 로그 — 완료 증거: 백필 뒤 `export_integrity`의 `event_gaps` 0행, 백필한 이벤트가 `verify_events`(원본 대조)를 특별 처리 없이 통과. **4-3b 구간별 정합 manifest** `export_hop_manifests`: 같은 창에 대해 원본 기대 / outbox / MongoDB 세 구간의 (창, 이벤트 이름)별 건수·`ids_sha256`·`content_sha256` — 완료 증거: 세 구간이 같은 창에서 일치, 어느 구간을 바꿔도 manifest 대조만으로 검출. **4-3c 구간 대조** `verify_hops`: 두 구간 manifest(파이프라인 쪽이 같은 규칙으로 만든 것 포함)를 대조해 어긋난 창·이벤트 종류를 보고, 세대 연결(`previous_sha256`) 확인 — 완료 증거: 불일치 반례 시험, 백필로 창이 다시 열려도 새 세대로 일관. **4-3d 부하·장애 시험**에 백필과 구간 manifest 대조 추가 — 완료 증거: `check.sh` 통과, 장애 시나리오에서 복구 뒤 manifest 일치, **다음 세대에 늦게 나타난 이벤트 수**를 세어 창 닫힘 여유 2분(H11 A안)이 충분한지 확인(늦은 이벤트가 보이면 B안: 잠금 대기 제한을 정해 상한에서 여유를 정하고 150 동시·장애 시험을 다시 잰다). 문서와 시험은 MySQL 노드·주소에 기대지 않는다(InnoDB Cluster 전환 뒤에도 같은 계약) |
| Step 4-4 **[완료 2026-10-11, 외부 검토 승인]** | 코드 정리 — 리팩터링 2차(`c4a6b63`~`5666946`)가 남긴 동작 차이 1건과 중복을 동작 변화를 명시하고 시험으로 고정하며 정리한다. **7단계 + 선택 1**(4-4a → b → c → d → i → h → k, 선택 4-4e). 일부러 남기는 중복 C1~C6, 상세는 §8.2. 구현 `e53a15a`~`4de457f`, 외부 검토 P2 보완 `6b563cf` |
| Step 5(확장) | 조건부·기록만: Debezium outbox 라우터 → Kafka(중계 대체 — **전환 게이트**: 전송 확인·보존 기준, 라우터의 UPDATE·DELETE 처리, 봉투 매핑, 설계 §6.3), Spark → Delta 메달리온(설계 §10 "분석 계층 대응"), 스키마 저장소, C4 수신(`records.api` 집계 안쪽 교체) |
| Step 6 **[진행 중, 2026-10-12~]** | **Step 3 이후 수정** — 연동 검토·운영·외부 검토에서 나오는 수정을 하나씩 쌓는다(6-1, 6-2 …, 수정마다 계기·결정·계획·완료 증거). 상세는 §8.4. 6-1 매체 연동 검토(게임 ad-bridge) 후속 **완료(2026-10-12)**: 결정 반영(C1 1.2.0), 서버 규칙 `media_deactivated` 6-1a `42de743`·6-1b `a70d769`(기록 표 방식), 질의 수 기준선 10 · 39 · 27, 계약 반영 6-1d |

## 8.1 Step 3 상세 계획 (2026-10-08 작성, 2026-10-12 갱신 — 3-0~3-3 구현, 승인 2026-10-12 외부 검토 `13f3bc2` 통과)

### 8.1.1 전제와 원칙

- **서버 렌더(Django 템플릿) + 폼 POST.** 엄격한 CSP(`script-src 'self'`, 인라인 스크립트·`style` 속성 금지)가 이미 켜져 있어 JS 없이 동작하는 화면이 기본이다(폼 제출·링크). 필요한 곳에만 **작은 JS를 덧붙인다**(D3-1): ① JS가 꺼져도 모든 흐름이 동작하고 JS는 편의만 더한다(점진적 향상, 흐름 확인은 지금처럼 서버 시험) ② JS에 비즈니스 규칙을 두지 않는다 — 서버 계산이 필요한 것은 JS로 흉내 내지 않고 "미리보기" 제출로 서버가 계산한다 ③ 스크립트는 우리 서버의 정적 파일로만 둔다(인라인·외부 CDN 없음, CSP를 바꾸지 않는다). 차트는 **서버가 만든 인라인 SVG**(표현 속성만, 라이브러리 없음)이고 옆에 같은 값의 표를 둔다(D3-2, 접근성).
- **공용 도우미를 쓴다(3-0의 전제).** 리팩터링에서 `foundation.api`로 모은 역할 검사 `require_admin`·`require_advertiser`, 형식이 틀린 ID를 버리는 일괄 조회 `parse_uuids`, 읽기 전용 관리자 화면 `ReadOnlyAdmin`을 콘솔이 그대로 쓴다. 콘솔에 사본을 새로 만들지 않는다.
- **새 이벤트 종류를 만들지 않는다.** Step 3의 쓰기 동작(입찰 정책 새 버전·중단/해제·포인트 조정·광고 만들기)은 감사 로그만 남긴다. C2 이벤트는 결정·접수·판정·과금 네 종류뿐이다(설계 §10 "C2 이벤트 모양").
- **뷰는 얇다(설계 §6.6).** 비즈니스 규칙(검증·소유권·상태 전이·금액 계산)은 서비스 `api`/`engine`에만 둔다. 뷰는 "서비스 호출 → 렌더"이고, 도메인 예외를 화면 메시지·폼 오류로 바꾸는 코드는 **콘솔 가장자리 한 곳**(`console/errors.py`)에만 둔다. **경계 테스트로 강제**한다(`tests/boundaries/test_console_rules.py`, 3-0c `4bebbe5`): `console` 아래 파일은 `django.db` 전체(트랜잭션·모델·원시 SQL)와 `engine`(금액 계산)을 import하지 않고, 모델 매니저(`X.objects`·`_default_manager`·`_base_manager`)로 직접 조회하지 않는다. 다른 모듈은 지금처럼 `<module>.api`만 쓴다(층 규칙). 그래서 여러 단계를 한 트랜잭션으로 묶어야 하는 일(예: 가입 = 계정 + 지급 + 감사)은 서비스 쪽에 둔다(`billing.register_advertiser`).
- **여러 모듈의 값을 모으는 화면 전용 조립**(예: 캠페인 목록의 `today` = 캠페인 + 소진액, 알림, 입찰 미리보기 `effects`)은 `console/queries/`에 둔다. 규칙을 새로 만들지 않고 각 `api` 결과를 합치기만 한다(C6가 이미 "콘솔이 채운다"고 한 부분). 같은 층(L2)의 `campaigns`·`billing`은 서로 import할 수 없으므로 조립 위치는 L4 `console`이다.
- **관리자 화면은 Django admin 위에 얹는다.** 모델 직접 편집은 계속 막고(읽기 전용), 쓰기는 **서비스 `api`를 부르는 전용 페이지·동작**으로만 한다. 여러 모듈을 가로지르는 관리자 페이지는 L4 `console/operator/`에 두고 admin 사이트에 등록한다(각 앱의 `admin.py`는 자기 모델만 본다). [구현 3-1a `e557e0d`] 운영 화면의 경로는 **관리자 경로 + `operator/`**(`<ADMIN_URL_PATH>operator/`)라 관리자 경로 규칙(관리자가 아니면 익명·광고주 모두 **404**로 존재를 숨김, 위협 모델 T7)을 그대로 받는다. admin 첫 화면에 운영 동작 링크를 둔다. **로그인 잠금 기록(django-axes) 세 화면도 읽기 전용**이다(삭제 = 잠금 해제·기록 지우기도 막음, 결정 2026-10-11 — 설계 §10 "로그인 잠금 기록 관리"). 급한 잠금 해제는 서버 명령(`axes_reset_username` 등)으로 한다.
- **두 번 하면 안 되는 동작은 요청 키로 한 번만** [3-1a에서 세션 토큰(`console/once.py`)으로 시작, 외부 검토 3-1d 보완 `ab7a607`·`1e72031`에서 바꾸고 `once.py` 삭제]: 폼을 그릴 때마다 새 `request_key`를 싣고, 서비스가 그 키를 **결과 행에 같은 트랜잭션으로** 저장한다(유일 제약). 같은 키의 두 번째 요청은 유일 제약에 막혀 트랜잭션 전체가 되돌려진다. 근거: 세션 토큰은 소비(세션)와 결과 쓰기(DB)가 다른 저장소라 **동시 제출**과 **커밋 뒤 응답이 실패한 재시도**를 한 번으로 묶지 못했다 — 키 발급에서는 평문을 아무도 보지 못한 유효 키가 하나 더 생겼다. 쓰는 곳: 매체 키 발급·교체(`MediaKey.request_key`, 두 번째는 409와 키 식별자 — 평문은 다시 보여 줄 수 없으므로 받지 못한 키는 폐기 안내), 포인트 조정(`LedgerEntry.adjust_key`, 같은 키는 처음 결과·다른 내용이면 409), **3-2c 광고 만들기도 같은 방식**이다(`Campaign.request_key`, `b61112a` — 같은 키면 처음 만든 광고를 돌려주고, **만들기 전에 키를 먼저 본다**: 처음 제출로 캠페인 상한에 닿은 뒤 다시 보내도 "상한 초과"가 아니라 이미 만든 광고로 간다. 동시 제출은 유일 제약이 막는다). **이미 성공한 키는 폼 검증보다 먼저, 그리고 광고주 잠금 안에서 다시 확인한다** [외부 검토 41d2288 보완 `7fdc76f`]: 화면이 폼 검증 전에 `campaigns.ad_created_by_key`로 보고(그 사이 고른 위치가 꺼져 400이 되거나 상한에 닿아도 처음 결과로), 서비스는 광고주 잠금(`AdvertiserQuota`)을 잡은 뒤 한 번 더 본다(첫 조회와 앞선 요청의 커밋 사이에 겹친 다시 보냄이 상한 오류로 끝나던 틈). **응답은 계층마다 다르다**: 서비스는 본인 키면 처음 결과(`duplicate=True`), **남의 캠페인에 붙은 키(위조한 폼)면 409**(`Conflict`). 화면(`console/views/ads.py`)은 본인 키의 다시 보냄을 **처음 만든 캠페인 상세로 302**("이미 만든 광고입니다"), 남의 키는 409를 오류 메시지로 바꿔 **광고 만들기 화면으로 302** 한다 — 같은 302라도 가는 곳과 뜻이 다르다.
- **화면의 교착·잠금 대기 초과는 503** [외부 검토 `00d3067`, 구현 `8449469`]: 뷰 밖으로 나온 교착(1213)·잠금 대기 초과(1205)는 서버가 그 트랜잭션을 되돌린 것이라 500 대신 **503 + `Retry-After: 1`**로 응답한다(`ApiErrorMiddleware` — 화면은 HTML, `/api/`는 problem+json). 연결 끊김처럼 커밋 결과가 불명확한 오류와 다른 오류는 그대로 둔다. **자동 재시도는 하지 않는다**(사용자가 다시 보낸다). 매체 API는 원래대로 `serving_api/auth.py`가 `OperationalError`를 503으로 바꾼다(S6).
- 모든 쓰기는 PRG(POST → 리다이렉트 → GET)와 CSRF, 위험한 동작은 **사유 필수 + 감사 로그**(서비스가 이미 같은 트랜잭션에 남긴다). `subject_id`·매체 키·다른 광고주 정보는 어떤 화면에도 나오지 않는다. 시각은 KST로 표시하고 UTC 기준 항목(예산 리셋)은 리셋 시각을 적는다. 숫자에는 단위("포인트")를 붙인다.
- 광고주가 입력한 문자열(제목·이름·이동 주소)은 **항상 이스케이프**하고, 이동 주소는 `https`만 링크로 만들며 `rel="noopener noreferrer nofollow"`, 관리자 화면에는 **도메인을 눈에 띄게** 표시한다.

### 8.1.2 서비스 보강 (화면이 필요로 하는데 아직 없는 것)

| # | 필요 | 위치 | 내용 |
|---|---|---|---|
| S1 | 성과 지표(C6 `/reports/daily`) **→ 2-10으로 앞당김(퍼널 집계)** | `records.api.daily_report(owner, from, to, campaign_id=None, ad_group_id=None)` | `ACCEPTED` 반응 수를 유형별·예산 일별로 집계(결정의 `owner_id`·`campaign_id`로 소유 범위를 좁힌다) + `billing`의 그날 소진 포인트, 바로 앞의 같은 길이 구간 `previous_totals`. `records`(L3)가 `billing`(L2)을 읽는 방향이라 층 규칙에 맞는다 |
| S2 | 프로필·비밀번호(C6 `/me`, `/me/password`) | `foundation.api.update_profile`, `change_password` | 닉네임·반 검증(가입 규칙 재사용), 현재 비밀번호 확인, 비밀번호 검증기, 감사 로그, 변경 후 현재 세션 유지·다른 세션 무효화 |
| S3 | 광고 만들기(집행)의 원자성 | `campaigns.api.create_ad(user, campaign, ad_group, creative)` | 캠페인·광고그룹·소재를 **한 트랜잭션**으로 만든다(이미지 검증 실패 때 빈 캠페인이 남지 않는다). 기존 개별 서비스를 안에서 재사용. **입력 오류의 위치**는 부분 이름을 앞에 붙인 `/campaign/…`·`/ad_group/…`·`/creative/…`이고(화면은 `console/errors.py`가 폼 칸으로 바꾼다), 이미지 거절(`ImageRejected`)은 그대로 전달한다. 역할 검사는 각 부분 서비스가 한다 [구현 3-0b `dd305d6`]. [3-2c `b61112a`] `create_ad(…, request_key=)`(요청 키를 캠페인 행에 같은 트랜잭션으로, 유일 제약 — 남의 캠페인에 붙은 키면 서비스는 409 — 화면은 오류 메시지와 함께 광고 만들기 화면으로 302, §8.1.1), 미리보기용 `campaigns.bid_effects(amount, slot_ids)`(3-2a의 위치별 판정을 그대로 써서 적용 금액은 `engine` 한 곳. 3-4g `24fe4dd`부터 선택 인자 `slots=` — 광고그룹 상세는 이미 읽은 슬롯 정책을 넘겨 다시 읽지 않는다) |
| S4 | 광고주 본인 소재 이미지 | `console` 전용 뷰 + `campaigns.get_creative`(소유 확인) + `assets.open_asset` | 공개 `/assets/…`는 `SUSPENDED`·`ENDED` 캠페인 이미지를 404로 막는다. 광고주는 **자기 소재**를 중단 중에도 봐야 하므로 소유 확인 후 같은 보안 헤더(`nosniff`, 캐시 정책)로 내려 주는 별도 경로를 둔다. [구현 3-2d `3baf897`] `/advertiser/creatives/<id>/image-file` — 소유를 확인한 뒤에만(남의 것 404), `nosniff`·`no-store`, 중단 중에도 본인은 본다 |
| S5 | 관리자 목록용 조립 | `console/queries/` | 광고 모니터링(캠페인+소재+광고주 닉네임·반+이동 주소 도메인), 재검토 대기 목록. 읽기 전용 조립. [3-3d `ca2572c`, 외부 검토 `00d3067` P3-4 2단계] `campaigns.monitoring_list`는 **마지막 변경 시각**(캠페인·소재 중 늦은 쪽, 소재가 없으면 캠페인)을 DB에서 계산해 최근순으로 정렬하고, **같으면 캠페인 ID 역순**(UUIDv7 — 나중에 만든 것 먼저)으로 끊어 쪽끼리 겹치거나 빠지는 줄이 없다. **쪽 나누기도 DB에서**(`Paginator`가 자른 쪽의 캠페인·소재·열린 재검토 요청만 읽음) — **쪽마다 질의 4번**(개수·그 쪽 캠페인·소재·열린 재검토 요청). 전에는 모든 캠페인·소재를 읽어 파이썬에서 정렬했다. 한계: 정렬 키가 계산 값이라 색인을 쓰지 못해 쪽마다 모든 캠페인을 훑어 정렬한다(광고주 150명 × 캠페인 상한 20 = 3,000행) — 더 커지면 마지막 변경 시각을 캠페인 열로 두고(소재 변경 때 함께 갱신) 색인한다 |
| S7 | 관리자의 광고주·포인트 화면 (3-1d `749148a`) | `foundation`·`campaigns`·`billing` | `foundation`: `list_advertisers`·`get_advertiser`·`set_advertiser_active`(비활성화는 사유 필수, 다시 활성화는 사유 선택, 같은 상태면 409). `campaigns`: `advertiser_usage`(상한 검사와 같은 기준 — 교체한 과거 파일 포함, 같은 파일은 한 번, 질의 3번). `billing`: `wallet_of`·`ledger_of`(관리자용, 광고주용 `get_wallet`·`list_ledger`와 내부 공유). `foundation.ProfileView`에 `is_active`(C6 Profile에는 없음, 관리자 화면 표시용) |
| S8 | 광고주 대시보드 (3-2a `6f05beb`·`362a4c6`) | `records`·`billing`·`campaigns`, 조립은 `console/queries/dashboard.py`·`alerts.py` | `records.campaign_totals(owner, start, end)`: 기간의 캠페인별 합계 — `daily_report`와 같은 규칙(인정된 반응을 수신일로, 소진은 실제로 받은 포인트)을 묶음 기준만 결정의 캠페인으로 바꿔 쓴다(기존 집계 함수가 묶음 기준을 인자로 받음, 질의 수는 데이터와 무관). `billing.spend_by_campaign`: 캠페인별 소진 합(질의 한 번). `campaigns.ad_group_effects`: 광고그룹마다 현재 입찰을 게재 위치별 현재 정책에 대어 본 결과(`SlotEffect` 종류 `within_range`·`capped_at_cap`·`below_floor`·`slot_inactive`·`no_policy`, 적용 금액은 `engine`의 `effect_of` 한 곳, 3-2c·3-2d의 입찰 안내도 이것을 쓴다). `campaigns.latest_review_requests`: 캠페인마다 가장 최근의 재검토 요청(반려 답변). 조립: `dashboard.py`는 상위 캠페인(캠페인 이름과 합침), `alerts.py`는 알림 패널(저장 없이 지금 상태에서 계산). 3-4g `24fe4dd`부터 화면이 한 번 읽은 캠페인 목록·지갑을 둘이 함께 받는다(`top_campaigns(user, start, end, camps, limit=TOP)`·`alerts_for(user, now, camps, wallet)`) |
| S9 | 원장 줄의 캠페인 이름 (3-2e `41d2288`) | `campaigns.campaign_names(ids)` | 캠페인 ID → 이름(**표시용**, 질의 한 번, 없는·형식이 틀린 ID는 결과에 없음). 광고주 포인트 화면과 관리자 광고주 상세의 원장 표가 쓴다. 역할·소유 검사가 없으므로 **호출한 쪽이 보여도 되는 ID만 넘긴다**(지금은 이미 범위가 좁혀진 원장 줄에 적힌 ID만) |
| S6 | 매체 키 발급·교체·폐기를 화면에서 | 기존 `masters` 서비스 호출 | **평문 키는 응답 한 번만**(`no-store`), 목록에는 `key_id`·상태·만료만 |

### 8.1.3 단계

| 단계 | 내용 | 완료 증거 |
|---|---|---|
| **3-0 기반** | S2·S3 서비스(S1은 2-10)(+단위 테스트·위협 모델 행), 콘솔 공통 틀: 레이아웃·내비게이션·디자인 토큰 CSS(라이트/다크, 모바일 폭), KST/포인트 템플릿 필터, 메시지, `console/errors.py`(예외 → 화면 한 곳), 쪽 나누기, 정적 JS를 싣는 자리(인라인 없음, CSP 그대로), **경계 테스트(뷰에 규칙 없음)**. 전제: `foundation.api` 공용 도우미(§8.1.1). **루트 주소 `/`**: 지금은 로그인 화면으로 임시 이동(`7fd1fa8`) → 로그인한 광고주는 대시보드, 관리자는 admin으로 보내고, 익명은 지금처럼 로그인 화면으로 | 서비스 테스트, 경계 테스트가 실제 위반을 잡음(변형 검사), 접근 제어 목록(`EXPECTED_*`) 갱신, 루트 주소가 역할마다 정한 곳으로 보냄(익명·광고주·관리자) |
| **3-1a 관리자: 매체·슬롯·키** | 매체·슬롯 등록·활성/비활성(과금 단위·**`audience`** 표시, 과금 단위와 `audience`는 생성 후 변경 불가 안내), 매체 키 발급·교체(유예 선택)·폐기, 키 평문은 한 번만 | 서비스만 호출, 감사 로그, 평문 키가 응답 한 번 외에 어디에도 없음(로그·DB·재조회), 관리자가 아니면 익명·광고주 모두 404(관리자 경로 규칙으로 존재를 숨김, 2026-10-11 고침 — 처음 계획은 403), 키 발급·교체는 같은 폼을 다시 보내도(동시 제출·응답 실패 뒤 재시도 포함) 키 하나만 — 요청 키(`1e72031`) |
| **3-1b 관리자: 입찰 정책** | 슬롯별 **새 버전 입력**(현재값이 채워진 폼, 사유 필수, 낙관적 잠금 `expected_version` 숨김 필드, 하한≤기준가≤상한 오류 표시), 이력 열람, **목록에서 여러 슬롯을 골라 같은 값으로 일괄 새 버전**(전부 성공/전부 실패 표시) | 충돌(409 동등)을 화면이 "`<슬롯 이름>`: 다른 곳에서 먼저 바뀌었습니다(현재 버전 N)."로 안내(서비스 `StaleVersion` 문구, 3-1b `7e1d9fe` — 일괄 동작에서도 충돌한 슬롯이 보인다), 일괄 동작 원자성, 감사 로그 |
| **3-1c 관리자: 광고 모니터링·중단** | 최근 등록·변경 캠페인 목록 + **소재 썸네일 + 이동 주소 도메인(강조)** + 광고주 닉네임·반, **중단(사유 필수, JS 확인 창)·해제**, **재검토 대기 목록(해제/반려+답변)**, 관리자 전용 이미지 경로. [구현 `b396d0d`] 모니터링은 캠페인·소재 중 **늦은 마지막 변경순**(소재의 이동 주소만 바꿔도 맨 위로) — 처음에는 전부 읽어 파이썬에서 정렬했고, 3-3d `ca2572c`부터 DB에서 정렬·쪽 나누기(§8.1.2 S5). 관리자 전용 이미지 경로는 `<ADMIN_URL_PATH>operator/assets/<이름>`(중단·종료 캠페인 소재도 보임, `no-store`, 관리자가 아니면 404). [외부 검토 보완 `da0eb88`] 반려도 캠페인 행을 먼저 잠그고 요청을 다시 읽음, 해제는 화면이 본 중단 회차·재검토 요청과 대조(설계 §4.5), 중단 폼 확인 창 | 중단 중인 소재도 썸네일 표시, 사유 없이 중단 불가, 광고주 정지 상태가 즉시 반영, 닫힌 요청을 늦은 반려가 덮지 않음·오래된 해제 버튼이 새 중단을 풀지 않음 |
| **3-1d 관리자: 광고주·포인트** | 광고주 목록(캠페인·소재 수, 업로드 용량 대 상한), 비활성화, 비밀번호 초기화(기존), 지갑·원장 열람, **포인트 조정**(사유 필수·0 밑으로 불가·반대 부호 항목). [구현 `749148a`·`9013a30`·`e094a17`] 비활성화는 로그인·열린 세션·광고 송출·공개 이미지를 멈추고 다시 활성화하면 그대로 다시 나간다(설계 §10). 모니터링·재검토 대기에 비활성 광고주 표시. 사용자 관리 화면은 프로필·비밀번호 초기화만 하고 모든 계정의 활성 여부가 읽기 전용(관리자 계정까지는 사용자 결정 2026-10-11, 역할·`is_superuser` 읽기 전용·계정 추가 없음(`ab5bc59`), 세션 폐기 버전, 지갑 없는 옛 계정 처리, 포인트 조정의 원장 멱등 키 — 외부 검토 3-1d 보완 `ab7a607`, 원장 커서는 ASCII 숫자 10자리까지). 관리자 원장 화면에는 캠페인 이름이 없다(3-2e에서 이름을 붙일 때 같이 쓴다 → 3-2e `41d2288`에서 같은 원장 표로 붙임) | 조정이 원장 + 감사 로그, 잔액 = 원장 합계 유지, 같은 폼을 두 번 내도 한 번만 조정, 비활성 광고주의 광고가 멈췄다가 다시 나감 |
| **3-2a 광고주: 대시보드** | 기간 선택(기본 최근 7일·예산 일 경계, 오늘 포함·오늘 칸 "집계 중" 표시, 바로 앞 7일과 비교 — D3-5), 지표 카드(노출·클릭·전환·소진 포인트 + 증감률), SVG 추세 그래프(옆에 같은 값의 표), 상위 캠페인 표, **포인트 위젯**(잔액·오늘 소진·리셋 시각), **알림 패널**(S5: 중단 사유·반려 답변·기간 종료·예산 소진·잔액 부족·입찰 하한 미만/상한 적용). [구현 3-2a-1 `b8c3d2d` 기간·지표·그래프·포인트, 3-2a-2 `6f05beb` 상위 캠페인 표(S8, 소진 포인트 → 노출 → 이름 순 5개), 3-2a-3 `362a4c6` 알림 패널(S8)] 기간은 오늘 포함 최근 7·14·30·90일(기본 7, 잘못된 값은 기본으로), 직전 값이나 분모가 0이면 "—"(나누지 않음), 그래프는 지표를 고를 수 있고 오늘 막대는 흐리게. **알림 기본값**(구현 세션이 정함, 통합 시험에서 다시 판단): 저장하지 않고 지금 상태에서 계산해 조건이 풀리면 사라지고 심각한 것부터 보인다. `campaign_suspended`(긴급) 중단 중 · `review_rejected`(주의) **이번 중단에 대한 반려만**(지난 중단의 반려는 안 보임) · `campaign_ended`(알림) 끝난 뒤 **7일 동안만**(끝난 상태는 풀리지 않으므로) · `budget_exhausted`(주의) 남은 일예산 < 그 캠페인의 가장 낮은 적용 금액 · `bid_below_floor`(주의)·`bid_capped`(알림) 진행 중 캠페인의 켜진 광고그룹만 · `balance_insufficient`(긴급)·`balance_low`(주의) D3-4. 비교는 엔진의 후보 거르기와 같다(남은 일예산·잔액 < 적용 금액이면 그 위치에 나가지 않음). "언제부터" 시각은 잔액 알림 = 지금, 입찰 알림 = 그 입찰을 넣은 시각, 예산 알림 = 오늘 예산 일의 시작. 일시 중지한 캠페인·꺼진 광고그룹·꺼진 위치는 입찰·잔액 안내에서 뺀다 | 다른 광고주의 수치가 섞이지 않음(격리 테스트), 빈 데이터·0 나눗셈 처리, 알림은 상태에서 계산 — 알림이 뜬 상태에서 엔진이 실제로 내보내지 않음(또는 일부 위치에만)까지 시험, 이스케이프(캠페인 이름·중단 사유·반려 답변)·인라인 `style` 없음, 상위 캠페인·알림의 질의 수가 데이터와 무관, 변형 검사 19건. 브라우저 확인은 3-3에서(이번에는 렌더링된 HTML만 시험) |
| **3-2b 광고주: 캠페인** | 목록(상태 배지, **ON/OFF 토글**, 기간, 일예산, 오늘 소진, 지표, `SUSPENDED`는 토글 비활성+사유), 상세(일예산·기간 수정, 종료 버튼은 되돌릴 수 없음 경고 + JS 확인 창), 광고그룹 목록. [구현 `a75bdad`] 목록의 지표는 최근 7일 노출·클릭·전환, 상단 메뉴에 "캠페인". 상세는 기간·일예산·오늘 소진·남은 예산·리셋 시각과 켜기·끄기, 수정은 이름·일예산·끝나는 시각(KST로 입력받아 UTC로 넘김, 비우면 끝 없음, **바뀐 칸만** 보냄 — 초가 있는 끝 시각을 분 단위 화면이 그대로 내도 바뀌지 않은 것으로 봄). 끝난 캠페인은 수정 폼·끝내기 버튼이 없다. **정지 사유·재검토 요청**(Step 3-2 범위)도 여기서: 중단된 캠페인은 사유와 재검토 요청 폼(대기 중이면 폼 대신 안내), 요청 내역(상태·메모·관리자 답변). 광고그룹 표는 과금 단위·켜짐·현재 입찰·위치별 결과 요약(노출 가능·하한 미만·상한 적용·꺼진 위치, `campaigns.ad_group_effects`). **수정 폼의 버전 대조**: 폼이 화면이 본 마지막 변경 시각을 숨김 칸으로 싣고 서비스가 잠금 안에서 대조해 다르면 409(`update_campaign(…, expected_updated_at=)`, 선택 인자) — 폼을 연 뒤 다른 탭·기기에서 바뀐 값을 옛 폼이 덮어쓰지 않게(외부 검토에서 여러 번 지적된 유형을 미리 막음). 켜기·끄기와 끝내기는 바꿀 값이 분명해 대조하지 않는다. 돌아갈 곳은 정해진 화면으로만(외부 주소로 리다이렉트 없음) | `ENDED`·`SUSPENDED` 규칙을 화면이 서비스 오류로만 표시(뷰에 규칙 없음), 타인 캠페인 404 — 시험 14개(상세·수정·켜기/끄기·끝내기·재검토 요청 모두 404이고 아무것도 바뀌지 않음, 중단된 캠페인 켜기·고를 수 없는 상태를 직접 보내도 서비스가 거절, 옛 폼 409, KST→UTC, 이스케이프), 변형 검사 7건. 브라우저 확인은 3-3에서 |
| **3-2c 광고주: 광고 만들기** | 단계 제목이 있는 **하나의 폼**(D3-3, 다중 페이지 위저드·초안 저장 없음): ① 과금 단위 카드 — JS가 있으면 고른 단위의 게재 위치만 바로 보이고, 없으면 단위를 고를 때 페이지를 다시 불러온다 → ② 캠페인(이름·기간·일예산) → ③ 광고그룹(이름·게재 위치 체크 목록(매체별 묶음·하한~상한·기준가, 단위가 다른 위치는 비활성)·입찰) → ④ 소재(이미지·제목·이동 주소, 규격 안내, 올리기 전 브라우저 미리보기(JS), 제목·이름 글자 수 표시(JS)) → ⑤ 확인 후 집행. 입찰 칸 아래 **위치별 적용 결과**는 실시간 계산이 아니라 **"미리보기" 제출로 서버가 계산**해 보여 준다(입력은 막지 않음). JS가 거른 값도 서버가 다시 검증한다. [구현 `b61112a`] JS가 없으면 단위 카드 옆 "이 단위의 게재 위치 보기" 버튼이 입력값을 그대로 둔 채 다시 그린다. 미리보기는 그대로 적용·상한으로 적용·하한 미만·꺼진 위치를 보인다(`bid_effects`). **미리보기·단위 고르기는 저장하지 않는 제출**이라, 그때 고른 이미지는 다시 골라야 한다. 이미지 용량이 상한을 넘으면 JS가 안내만 한다(막지 않음). 집행 버튼에만 확인 창(승인 없이 바로 집행된다는 안내, `confirm.js`가 누른 버튼의 `data-confirm`도 읽음). 캠페인 목록에 "+ 광고 만들기". **중복 제출은 세션 토큰이 아니라 `Campaign.request_key`**로 막는다 — 만들기 전에 키를 먼저 확인하고(상한에서 다시 보내도 처음 만든 광고로), 동시 제출은 유일 제약이 막으며, 같은 키면 그 캠페인으로 가서 "이미 만든 광고입니다". 큰 이미지의 413은 화면 경로에서 HTML 오류 화면(설계 §10 "업로드 전체 크기 가드") | `create_ad` 원자성, 중복 제출 방지(요청 키를 결과 행에 같은 트랜잭션으로 + PRG, §8.1.1), 이미지 거절 사유 표시, 쿼터 초과 안내 — 시험 15개(어느 부분이 거절돼도 빈 캠페인이 남지 않음, 두 번 누름·동시 제출(실제 MySQL 연결 두 개)·응답 실패 뒤 재시도·상한에서 다시 보냄 모두 광고 하나, 오류가 정확한 칸에(광고그룹 이름 오류가 캠페인 칸으로 가지 않음), 다른 단위 위치를 직접 보내면 거절, 꺼진 위치는 목록에 없음, 이스케이프, 권한), 변형 검사 9건("만들기 전 키 확인"을 빼는 변형은 상한 재제출 시험을 더해 잡음). 작은 JS 셋(단위별 위치 거르기·글자 수·이미지 미리보기)과 확인 창의 브라우저 확인은 3-3에서 |
| **3-2d 광고주: 광고그룹 상세** | 게재 위치별 적용 결과, **입찰 변경 이력**(버전 목록)과 새 입찰(낙관적 잠금 충돌 안내), 위치·ON/OFF 수정(과금 단위 불변 안내), 소재 미리보기·제목/주소 수정·이미지 교체(S4). [구현 서비스 결함 수정 `a909908`, 화면 `3baf897`] 화면에 올리기 전에 서비스 결함을 고쳤다: 입찰 추가·광고그룹 수정·소재 수정·이미지 교체가 잠그지 않고 읽은 객체를 통째로 저장해, 제목 수정과 이미지 교체가 겹치면 이미지가 되돌아가고 끝난 캠페인에도 쓸 수 있었다 → 캠페인 행 → 그 행 순서로 잠가 다시 읽는다(설계 §10 "캠페인 행 잠금 규약"). 화면: 현재 입찰과 위치별 결과(그대로 적용·상한으로 적용·하한 미만·꺼진 위치), 입찰은 새 버전으로 추가만·이력, 그 사이 바뀌었으면 409 "다른 곳에서 먼저 바뀌었습니다(현재 버전 N). 새로 불러와 다시 넣으세요."(3-3c `526046d`에서 다른 충돌 문구와 맞춤). 광고그룹의 이름·게재 위치·켜기/끄기는 **동작마다 작은 폼** — 한 칸을 바꾸는 제출이 다른 칸을 옛 값으로 덮지 않는다. 과금 단위 불변 안내, 지금 꺼진 위치는 "다시 저장하면 빠집니다". 소재는 본인 전용 이미지 경로 `/advertiser/creatives/<id>/image-file`(S4)로 미리보기, 제목·주소 수정은 바뀐 칸만 보내고 **화면이 본 변경 시각과 대조**(`update_creative(…, expected_updated_at=)`, 다르면 409), 켜기·끄기, 이미지 교체(이전 파일은 보관 — 3-3c `526046d`부터 **소재마다 따로 된 폼**이고 필드 이름은 `<소재ID>-image`·`<소재ID>-updated_at`, 화면 폼만의 이름이라 C6 계약은 그대로). 캠페인 상세의 광고그룹 이름에서 이어진다 | 입찰은 추가만, 충돌 안내, 교체한 과거 이미지 보유 규칙은 서비스 그대로 — 시험 화면 15개·경쟁 3개(실제 MySQL 연결 두 개: 제목 수정 중 이미지 교체는 둘 다 남고, 광고그룹 수정·새 입찰과 캠페인 끝내기는 줄을 서서 끝난 뒤의 쓰기가 없음, 남의 광고그룹·소재는 모든 경로 404이고 아무것도 바뀌지 않음, 끝난 캠페인의 입찰은 서비스가 거절, 옛 소재 폼 409, 오류는 그 칸에, 이미지 거절 사유, 이스케이프), 변형 검사 9건(잠금 2·화면 7). 브라우저 확인은 3-3에서 |
| **3-2e 광고주: 포인트** | 잔액, 원장 내역(최신순 커서 쪽 나누기, 지급·과금·조정, 과금은 캠페인 이름과 함께), 오늘 소진. [구현 `41d2288`] 잔액·오늘 소진·다음 리셋 시각(KST), 지갑이 없는 옛 계정은 안내만. 원장은 최신순 50줄씩 커서("더 이전 항목"·"처음으로", 틀린 커서는 첫 쪽), 과금 줄은 캠페인 이름과 잔액이 모자라 못 받은 포인트(S9). 상단 메뉴 "포인트", 대시보드 포인트 위젯에서 이어짐. **원장 표는 공용 부분 템플릿**(`console/_ledger.html`)이라 관리자 광고주 상세도 같은 표를 쓰고, 관리자 원장에도 캠페인 이름이 나온다(3-1d에서 미룬 것) | 커서 이동, 타인 원장 비노출 — 시험 6개(최신순, 캠페인 이름 이스케이프, 못 받은 포인트, 지갑 없는 계정, 관리자 화면의 캠페인 이름, 권한 포함), 변형 검사 4건 |
| **3-2f 광고주: 내 정보** | 닉네임·반 수정, 비밀번호 변경(S2). 현재 비밀번호 확인은 **로그인 잠금(axes)과 같은 계수**(설계 §10 "비밀번호 변경의 시도 제한", 결정 2026-10-11 — 서비스 `change_password`는 3-0a에 있으므로 이 단계 전에 넣어도 된다) | 현재 비밀번호 틀리면 거절, 변경 뒤 다른 세션 무효, 로그인·변경 화면의 실패가 합쳐 5회면 잠금(429)·잠금 중에는 맞는 비밀번호도 거절 |
| **3-3 마무리** | 접근 제어 전수(관리자↔광고주 상호 차단, 익명 리다이렉트), 보안 헤더·CSP 위반 없음, 접근성 기본(레이블·키보드·대비), 모바일 폭, 브라우저 확인(캡처, **JS를 끈 상태로도 주요 흐름**), 위협 모델 **T43(콘솔 뷰)·T44(관리자 동작)** 연결(T38~T40은 2-8·2-9·2-10, T41·T42는 Step 4가 사용), **외부 검토(`00d3067`) 남은 P3 두 건**(구간 정합 manifest 내보내기의 메모리, 모니터링 DB 정렬·쪽 나누기 — §10, 결정 2026-10-11 사용자), 종료 점검표. [3-3a·3-3b `38647b9`] 접근 제어 전수 시험(`tests/test_access_sweep.py`): 모든 화면 경로를 실제 값으로 채워 역할마다 GET·POST — 광고주 화면은 익명이면 로그인으로·관리자는 403, 관리자 화면은 익명·광고주 모두 404. 화면 전수 점검 시험(`tests/test_screens_quality.py`): 모든 화면의 보안 헤더, CSP 위반 마크업(인라인 스크립트·`style`·`on` 속성), 접근성 기본(`lang`·대체 글·입력 이름표·버튼 이름·`main`), 디자인 토큰 대비(WCAG AA, 두 테마). [외부 검토 `e781f20` P3 `de77684`] 점검할 화면 목록은 광고주·운영 경로를 모두 실제 값으로 GET 해 HTML 화면이 목록에 없으면 실패하고(`test_no_console_or_operator_screen_is_left_out`), 관리자 사이트는 등록된 모든 모델의 목록·상세와 본인 비밀번호 변경·대상 비밀번호 초기화를 등록에서 만든다(전에는 손으로 적은 일부 화면). 정상 GET으로는 나오지 않는 화면(키 발급·로그인 잠금·가입 제한·오류)은 `e781f20`. 라이트 테마 `--muted`를 `#5f6673`으로(오류 배경 위 대비가 4.23으로 부족했다). [3-3c `526046d`] Chrome으로 화면을 점검해 찾은 것: ① 광고 만들기의 칸에서 Enter가 숨긴 "단위 보기"를 눌러 고른 이미지를 말없이 잃었다 → 첫 제출 버튼을 숨긴 "집행"으로(설계 §10 D3-1 보충) ② 이미지 미리보기의 `hidden`이 `display:block`에 져 깨진 그림이 보였다(`[hidden]` 규칙) ③ 고를 수 없는 게재 위치는 흐리게, 단위를 고르면 안내를 숨김, 그림이 아닌 파일은 미리보기를 숨김 ④ 운영 화면의 넓은 표가 페이지를 넘겼다(가로 스크롤) ⑤ 광고그룹의 이미지 교체 폼을 소재마다 따로(한 소재의 거절 사유가 모든 소재 아래에 붙고 이름표 `id`가 겹쳤다) ⑥ 매체 키 교체에 확인 창(즉시 만료면 그 키를 쓰는 매체 서버가 바로 인증 실패) ⑦ 같은 화면에 있는 폼끼리 `id`가 겹침(키 발급·교체, 광고그룹 이름·위치) ⑧ 비밀번호 칸 `autocomplete`, 입찰 충돌 문구를 다른 충돌과 같게. 화면 점검 시험에 비밀번호 `autocomplete`·겹친 `id` 검사를 더함. [3-3d `ca2572c`] 모니터링의 DB 정렬·쪽 나누기(P3-4 2단계, §8.1.2 S5) — 시험 `test_the_latest_of_several_creatives_counts`·`test_a_page_reads_only_its_own_campaigns`·`test_pages_split_one_order_without_overlap`. [3-3e `6654077`] 구간 manifest 내보내기를 창 단위로(P3-3 — 계획과 다른 점은 §10 "외부 검토(`00d3067`) 남은 P3" ①) — 시험 `WindowedSummaryTests` 4개(`test_the_source_hop_matches_summarizing_everything_at_once`·`test_the_outbox_hop_matches_summarizing_everything_at_once`·`test_it_reads_only_closed_windows_after_since_one_window_and_kind_at_a_time`·`test_unsent_counts_read_only_the_unsent_rows`)와 `test_several_windows_agree_and_only_the_range_is_read`. 공개 API: `events.api`에서 `outbox_documents`·`mongo_documents`를 없애고 `summarize_windows`·`table_stream`·`outbox_streams`·`mongo_streams`를 더함, `unsent_counts(size)`는 DB를 직접 읽음. `records.api`는 `source_documents` → `source_streams`(`expected_events`는 부하 검사기의 전수 대조용으로 남음). `billing.api`에 `charge_entries_for`(반응 멱등 키로 원장 과금 줄). 외부 검토(`e781f20`) P2 `5e8fa8c`에서 `records.api.unresolved_charges`·`billing.api.charge_refs_after`(원장 과금 줄을 ID 순으로 한 묶음씩)를 더함 — 창에 놓을 수 없는 과금 원장 줄을 세어 `checkpoint.unresolved_charges`에 적고 0보다 크면 내보내기·`verify_hops`가 실패(설계 §6.3a). [종료 점검 `89c8a38`] **JS 없는 주요 흐름 — HTML 폼 기반 서버 통합 시험**(브라우저가 아니다: 서버가 그린 HTML의 폼을 HTMLParser로 읽어 JS 없는 브라우저가 보낼 것만 시험 클라이언트로 냄 — 가입·로그인·광고 만들기의 단위 고르기·미리보기·집행·캠페인 수정·새 입찰·관리자 중단·재검토 요청·해제·포인트, 꺼진 칸·없는 칸·파일을 못 보내는 폼은 보낼 수 없음, CSRF 검사 — `tests/test_no_js_journey.py`, 문구 `de77684`). **실제 브라우저로 본 범위**: 3-3c Chrome 점검(`526046d`), 외부 검토가 Chrome에서 앱 스크립트를 막은 상태로 단위 보기 → 미리보기 → 집행 → 캠페인 수정 → 새 입찰까지 확인, **C6 규칙 ↔ 서비스 대조**(값 목록·금액 상한·칸 길이를 계약 파일에서 읽어 서비스에 직접 — `tests/test_console_contract_rules.py`). 대조에서 찾은 것: 비밀번호 최대 128자가 화면 폼에만 있어 서비스·서버 명령은 더 긴 비밀번호를 받았다 → 비밀번호 검증기 `MaximumLengthValidator`(`PASSWORD_MAX_LENGTH`, 설계 §10 "비밀번호") | 브라우저로 주요 흐름 확인, `scripts/check.sh` 통과, 종료 점검표 — 접근 제어·화면 전수 시험(`38647b9`, `e781f20`, `de77684`), Chrome 점검과 회귀 시험 `test_enter_in_a_field_creates_instead_of_redrawing`·`test_each_creative_has_its_own_image_form`(`526046d`), JS 없는 흐름·C6 대조(`89c8a38`), 외부 검토(`e781f20`) 보완 `5e8fa8c`(창에 놓을 수 없는 과금 원장 줄은 내보내기·대조 실패)·`de77684`(화면 점검 빠뜨림 방지), 재검토(`5e8fa8c`) 보완 `13f3bc2`(과금 키는 표준 표기일 때만 그 반응의 키, 반응 조회는 정확한 쌍만) |

각 단계의 공통 완료 조건: ① 서비스 `api`만 호출(경계 테스트) ② 다른 광고주/권한 없는 역할 접근 테스트 ③ XSS·CSRF 회귀 테스트 ④ 감사 로그가 필요한 동작은 감사 확인 ⑤ 변형 검사 ⑥ 위협 모델 행 ⑦ `scripts/check.sh` 통과 후 커밋.

### 8.1.4 착수 전에 정한 것 [확정 2026-10-11, 사용자 — 기록은 설계 §10 "Step 3 화면 결정"]

| # | 질문 | 정한 값 | 이유 |
|---|---|---|---|
| D3-1 | 화면에 JS를 쓰나 | **조정**: JS 없이 동작하는 것이 기본(폼 제출·링크), 필요한 곳에만 **작은 JS를 덧붙인다** — 규칙 셋(§8.1.1). MVP에서 붙이는 곳: 광고 만들기의 과금 단위별 위치 거르기, 소재 이미지 미리보기, 제목·이름 글자 수, 되돌릴 수 없는 동작(캠페인 종료·광고 중단 등)의 확인 창. 모두 규칙이 없고 서버가 다시 검증한다 | CSP를 바꾸지 않고 편의만 더한다. 규칙 셋으로 나중의 화면 교체 비용을 키우지 않는다 |
| D3-2 | 차트 | **서버가 만든 인라인 SVG**(라이브러리 없음), 옆에 같은 값의 표(접근성) | CDN·인라인 스크립트 금지, 의존성 0 |
| D3-3 | 광고 만들기 형태 | **단계 제목이 있는 한 페이지 폼 + 원자적 `create_ad`**. 위저드(다중 페이지·초안 저장)는 하지 않는다 | 초안 저장 상태·고아 객체·중복 제출 위험이 없다 |
| D3-4 | 알림 임계값 | [확정 2026-10-09] 두 단계: `balance_low`(경고) = 잔액 < 활성 입찰의 **최대** 적용 금액, `balance_insufficient`(심각) = 잔액 < **최소** 적용 금액. 설정값으로 최소 기준 포인트 추가 가능 | 숫자 임의 기준보다 "지금 노출이 안 되는가"로 정의 |
| D3-5 | 대시보드 기본 기간 | **최근 7일**(예산 일 경계), 비교는 바로 앞 7일. **오늘 포함·오늘 칸에 "집계 중" 표시**(구현 세션 제안)로 **우선 진행**한다 — 통합 시험에서 개발자가 직접 써 보고 바꿀지 다시 정한다(사용자, 2026-10-11) | C6 `previous_totals`와 일치 |
| D3-6 | 관리자 화면을 어디에 | **Django admin 안**(읽기 전용 모델 + 서비스를 부르는 전용 페이지), 코드는 L4 `console/operator/` | 설계 §5.2 확정, 인증·권한·감사 재사용 |

**재검토 조건**: 통합 시험·실사용에서 더 즉각적인 화면 요구가 크게 나오면 JS를 계속 덧붙이지 않고 설계 §6.6의 길(C6 콘솔 API 구현 + 프론트 분리)로 간다. 서비스가 이미 C6 규칙을 지키므로 화면만 바뀐다. D3-3을 위저드로, D3-6을 별도 관리자 화면으로 바꾸는 것도 콘솔 층 작업이 크다(서비스는 그대로).

**하지 않는 것(V1)**: 타겟팅 화면, CSV·엑셀 내보내기, 충전 버튼(C5), 알림 저장·이메일, 다국어, 프론트 분리(C6 JSON 구현), 실시간 갱신.

### 8.1.5 위험과 대응

| 위험 | 대응 |
|---|---|
| 뷰에 규칙이 슬금슬금 들어간다 | 경계 테스트(import 금지)와 리뷰 체크리스트, 규칙이 필요하면 서비스를 먼저 만든다 |
| 화면이 많아 일정이 늘어짐 | 3-1과 3-2를 병행 가능한 묶음으로 나눔(각 단계가 독립 커밋). 3-2c·3-2d(가장 큼)는 단계별 서비스가 이미 있어 화면 작업 위주 |
| 광고주 입력의 XSS·피싱 링크 | 자동 이스케이프 테스트(`<script>`·따옴표·유니코드), `https`만 링크, `noopener`, 관리자 화면의 도메인 강조 |
| 이미지 경로로 타인 소재 노출 | 소유 확인 후에만 내려 주고 다른 광고주·익명은 404(S4 테스트) |
| 중복 제출로 캠페인이 둘 | 요청 키를 결과 행에 같은 트랜잭션으로(유일 제약, §8.1.1) + PRG + 서비스 이름 중복 규칙 |
| 대시보드 집계가 느려짐 | 소유·기간으로 먼저 좁히고(인덱스 `status, received_at`·`decision_id, type`), 150명 규모는 단순 집계로 충분. 필요해지면 일별 요약 테이블(파생값, 재계산 명령)을 둔다 |

### 8.1.6 열린 항목 (Step 3 진행을 막지 않음)

- **HTTP/HTTPS 배포** [사용자 결정 대기, 설계 §7-14]: 운영 설정은 HTTPS 전용(Secure 쿠키·HTTPS 리다이렉트·HSTS)이라 HTTP로 배포하면 콘솔 로그인이 되지 않는다. 대안 A(콘솔은 HTTPS, 매체 API만 내부망 HTTP)·B(시연용 HTTP, 접속 제한)·C(Frontend에 TLS 종단, 앱 코드 변경 없음 — 환경값 `BEHIND_TLS_PROXY`). 개발·시험(dev 설정)은 영향이 없다.

### 8.1.7 Step 3 종료 점검표

- [x] 3-0~3-3 구현, 커밋마다 `scripts/check.sh` 통과(구현 세션 보고 — 마지막 수치 `e781f20` 시점 시험 1277개)
- [x] **콘솔 뷰에 규칙 없음**(설계 §6.6): 콘솔은 서비스 `api`만 부르고 `django.db`·`engine`·모델 매니저를 쓰지 않는다(경계 시험 `tests/boundaries/test_console_rules.py`, 3-0c). 화면에 필요한 서비스는 §8.1.2 S1~S9로 보강했다
- [x] **관리자 화면(3-1a~3-1d)**: 매체·위치·키, 입찰 정책(일괄 포함), 모니터링·중단·재검토, 광고주·포인트. 모델 직접 편집은 읽기 전용, 쓰기는 서비스를 부르는 운영 화면으로만(`<ADMIN_URL_PATH>operator/`, 관리자가 아니면 404). 사용자 관리는 프로필·비밀번호 초기화만(설계 §10 "광고주 비활성화는 송출도 멈춘다")
- [x] **광고주 화면(3-2a~3-2f)**: 대시보드·알림, 캠페인, 광고 만들기(한 페이지 폼 + 원자적 `create_ad`), 광고그룹 상세, 포인트, 내 정보·비밀번호 변경(로그인과 같은 시도 제한)
- [x] **두 번·겹쳐 내도 한 번만, 옛 폼은 덮지 않음**: 두 번 하면 안 되는 동작은 결과 행에 같은 트랜잭션으로 저장하는 요청 키(매체 키 발급·교체, 포인트 조정, 광고 만들기 — §8.1.1), 수정 폼은 화면이 본 값과 대조(`expected_updated_at`·`expected_version`), 쓰기는 광고주 → 캠페인 → 광고그룹·소재 순서로 잠근다(설계 §10 "캠페인 행 잠금 규약")
- [x] **접근 제어 전수**(3-3a `38647b9`): URL 설정 전체(정규식 경로 제외)를 실제 값으로 채워 역할마다 GET·POST — 광고주 화면은 익명이면 로그인으로·관리자는 403, 관리자 화면은 익명·광고주 모두 404
- [x] **화면 전수 점검**(3-3b `38647b9`, `e781f20`, `de77684`): 모든 화면(정상 GET 화면과 키 발급·로그인 잠금·가입 제한·오류 화면)의 보안 헤더, CSP 위반 마크업 없음, 접근성 기본, 디자인 토큰 대비(WCAG AA). 광고주·운영 경로를 모두 GET 해 빠뜨리면 실패, 관리자 사이트는 등록된 모든 모델
- [x] **JS 없이 주요 흐름**(D3-1): HTML 폼 기반 서버 통합 시험(`89c8a38`, 브라우저가 아니다). **실제 브라우저**: 3-3c Chrome 점검(`526046d`, 8건 수정), 외부 검토가 Chrome에서 앱 스크립트를 막고 단위 보기 → 미리보기 → 집행 → 캠페인 수정 → 새 입찰 확인
- [x] **C6 규칙 ↔ 서비스 대조**(`89c8a38`): 값 목록·금액 상한·칸 길이. 찾은 것: 비밀번호 최대 128자 → 비밀번호 검증기(비대화형 `createsuperuser`는 Django가 검증기를 돌리지 않음 — 코드로 막지 않고 문서에 남김, 사용자 결정 2026-10-12)
- [x] **미뤄 둔 P3 두 건**(외부 검토 `00d3067`, 사용자 결정 2026-10-11): 모니터링 DB 정렬·쪽 나누기(3-3d `ca2572c`), 구간 manifest 창 단위 읽기(3-3e `6654077`, 보완 `5e8fa8c`·`13f3bc2` — 창에 놓을 수 없는 과금 원장 줄은 세어 내보내기·대조를 실패로)
- [x] `threat-model.md` 갱신: T43(콘솔 뷰, ⑩~⑭까지), T44(관리자 동작, ⑥까지), T42 ⑧(3-3e), T2·T40 인용 보강
- [x] 설계 §10에 Step 3 결정 반영("Step 3 화면 결정", "비밀번호 변경의 시도 제한", "로그인 잠금 기록 관리", "광고주 비활성화는 송출도 멈춘다", "캠페인 행 잠금 규약", "비밀번호"), DRD 갱신(0.25~0.31), C6 갱신(`expected_updated_at`, 광고그룹·소재 응답 `updated_at`), 진행 상태 표(§10) 갱신
- [x] **외부 검토 완료**(`38647b9..13f3bc2`, 3-1~3-2의 단계별 외부 검토는 §10 진행 기록)
- [ ] **사람의 일 — HTTP/HTTPS 배포**(설계 §7-14, §8.1.6): 운영 설정은 HTTPS 전용이라 HTTP로 배포하면 콘솔 로그인이 되지 않는다. 대안 A·B·C 중 결정

**검증 범위 — 승인 검토에서 다시 재지 않은 것**: 실제 브라우저, 150 동시 전체 부하, 장애·failover, 다중 웹 워커, 장시간 메모리 증가, 실제 플랫폼 연동, 질의 수 10·38·26, 기본 청크 2,000에서의 대규모 RSS. 이 가운데 150 동시 부하와 클러스터는 구현 세션이 `89c8a38` 시점에 `cluster_check.sh`로 통과시켰다.

---

## 8.2 Step 4-4 코드 정리 계획 (리팩터링 2차 후속, 2026-10-10 작성, 완료 2026-10-11)

**입력**: 리팩터링 2차(`c4a6b63`~`5666946`, 동작 변경 없음)를 하며 찾았지만, 동작이 바뀌거나 범위가 커서 리팩터링에서 고치지 않은 것들이다(리팩터링 세션 보고, 위치는 `5666946` 기준). 기능을 더하지 않는다. 다만 아래 단계에는 **동작이 바뀌는 것이 있으므로** 바뀌는 점을 단계마다 적고 시험으로 고정한다(리팩터링 세션이 아니라 구현 세션의 일).

### 8.2.1 진행 기준 (모든 단계 공통)

1. 바꿀 동작에 시험이 없으면 **특성 시험을 먼저** 넣고, 일부러 고장 내 실제로 잡는지 확인한다(변형 검사).
2. 동작이 바뀌는 항목은 바뀌는 점을 이 표에 적고 시험으로 고정한다. 바뀌지 않아야 하는 항목은 기존 시험이 그대로 통과해야 한다.
3. 단계마다 `scripts/check.sh` 전체를 돌린다. `events`·`records`의 처리 경로를 건드리면 **150 동시 부하 시험**, 상시 루프를 건드리면 **장애 시험**(단일 노드 5개, 해당하면 클러스터)까지 돌린다.
4. 질의 수 기준선: 결정 10 · 반응 38 · 클릭 26. 늘면 안 된다.
5. 한 단계 = 한 커밋. 한 단계가 다른 단계의 변경에 기대지 않게 순서를 지킨다(권하는 순서 = 아래 표의 순서).

### 8.2.2 단계 (7단계 + 선택 1, 리팩터링 세션 검토 반영)

진행 순서: **4-4a → 4-4b → 4-4c → 4-4d → 4-4i → 4-4h → 4-4k**. 4-4e는 선택이다. 처음 계획의 4-4f·4-4g(상시 루프 공용화)와 4-4j(`Counter`)는 빼고 §8.2.4로 옮겼다.

| 단계 | 대상(위치) | 할 일 | 바뀌는 동작 | 완료 증거 |
|---|---|---|---|---|
| **4-4a 청크 크기 입구 검사** (A1) | `events/relay.py` `missing_event_ids(chunk=1000)`, `records/backfill.py` `backfill(chunk=500)` | 두 함수 입구에서 `chunk >= 1`을 명시적으로 검사하고 아니면 `ValueError`(R6). 리팩터링 전에는 음수면 빈 루프라 **누락 점검은 "누락 없음", 백필은 "아무것도 안 하고 성공"**으로 끝났고, 지금은 `itertools.batched`가 우연히 오류를 낸다 — 이 동작을 계약으로 굳힌다("모르면 없다고 답하지 않는다", `missing_event_ids` 설명과 같은 원칙) | 지금 동작을 명시적으로 고정(오류 문구만 바뀜). 이렇게 부르는 곳은 없다 — `backfill_events`는 `--chunk ≥ 1`을 이미 검사하고 나머지는 기본값을 쓴다 | 두 함수를 직접 부를 때 0·음수면 오류인 시험, 검사를 빼면 실패(변형 검사) |
| **4-4b 판정 근거 쓰기 경계 시험을 AST로** (B2) | `tests/boundaries/test_judgment_scope.py`(정규식 `\bbasis\s*=(?!=)`), `records/hops.py` `expected_events`의 `**{"basis": r.basis}` | 경계 시험을 AST 기반으로 바꿔 **실제 쓰기만** 찾는다. **쓰기의 정의** [넓힘 2026-10-10, 외부 검토(Step 4-4) P2 `6b563cf`]: ① `basis=` 키워드나 `**{"basis": …}` 풀어 넘기기를 받는 `update`·`create`·`get_or_create`·`update_or_create`·`bulk_create` 호출과 `Reaction(basis=…)` 생성 ② `get_or_create`·`update_or_create`의 `defaults`·`create_defaults` dict에 든 `"basis"` 키 ③ `bulk_update`의 `fields`, `bulk_create`의 `update_fields` 목록에 든 `"basis"` ④ `.basis =`·`.basis +=` 대입. ②·③은 키워드로 넘기든 위치 인자로 넘기든 같은 인자로 본다(Django `QuerySet` 시그니처 순서). **한계**: 정적 검사라 실행 중에 만든 dict를 넘기는 `update(**fields)`는 보지 못한다. 쿼리셋이 `Reaction`인지는 정적으로 가리기 어려우므로 **이 꼴의 쓰기가 `records/processing.py`에만 있는지**를 규칙으로 한다(모델 정의·마이그레이션 제외). 그다음 `hops.py`의 우회 모양을 평범한 `basis=r.basis`로 돌린다(경계 시험이 코드를 어색하게 만든 사례) | 앱 동작 없음. 경계 시험(보안 태그)의 판정 기준이 "글자"에서 "실제 쓰기"로 바뀐다 | 다른 파일에 위 꼴의 쓰기(`update(basis=…)`·`bulk_update(…, ["basis"])`·`.basis =`)를 넣으면 실패, 읽기용 키워드 인자 `basis=r.basis`는 통과(변형 검사). 쓰기·읽기 꼴마다 소스 조각을 넣어 보는 시험(`BasisWriteFormsTests`: 위치 인자 `defaults`·`create_defaults`·`update_fields`, `bulk_create`의 두 번째 위치 인자 `batch_size`는 읽기). 같은 파일의 다른 구조 검사(`scoped_reactions` 입구 하나, `gather`·`display_signal` 호출)는 그대로 통과 |
| **4-4c 원장 멱등 키 형식 한 쌍** (B4) | 만들기 `records/processing.py` `reaction_ref()`, 다시 만들기 `records/hops.py:31-32`(f-string), 해석 `records/backfill.py` `_parse_ref()` | `<매체>:<reaction_id>`를 만들고 해석하는 한 쌍을 한 곳에 두고 나머지 두 곳이 쓴다(R3: 형식 도우미만 공유, 기대 이벤트 매핑은 독립). 먼저 `_parse_ref`의 잘못된 입력 처리(구분자 없음·UUID 아님)를 특성 시험으로 고정 | 없음(형식 같음) | 만들기 → 해석 왕복 시험, 잘못된 키는 지금처럼 해석 불가, 질의 수 그대로 |
| **4-4d 구간 계약 값 한 곳** (B3) | 대상은 **구간 계약 값 세 가지뿐**: ① 구간 줄 모양의 버전(`export_hop_manifests`의 `SCHEMA_VERSION` ↔ `hopcheck.SUPPORTED_SCHEMA_VERSION`) ② 창 이름 ↔ 크기 표 두 벌(`events/hops.py` `WINDOWS` {day, hour} ↔ `events/hopcheck.py` `WINDOW_SIZES` {utc-day, utc-hour})과 명령의 `f"utc-{window}"` 이어 붙이기 ③ 시각 형식(`%Y-%m-%dT%H:%M:%SZ` 해석·출력 4곳 `_z`·`_time`·`_parse`·`strftime`, 밀리초 형식) | 세 가지를 `events/hops.py` 한 곳에 두고 `events.api`로 노출한다(결정 R2. 설계의 의존 규칙 R2에 따라 `records` 명령은 `events.api`만 쓴다). 내보내는 쪽(`export_hop_manifests`)과 대조하는 쪽(`hopcheck`)이 같은 값을 쓴다. `verify_hops`·`export_integrity`·`backfill_events`의 `SCHEMA_VERSION`은 대상이 아니다(§8.2.4 C6) | 값을 그대로 옮기므로 없음 | 창 옵션마다 "내보낸 선언을 대조 쪽이 읽는다" 왕복 시험, 기존 구간 시험 그대로 통과 |
| **4-4i 원자적 게시 단계 하나로** (B6) | `events/ndjson.py` `write()`(데이터 파일)와 `_publish()`(manifest·세대 사본) — 같은 "임시 파일 → fsync → `os.replace` → 폴더 fsync"가 두 벌. 데이터 파일은 쓰면서 해시를 계산해 그 해시로 최종 이름을 정하므로 `_publish`를 그대로 못 씀 | **방법은 하나**: "교체 + 폴더 동기화" 단계만 함수로 빼서(예: `_replace_durably(tmp, final)`) `write()`와 `_publish()`가 같이 쓴다. 콜백 방식은 쓰지 않는다 — 10줄 남짓의 중복을 없애려고 원자성 코드에 추상화 한 겹을 더하게 된다 | 없어야 한다. 외부 검토가 여러 번 본 원자성이라 단계마다 중간 실패를 넣어 확인한다 | 기존 원자성 시험(쓰다 죽음·manifest 교체 실패·동시 게시·내구성 순서) 통과 + 각 단계(쓰기·동기화·교체·폴더 동기화)에 실패를 넣는 변형 검사 |
| **4-4h MongoDB 오류 문구 도우미** (B5, 우선순위 낮음) | 같은 꼴 `{type(e).__name__}: {str(e)[:N]}` 9곳(N이 200·300으로 섞임): 명령 6곳(`backfill_events.py:35`·`export_integrity.py:35`·`export_hop_manifests.py:50`·`relay_events.py:61`·`relay_events.py:65`·`ensure_event_store.py:15`)과 `events/store.py`의 상태 확인 결과 문구 3곳(연결·쓰기 권한·컬렉션, 90·105·118행) | `events`에 도우미 하나를 두고 `events.api`로 노출, 아홉 곳이 쓴다. 자르는 길이는 200자로 통일(R4). 도우미가 줄여 주는 것은 위 한 조각뿐이라 우선순위는 낮다 | 오류 문구(stderr·상태 확인 결과)가 조금 바뀐다(`ensure_event_store`의 300자 → 200자) | 도우미 단위 시험(형식·길이), 각 명령이 MongoDB 오류에서 여전히 비정상 종료하고 오류 종류 이름을 남김, `check_event_store` 결과 시험 그대로 통과 |
| **4-4k 시험 스크립트의 `docker()` 하나로** (B8, 마지막) | `scripts/mongo_temp_rs.py:21`(시간 제한 120초), `scripts/failure_test.py:65`(180초), `scripts/mysql_cluster.py:27`(300초, `input` 인자) | `scripts/`에 공용 도우미를 두고 시간 제한을 인자로 받는다. 호출마다 지금 값을 넘긴다(R5) | 시험 하네스만 바뀐다(앱 없음) | 장애 시험(단일 노드·클러스터)과 `cluster_check.sh`가 그대로 통과 |
| *4-4e 상시 명령 특성 시험 (선택)* | `process_reactions`, `relay_events` | 공용 루프를 만들지 않으므로(§8.2.4 C4), 두 명령의 동작 중 **시험이 없는 것만** 특성 시험으로 남긴다. 예: 중계의 점점 길게 쉬기(최대 30초), 충돌 시 멈춤 | 없음(시험만) | 변형 검사로 각 시험이 실제로 잡음을 확인, 장애 시험 그대로 통과 |

### 8.2.3 정한 것 [확정 2026-10-10 — 리팩터링 세션 검토 반영, 사용자 전달]

| # | 질문 | 정한 값 | 이유 |
|---|---|---|---|
| ~~R1~~ | ~~상시 루프의 재시도 정책을 통일하나~~ | 삭제 — 4-4f·g를 빼서 정할 필요가 없다(§8.2.4 C4) | — |
| R2 | 구간 계약 값과 파일 종류별 `schema_version` (4-4d) | **구간 계약 값(줄 버전, 창 이름 ↔ 크기, 시각 형식)만 `events/hops.py` 한 곳에 두고 `events.api`로 노출한다.** 다른 파일 종류(`ledger_check`·`event_gaps`·`event_delivery`·`backfill_result`·`hop_report`)의 버전은 각 명령에 그대로 둔다. 값은 모두 1 그대로 | 각 버전은 한 곳에서만 정의된 서로 다른 계약이라 중복이 아니다. 구간 모듈로 모으면 소유가 흐려진다 |
| R3 | 원장 멱등 키 형식을 `records/hops.py`도 공유하나 (4-4c) | **형식 도우미(만들기·해석)만 공유**하고, 기대 이벤트를 만드는 매핑은 독립으로 둔다 | 키 형식은 저장된 데이터의 형식(원장 `reaction_ref`)이라 검증 대상이 아니다. 독립 검증이 지키려는 것은 원본 → 이벤트 매핑이다(C1) |
| R4 | MongoDB 오류 문구를 자르는 길이 (4-4h) | **200자**(`events/store.py` 3곳 포함) | 아홉 곳 중 여덟이 이미 200자다 |
| R5 | `docker()` 시간 제한 (4-4k) | **호출마다 지금 값을 인자로 넘긴다**(120·180·300초, 기본값 하나로 바꾸지 않음) | 클러스터 기동처럼 오래 걸리는 호출과 짧은 호출이 섞여 있다 |
| R6 | 청크 검사의 오류 형태 (4-4a) | **`ValueError`**(무엇이 잘못됐는지 적은 문구) | 지금 동작과 같은 종류의 오류를 명시적으로 낸다 |

### 8.2.4 정리하지 않는 것 (일부러 남기는 중복)

| 중복 | 위치 | 남기는 이유 |
|---|---|---|
| C1 결정 스냅샷 → 이벤트 매핑 두 벌 | `records/services.py` `_record_decision_event`, `records/hops.py` `expected_events` | 원본 행에서 기대 이벤트를 **따로** 만들어 라이브 경로의 매핑 결함을 드러내는 독립 검증 경로다. 합치면 검증력이 사라진다(R3과 같은 이유로 키 형식만 공유) |
| C2 `_now` 다섯 벌, `_audit` 세 벌 | `masters`·`campaigns`·`billing`·`records`(두 곳) | 시험이 `records.services._now`·`records.processing._now`를 패치한다. `_audit`은 두 줄짜리 감싸개라 합쳐도 호출부만 바뀐다 |
| C3 dev/prod 설정의 비슷한 블록 | `config/settings/dev.py`·`prod.py` | 환경별 필수 여부가 달라 명시적인 쪽이 낫다 |
| C4 두 상시 루프(옵션 검증·SIGTERM·주기 쉬기) | `records/management/commands/process_reactions.py`, `events/management/commands/relay_events.py` | 실제로 같은 부분은 10줄 남짓이고, 실패 처리·출력·재시도는 일부러 다르다. 합치려면 정책을 인자로 받는 공용 실행기(부르는 곳 둘)를 `foundation`에 새로 만들어야 하고, 장애 시험이 지키는 "복구 뒤 상시 프로세스만으로 대기열 비우기" 보장을 건드린다. 시험이 없는 동작은 4-4e(선택)로 고정만 한다 |
| C5 수동 카운트 `d[k] = d.get(k, 0) + 1` | `events/hops.py`, `verify_hops.py`, `records/integrity.py` | `Counter`로 바꿔도 줄이 줄지 않는다. `integrity`의 `stats`는 호출한 쪽이 넘긴 dict를 채우는 약속이고, 출력에는 `dict()`를 씌워야 한다 |
| C6 파일 종류별 `SCHEMA_VERSION` | `verify_hops`(`hop_report`)·`export_integrity`(`ledger_check`·`event_gaps`·`event_delivery`)·`backfill_events`(`backfill_result`). `export_hop_manifests`의 `SCHEMA_VERSION`은 구간 줄 버전 하나뿐이라 대상이 아니다 — 4-4d에서 `events/hops.py`로 옮기고 이 명령에는 자기 상수가 남지 않는다 | 서로 다른 파일의 계약을 각 명령이 한 곳에서 정의한다(R2) |

### 8.2.5 보류 (중복이 아니라 성능, 리팩터링 1차에서 미룸)

| 항목 | 위치 | 보류 이유 | 다시 볼 때 |
|---|---|---|---|
| ~~광고그룹 목록 N+1~~ | `campaigns/services.py` `list_ad_groups` | 부르는 화면이 아직 없다 — Step 3 화면은 `ad_group_effects`(질의 3번)를 써서 지금도 부르는 화면이 없다(시험에서만) | **해소** — 3-4g `24fe4dd`(§8.3, 결정 2026-10-12 사용자): 현재 입찰은 하위 질의 + `in_bulk`, 게재 위치는 한 번에 읽어 광고그룹 수와 무관(그룹 3개에서 질의 8 → 4) |
| 지갑별 원장 질의 N+1 | `billing/services.py` `_check_wallets` | 한 번에 읽으면 원장 전체가 메모리에 올라간다(교환 관계) | 지갑 수가 늘어 정합성 점검 시간이 문제가 될 때 |
| 처리 직후 같은 반응 재조회 | `records/processing.py` `_wake_dependents` | 동시성 핵심 경로이고 반응당 질의 1회다 | 반응 처리량이 병목으로 측정될 때 |
| ~~키별 UPDATE~~ | `masters/services.py` `rotate_media_key` | 매체당 키가 1~2개라 이득이 없다 | **해소** — `d2e2ee5`(외부 검토 3-1d 보완)이 정확성 문제 때문에 매체 행을 잠그고 조건부 UPDATE 한 번으로 바꿨다(교체의 만료 조건은 UPDATE 안에서) |

### 8.2.6 후속 변경 후보 (4-4 구현 중 발견, 구현 세션 보고)

| 항목 | 위치 | 지금 | 다시 볼 때 |
|---|---|---|---|
| 준비 대기의 시간 제한 | `scripts/failure_test.py` `wait_ready` | 전체 대기 시간(기본 180초)은 있지만 한 번의 확인 호출(`docker exec … mysqladmin ping`)에는 시간 제한이 없어, 그 호출이 멈추면 전체 대기 시간을 넘길 수 있다. 4-4k(`docker()` 하나로)는 호출마다 지금 값을 넘기는 것까지만 했다(R5) | 장애 시험이 준비 대기에서 멈추는 일이 보이거나 시험 하네스를 다시 고칠 때. 개별 호출 시간 제한과 전체 대기 시간을 같이 정한다(시험 하네스만, 앱 없음) |

---

## 8.3 Step 3-4 코드 정리 계획 (리팩터링 3차, 2026-10-12 작성, 완료 2026-10-12)

**입력**: Step 4-4 정리 뒤(`4de457f`)부터 Step 3 승인(`4fcb2ef`)까지의 코드 — 커밋 59개, 140개 파일(+7,971/−328). 리팩터링 세션 보고이고, 행 번호는 `4fcb2ef` 기준이다. **구조를 고칠 문제는 없다.** 반복되는 코드 5묶음, 쓰이지 않는 코드 3곳, 표기 2곳을 정리하고, 동작이 바뀌는 성능 정리 둘(화면의 중복 읽기 B1, 광고그룹 목록 N+1)은 3-4g 한 단계로 따로 둔다.

### 8.3.1 진행 기준 (모든 단계 공통)

1. 하위 층 → 상위 층 순서로, **한 단계 = 한 커밋**. 단계마다 `scripts/check.sh`를 통과시킨다(`claude` 환경 파이썬, 다른 세션과 시험 DB가 겹치지 않게 `DB_NAME`을 따로).
2. **동작 불변**(3-4g 제외): 응답 코드·문구·리다이렉트·감사 로그·잠금 순서·질의 수가 그대로다. 결정 서빙 경로(`candidate_facts_for_slot`·`records` 판정)는 건드리지 않는다 — 질의 수 결정 10 · 반응 38 · 클릭 26, 화면 시험의 "데이터가 늘어도 질의 수가 같다"도 그대로.
3. **시험이 패치하는 이름은 바꾸지 않는다**: 화면 모듈의 `_now`(`console.views.dashboard`·`campaigns`·`points`), `records.services._now`·`records.processing._now`, `campaigns.services._creative_view`(`test_operator_campaigns`가 `wraps`로 호출 수를 센다).
4. **경계 규칙**: `api.py`는 값 객체만 돌려주고, 콘솔은 `django.db`·`engine`·모델 매니저를 쓰지 않는다.
5. 새 시험은 모두 변형 검사로 실제로 잡는지 확인한다. 마지막에 **150 동시 부하 시험**을 한 번 돌린다.
6. 예상 규모: 3-4g를 빼고 순감 약 50줄.

### 8.3.2 단계 (8단계)

진행 순서: **3-4a → 3-4b → 3-4c → 3-4d → 3-4e → 3-4f → 3-4g → 3-4h**.

| 단계 | 대상(위치) | 할 일 | 바뀌는 동작 | 완료 증거 |
|---|---|---|---|---|
| **3-4a 시험 먼저** | 새 파일 `tests/test_service_input_contracts.py`(2차의 `test_chunk_boundaries.py`와 같은 방식) | 기준선으로 `check.sh` 시험 수를 잰다. ① **요청 키**: `masters.issue_media_key`·`masters.rotate_media_key`·`billing.adjust`·`campaigns.create_ad`에 `""`·`"x"*65`·`123`이면 `InvalidRequest`이고 `errors`가 `[{"pointer": "/request_key", "message": "1~64자 문자열이어야 합니다."}]`, `"x"*64`와 `None`은 통과. `campaigns.ad_created_by_key`는 위 세 값과 `None`에 `None`. 검증 순서도 고정 — 앞선 검증(교체의 유예 시간, 조정의 사유·금액)이 먼저 실패한다 ② **`enabled` 타입**: `update_ad_group`·`update_creative`에 `"1"`이면 `/enabled` "true 또는 false 여야 합니다." ③ **화면이 본 시각 대조**(`StaleVersion`, 409): `update_campaign`·`update_ad_group`·`update_creative`는 "다른 곳에서 먼저 바뀌었습니다. 새로 불러와 다시 수정하세요.", `replace_creative_image`는 "… 다시 바꾸세요." ④ **관리자 중단·해제**: 없는 ID와 형식이 틀린 ID 모두 `NotFound`(지금 문구 그대로). 3-4d②(소재 묶기)와 3-4f(12곳)의 대상이 기존 시험에 잡히는지 변형 검사로 확인하고, 안 잡히는 곳은 이 단계에서 시험을 더한다 | 없음(시험만) | 새 시험이 변형 검사로 잡힘 |
| **3-4b L0 foundation** | `foundation/validators.py`, `foundation/api.py`, `foundation/http.py:150-152` | `is_request_key(value)`(1~64자 문자열인지)와 `clean_request_key(value)`(`None`은 그대로, 그 밖의 틀린 값은 위와 같은 `InvalidRequest`)를 두고 `foundation.api`로 공개한다. `http.py`의 빈 줄 3개를 2개로 | 없음 — 요청 키 검증 4벌의 위치(`/request_key`)와 문구가 모두 같다 | `check.sh` 통과 |
| **3-4c L1 masters** | `masters/services.py:260-263` `_request_key`, `:285`·`:302` | `_request_key`를 지우고 `clean_request_key`로 | 없음 | `check.sh` 통과 |
| **3-4d L2 billing·campaigns** | `billing/services.py:100-101`·`:107`·`:117`, `campaigns/services.py` | **billing**: 요청 키는 `clean_request_key`로(검증 위치는 그대로), 같은 `Conflict` 문구 2벌을 모듈 상수 하나로. **campaigns**: ① 요청 키 `:644-645`는 `clean_request_key`, `:672-673`은 `is_request_key` ② 캠페인별 소재 묶기 2벌(`_MonitoringRows.__getitem__` `:387-389`, `open_review_queue` `:418-420`) → `_creatives_by_campaign(campaign_ids)` ③ 관리자의 캠페인 잠금 조회 2벌(`suspend_campaign` `:270-272`, `release_campaign` `:287-289`) → 도우미 하나 ④ 화면이 본 시각 대조 4벌(`:198-199`·`:493-494`·`:727-728`·`:753-754`) → 도우미 하나(문구는 동사만 다름) ⑤ `enabled` 타입 검사 2벌(`:498-499`·`:734-735`) → 하나 | 없음 — 질의(`select_related("ad_group")`, `created_at` 순)·질의 수(모니터링 쪽마다 4번, 대기열 2번)·잠금 순서·문구가 같다. 시험이 패치하는 `_creative_view`도 그대로 거친다 | `check.sh` 통과 |
| **3-4e L3 records** | `records/management/commands/export_hop_manifests.py:16`·`:81`·`:83`, `records/hops.py:72` | 쓰는 곳이 없는 `HOPS`를 지운다(2차 때 놓친 것). `:83` 줄 끝의 최대 상주 메모리 주석을 `peak_rss`를 출력하는 `:81`로 옮긴다. `sample += [x][:examples - len(sample)]`를 `if len(sample) < examples: sample.append(x)`로 | 없음 — `examples`가 0이거나 음수여도 결과가 같다 | `check.sh` 통과 |
| **3-4f L4 console** | `console/errors.py`, 운영 화면 `console/operator/views.py`, 광고주 화면 `console/views/ad_groups.py`·`campaigns.py` | `errors._not_shown` 마지막 조건의 튜플을 `HANDLED`로. `errors.run_action(request, call, *args, success=None, **kwargs)`를 둔다 — 실패하면 `messages.error(message_of(e))`, 성공하고 `success`가 있으면 `messages.success`, 성공 여부를 돌려준다. 이 패턴 **12곳**을 바꾼다: 운영 화면 7곳(`media_active:59`·`slot_active:82`·`key_revoke:165`·`campaign_suspend:193`·`campaign_release:204`·`review_reject:227`·`advertiser_active:261`), 광고주 화면 5곳(`ad_groups.py`의 `ad_group_enabled:101`·`creative_enabled:135`, `campaigns.py`의 `campaign_status:63`·`campaign_end:76`·`campaign_review:87`). 제외: `_issue_key:131`(성공하면 평문 키 화면을 그림), `ads.py:52`(돌려받은 값으로 분기). `ad_groups._done`은 다른 호출자가 남아 유지 | 없음 — 메시지 문구·순서와 리다이렉트가 같다. 콘솔 경계 규칙도 지킨다 | 12곳이 화면 시험에 잡힘(변형 검사, 3-4a), `check.sh` 통과 |
| **3-4g 화면의 중복 읽기(B1)와 광고그룹 목록 N+1** (의도한 동작 변화, perf) | `console/views/dashboard.py:33`, `console/queries/alerts.py:32`·`:93-96`, `console/queries/dashboard.py:11`, `console/queries/ad_groups.py:28`·`:31`, `campaigns/services.py:696` `bid_effects`, `campaigns/services.py` `list_ad_groups` | **B1** ① 대시보드 지갑: 화면이 읽은 지갑을 `alerts_for`에 넘기고 `alerts.py`의 다시 읽기를 지운다(지갑이 없으면 잔액 알림이 없는 것은 같다) ② 대시보드 캠페인 목록: 화면이 `campaigns.list_campaigns(user, now=now)`를 한 번 읽어 `top_campaigns`와 `alerts_for`에 넘긴다 ③ 광고그룹 상세: `ad_group_page`가 이미 읽은 `get_slots_with_policy` 결과를 `campaigns.bid_effects(amount, slot_ids, slots=…)`에 넘겨 다시 읽지 않는다(광고 만들기 미리보기는 지금처럼 인자 없이, 적용 금액은 그대로 `_effect` → `engine`의 `effect_of`). **N+1**(§8.2.5에서 옮김, 결정 2026-10-12 사용자) ④ `list_ad_groups`가 광고그룹마다 현재 입찰(`_current_bid`)과 게재 위치(`slot_links`)를 따로 읽는다(질의 1 + 2N) → 현재 입찰은 하위 질의(`ad_group_effects`와 같은 방식), 게재 위치는 한 번에 읽어 **광고그룹 수와 무관한 고정 횟수**로 | **질의 수**: 대시보드 −3, 광고그룹 상세 −1, `list_ad_groups`는 그룹 수와 무관. **읽는 시점**: 위젯의 잔액과 잔액 알림이, 위치 정보와 위치별 결과가 같은 읽기를 본다(지금은 `READ COMMITTED`에서 따로 읽어 경쟁이 생기면 이론상 서로 다를 수 있다). 상위 캠페인 표의 상태도 화면의 `now`로 계산된다(지금은 `top_campaigns`가 시계를 따로 읽는다). 화면 값을 정하는 규칙은 그대로이고 C6·설계에는 영향이 없다 | 대시보드 한 번에 지갑 SELECT 1번, 광고그룹 상세의 슬롯 정책 조회 1번, `list_ad_groups`의 질의 수가 그룹 수와 무관함을 고정(중복 읽기·N+1을 되살리면 실패). `test_alerts.py`의 `alerts()` 도우미가 지갑과 캠페인 목록을 넘기게 고침. 기존 "질의 수는 데이터와 무관" 시험 그대로 통과 |
| **3-4h 시험 정리** | `tests/test_dashboard.py:7`, `tests/test_operator_campaigns.py:14` | 쓰지 않는 import(`date`, `make_admin`)를 지운다 | 없음(시험만) | `check.sh` 통과 |

### 8.3.3 정한 것 [확정 2026-10-12, 사용자]

- **B1(화면의 중복 읽기)을 포함**한다. 의도한 동작 변화이므로 3-4g 한 단계로 따로 둔다.
- **광고그룹 목록 N+1(§8.2.5)도 이번에 고친다** — Step 3 화면은 `ad_group_effects`(질의 3번)를 써서 `list_ad_groups`를 부르는 화면이 없지만(시험에서만 부름), 다시 볼 조건을 미루지 않고 3-4g에 넣는다.
- **커밋은 2차와 같게**: 단계마다 하나씩, 파일을 지정해서(`-A` 금지), Claude/AI 관련 정보 없이. 형식은 `test|refactor|perf(ads-server): Step 3-4x …`.

### 8.3.4 정리하지 않는 것 (일부러 남기는 중복)

| 항목 | 이유 |
|---|---|
| 이미지 응답 3줄 2곳(`ad_groups.creative_image_file`, `operator.asset`) | `api.py`는 값 객체만 돌려주므로 `assets.api`에 응답 도우미를 둘 수 없다. 콘솔에 새 파일을 만들 만큼 크지도 않다 |
| `ProfileView`·`AdvertiserAccount` | 하나는 C6 계약 타입이다. 합치면 계약 타입에 `last_login`이 들어간다 |
| 비밀번호 확인 칸 비교 2곳, `token_urlsafe(16)` 4곳, 지갑이 없으면 `None` 2곳 | 2~4줄이라 도우미를 만들면 원래 코드보다 길어진다 |
| 라벨 필터 7개(`console_format.py`) | 반복이지만 지금처럼 단순하게 둔 것이 가장 읽기 쉽다 |
| 화면 모듈마다 있는 `_now()` | 시험이 모듈마다 패치한다 |
| `campaign_page`가 광고주의 광고그룹 결과를 모두 읽은 뒤 거름 | 질의는 3번으로 고정이고, 행 수는 광고그룹 상한(100)까지다 |
| `ponytail:` 표시가 있는 두 곳(`_MonitoringRows`, `summarize_windows`) | 한계가 적혀 있는 의도한 단순화다 |
| 시험의 `request_key` 도우미 2개 | 하나는 폼 `id`로 범위를 잘라서 동작이 다르다 |

### 8.3.5 이 계획과 함께 고친 문서

- §8.2.5 "키별 UPDATE(`rotate_media_key`) — 하지 않는다" 행: `d2e2ee5`이 정확성 문제(겹친 교체가 만료된 키를 되살림) 때문에 조건부 UPDATE 한 번으로 바꿔 **이미 해소됨**으로 표시했다.
- §8.2.5 "광고그룹 목록 N+1(`list_ad_groups`)" 행: 이번 3-4g에서 고치는 것으로 옮겼다.
- §10 진행 표에 "Step 3-4 코드 정리 계획" 행(계획).
- 리팩터링 3차 기록은 §10 "Step 3-4 코드 정리" 행에 남겼다(계획과 다른 점 포함). §8.2.5 "광고그룹 목록 N+1" 행은 `24fe4dd`로 해소 표시.

---

## 8.4 Step 6 — Step 3 이후 수정 (2026-10-12 시작)

**무엇을 담나**: Step 3 승인(2026-10-12) 뒤 연동 검토·운영·외부 검토에서 나오는 수정이다. 기능 단계(Step 3·4)를 다시 열지 않고 여기에 수정 단위로 쌓는다. 수정 하나가 **`6-N`**(생긴 순서)이고, 그 안의 단계는 `6-Na`·`6-Nb` …다. 새 수정이 생기면 8.4.2 다음에 절을 하나 더한다.

### 8.4.1 진행 기준 (모든 수정 공통)

1. 수정마다 **계기 · 결정 · 단계 · 완료 증거 · 매체 쪽 요청(있으면)**을 적는다. 결정은 설계 §10, 진행은 §10 표에 행 하나.
2. **결정은 바로, 계약은 구현 뒤에**: 사용자가 정한 것은 바로 설계 §10에 남긴다. 아직 구현되지 않은 서버 동작(새 사유 코드·판정 규칙)은 **구현이 끝난 뒤** 계약·DRD·위협 모델에 넣는다 — 계약이 없는 동작을 약속하지 않게. 그때까지 설계 §10에 "[구현 예정]"으로 표시한다.
3. **계약 버전**: 전송 형식이 그대로이고 매체에 새 요구가 생기면 부 버전(1.x, 호환)을 올리고 "변경" 절을 둔다. 호환되지 않으면 `/v2`다(설계 §10 "계약 v1.1"·"계약 v1.2").
4. 코드 단계는 Step 3-4와 같다: **한 단계 = 한 커밋**, 단계마다 `scripts/check.sh` 통과, 동작이 바뀌는 곳은 시험으로 고정, 질의 수 기준선이 바뀌면 기록한다 — **지금 기준선은 결정 10 · 반응 39 · 클릭 27**(6-1c, 2026-10-12. 그 전은 10 · 38 · 26).
5. **서버 작업은 착수 전에 사용자가 정한다.** 그 전에는 계획만 적고 "착수 결정 대기"로 둔다.

### 8.4.2 6-1 매체 연동 검토 후속 (게임 ad-bridge, 2026-10-12)

**계기**: 게임 쪽 광고 연동 모듈(ad-bridge, 게임 dev `be71bd7`)을 광고 서버 입장에서 검토했다(구현 세션, 2026-10-12). 계약 준수와 책임 범위는 문제가 없었고, 사용자가 세 가지를 정했다(2026-10-12).

| # | 결정 [확정 2026-10-12, 사용자] | 지금 반영(6-1 결정 반영) | 구현 뒤 반영 |
|---|---|---|---|
| 1 | `subject_id`는 매체가 자기 비밀로 만든 **광고 전용 가명**(다른 시스템 식별자 금지, 같은 사람은 늘 같은 값). 서버는 구별할 수 없어 계약과 연동 검토로 지킨다 | 계약 C1 1.2.0 규약 MUST·예시와 두 `subject_id` 설명, 매체용 요약, DRD 0.32(결정 표·C1 입력·반응 입력·L2, **D-5 해결**), 위협 모델 A6·T41, 설계 §10 | 없음(서버 변경 없음) |
| 2 | 반응 **401은 고친 뒤 한 번** 같은 내용으로 다시 보내도 되고, **403은 다시 보내지 않는다**. **매체 비활성화는 그 전에 만든 결정을 끝낸다**(비활성화 뒤 접수된 반응은 `REJECTED`, `media_deactivated`, 서버 클릭도 같음, 비활성화 전 접수는 늦게 판정해도 그대로) | 계약 반응 전달 규칙 5·매체용 요약, 설계 C1 반응 전달 규칙 5, 설계 §10(서버 규칙은 처음에 [구현 예정]으로 적고 6-1d에서 구현으로 바꿈) | **6-1d 완료**: 계약 1.2.0 안에서 `media_deactivated`(규칙 5의 403, "v1.2 변경" 4번, `ReactionReasonCode`)·매체용 요약, 설계 §4.7 규칙 표·§10, DRD 0.33(M5), 위협 모델 T45 |
| 3 | 반응 `GET`의 `status`·`reason_code`는 **매체 서버용**(최종 사용자에게 전달하지 않음) | 계약 `getReaction`·`ReactionReasonCode`·매체용 요약, 설계 §10 | 없음 |

**계약 버전**: 전송 형식은 그대로지만 1번의 MUST가 매체에 새 요구라 **1.1.0 → 1.2.0**(호환)으로 올리고 "v1.2 변경" 절을 두었다(문서 세션 판단, 설계 §10 "계약 v1.2"). 계약 버전을 고정한 시험은 없다(구현 세션 확인).

**단계** (서버 규칙 — 결정 2의 ③. 구현 세션 계획, **완료 2026-10-12**)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-1a `masters`** | 매체 비활성화 기록 표(매체, 비활성화 시각). `set_media_active(False)`가 **실제로 활성 → 비활성으로 바꿀 때만** 같은 트랜잭션에서 한 줄 추가. 관리자 화면은 읽기 전용. `api`에 "이 구간에 비활성화가 있었나" 조회 하나 | 마이그레이션, 감사·읽기 전용 화면 시험 갱신 | **완료 `42de743`** — `masters.MediaDeactivation`(마이그레이션 `masters/0004`, 색인 `(media, deactivated_at)`), 조건부 UPDATE라 동시에 꺼도 한 줄·이미 꺼진 매체를 다시 끄거나 켜면 기록 없음, `masters.api.first_deactivation(매체, after, until)` = (after, until] 안의 가장 이른 시각, 읽기 전용 모델 17 → 18. 시험 1,304개 |
| **6-1b `records`** | 판정 사실에 "결정 뒤, 접수 전 비활성화"를 더한다. 새 규칙 `media-period`(사유 `media_deactivated`)를 `REACTION_RULES`의 `same-media` 바로 뒤에 둔다. 판정 근거에 사용한 비활성화 시각을 기록한다 | 규칙 단위 시험. 처리 시험: 결정 → 비활성화 → 재활성화 → 노출이면 거부, 비활성화 전 접수·늦은 판정이면 인정, 재활성화 뒤 새 결정이면 인정, 서버 클릭도 같음 | **완료 `a70d769`** — 구간 (결정 시각, 접수 시각](결정과 같은 순간에 끈 것은 결정 전, 접수와 같은 순간에 끈 것은 접수 전), 기준 매체는 결정을 만든 매체(다른 매체의 보고는 `media_mismatch`가 먼저), 필수 조건(`MANDATORY_RULES`)에도 넣음, `basis` v2 → v3(`media_deactivated_at`), `set_media_active(now=)` 시각 주입. 시험 1,310개 |
| **6-1c 측정** | 질의 수 재측정(반응 경로 +1 예상), `check.sh` | 기준선 변화 기록 | **완료(커밋 없음)** — 결정 10 · 반응 39 · 클릭 27(전 10 · 38 · 26, 6-1a `42de743` 시점과 같은 측정 도구로 비교). 판정할 때 비활성화 조회 1번(반응 처리, 접수 때 바로 처리되는 클릭) |
| **6-1d 문서** | 구현 세션이 커밋 해시와 함께 따로 요청: 계약 `ReactionReasonCode`에 `media_deactivated`와 반응 판정 규칙 표, DRD 반응·매체 표, 위협 모델(매체 비활성화 우회) | 문서 반영 | **완료 (2026-10-12)** |

**검증**(구현 세션): 단계마다 `check.sh` 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, 구간 대조 `match` 12줄, `pip-audit`·`bandit` 통과. 새 시험의 변형 검사는 6-1a 6개·6-1b 10개 모두 잡았다. 등가 변형이던 규칙의 `decision_exists` 조건은 지웠다(결정이 없으면 비활성화 사실도 없다).

**방식** [확정 2026-10-12, 사용자 — 기록 표 방식으로 착수]: 매체에 "활성 회차" 열을 두는 방법도 있다. 하지만 결정·반응 표(쓰기가 많은 표) 둘에 열을 더하고 접수 경로 셋을 고쳐야 한다. 그래서 **접수 경로를 건드리지 않는 기록 표 방식**을 권한다(구현 세션). 이 방식도 결과는 정확하다(비활성화가 여러 번이어도 맞음).

**매체(게임) 쪽 요청** — 사용자가 전달(2026-10-12):
1. `subject_id`를 광고 전용 가명으로(필수, 계약 1.2): `campus_profile.user_uuid`를 그대로 보내지 말고 게임 서버만 아는 비밀로 만든 값 — 예: `HMAC-SHA256(ADS_SUBJECT_SECRET, "ads-subject/v1:" + user_uuid)` 앞 16바이트 → UUID. 분석에서 광고 반응과 사용자를 이어야 하면 비밀을 가진 게임 쪽이 가명 ↔ 사용자 대응을 접근 통제 아래에서 내보낸다.
2. 401·403 처리(검토 P3-1 보완): 401로 막힌 노출은 설정을 고친 뒤 같은 `reaction_id`·같은 내용으로 다시 보내는 운영 경로(자동 반복 없음). 403은 지금처럼 다시 보내지 않는다.
3. 판정 결과(검토 P3-2 확정): `status`·`reason_code`는 게임 서버 안에서만 쓰고 브라우저 응답에서는 뺀다. 화면에 판정이 필요하면 알려 달라(필요한 최소 표시를 같이 정한다).

# 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| Django 6.1에서 axes가 동작하지 않음 | 0-2 게이트, 실패 시 5.2 LTS로 내림 |
| 설정 이름을 기억에 의존해 틀림 | §4의 "구현 시점 확인" 목록 |
| 메타버스 쪽이 재시도를 구현하지 않음 | 2-1에서 매체 담당자와 계약 공유. 못 지키면 "유실 없음"은 수신 이후 구간만 보장된다고 문서에 명시 |
| ~~SQLite 쓰기 직렬화가 부하에서 한계~~ → **MySQL 연결 한도** | SQLite는 2-6에서 150 동시 한계가 보이지 않았고 DB-1에서 MySQL로 대체됐다. MySQL은 요청마다 연결을 닫아 150 동시에서 `max_connections`(151)에 닿아 일부가 503 + 재시도를 겪는다(처리는 올바름, [load-test.md](load-test.md) §2). 영속 연결·풀은 배포 구성과 인프라 `max_connections`가 정해진 뒤 정한다(7.3.4 #4) |
| Step 1이 커서 일정이 늘어짐 | 1-3(`billing`)·1-4(`engine`)를 병렬로 분담 |
| 열린 결정이 구현 중 바뀜 | 설계 문서를 먼저 고치고, 정책 변경 지점(R8)은 설정·파일 하나로 닫혀 있다 |

---

# 10. 진행 상태

| 단계 | 상태 | 비고 |
|---|---|---|
| 승격 | 완료 (2026-10-07) | `intake/` → `docs/ads-server/`, 구현은 `apps/ads_server/` |
| DRD 승격 | 완료 (2026-10-08) | 광고 서버 데이터 요구사항 문서 [ads-server-drd.md](ads-server-drd.md) (`intake/` → `docs/ads-server/`) |
| 0-0 위협 모델 | 완료 (2026-10-07) | [threat-model.md](threat-model.md): 위협 26건(Step 0 보완에서 T27 추가), 0-1~0-6 모두 대응 행 있음 |
| 0-1 골격·설정·User | 완료 (2026-10-07) | 테스트 26개, `runserver` 확인, WAL·`synchronous=FULL` 확인. `check --deploy` 경고 5건 기록(README) |
| 0-2 계정·인증·세션 | 완료 (2026-10-07) | 테스트 59개(보안 태그 33개) 통과, 브라우저로 가입→로그인→로그아웃 확인. **Django 6.1 / axes 게이트 통과**(설계 §9 기록) |
| 0-3 접근 통제 | 완료 (2026-10-07) | 테스트 79개 통과. URL 전수 점검이 보호 없는 URL·예상 밖 공개 뷰를 잡는 것을 의도적 변조로 확인 |
| 0-4 HTTP 보안 | 완료 (2026-10-07) | 테스트 106개(보안 태그 80개) 통과, `check --deploy` 경고 0(W021만 사유를 적어 의도적으로 끔), 실제 응답 헤더·admin 화면 CSP 동작을 브라우저로 확인 |
| 0-5 assets | 완료 (2026-10-07) | 테스트 144개(보안 태그 118개) 통과. 실제 이미지를 서비스 함수로 저장→서버에서 200/304/404 확인, 브라우저로 표시 확인. 업로드 전체 크기 가드 추가(2026-10-07 검토 후 `RequestBodyLimitMiddleware`로 이동, 413) |
| 0-6 감사·점검 | 완료 (2026-10-07) | 테스트 177개 통과, `scripts/check.sh` 전체 통과(`check --deploy` 경고 0·마이그레이션·테스트·`pip-audit` 취약점 0·`bandit` 이슈 0). 경계 검사(R1·R2·`engine` 순수성·R3)가 가짜 위반 소스를 실제로 잡음을 검증. 브라우저로 5회 실패 잠금·잠금 중 올바른 비밀번호 거부·감사 로그 기록 확인 |
| **Step 0 전체** | **완료 (2026-10-07)** | 아래 종료 점검표 모두 충족. 구현: `apps/ads_server/` |
| Step 0 보완 | 완료 (2026-10-07) | 외부 검토 4건(감사 로그 덮어쓰기·과대 multipart 500·PNG ICC 잔존·관리자 본인 비밀번호 변경 감사 누락) 재현 후 수정, 회귀 테스트 추가. 의존성 직접 항목 패치 고정, `STATIC_ROOT` 설정 |
| Step 1 상세 계획 | 작성 (2026-10-07) | §6. 확정 반영: `Candidate`/`Eligible`, 적용 금액·종료 판정 `engine` 한 곳, 정수 포인트, `ENDED` 확정 상태, 가입 지급 50,000 |
| 1-1 `masters` | 완료 (2026-10-07) | 테스트 27개 추가(전체 223개), `check.sh` 통과. 정책 낙관적 잠금은 `expected_version`을 일부러 꺼 보면 테스트가 실패함을 확인(동시 저장 `['ok','ok']`). 경계 검사가 R2 위반 2건(`foundation.errors`·`foundation.models` 직접 import)을 잡아 `foundation.api` 경유로 수정. 위협 모델 T28 추가 |
| 1-4 `engine` | 완료 (2026-10-07) | 테스트 27개 추가(전체 250개). **Django·DB 없이 단독 통과**(`env -i … python -m unittest tests.test_engine_*`). 변형 검사: 동점 처리를 항상 첫 후보로 바꾸거나, `is_expired`·예산 비교의 경계를 어긋나게 하면 테스트가 실패함을 확인. 위협 모델 T29 추가 |
| 1-2 `campaigns` | 완료 (2026-10-07) | 테스트 57개 추가(전체 307개). 변형 검사: 종료 가드를 상태만 보게 하거나, 소유권 검사를 빼거나, 입찰 `expected_version` 검사를 끄면 테스트가 실패함을 확인. 동시 입찰 테스트가 "커밋 뒤 감사 기록"의 잠금 실패를 드러내 감사를 변경과 같은 트랜잭션으로 옮김(campaigns·masters). `foundation`에 `clean_text`·`parse_uuid` 공용화, `SlotView.media_is_active` 추가. 위협 모델 T30 추가 |
| 1-3 `billing` | 완료 (2026-10-07) | 테스트 25개 추가(전체 332개). 변형 검사: 잔액 하한·멱등 검사·예산 경계 오프셋·소진액 갱신을 각각 빼면 테스트가 실패함을 확인. 가입 지급 기본 50,000(`SIGNUP_GRANT_POINTS`), 가입과 지급은 한 트랜잭션(console 가입 뷰). 동시성 테스트(과금·입찰·정책) 10회 반복 안정. 위협 모델 T31 추가, §5.2 두 행에 테스트 연결 |
| 1-5 `records` | 완료 (2026-10-07) | 테스트 21개 + 통합 시나리오 1개 + 단일 원본 검사 2개 추가(전체 356개). 변형 검사: 저장 전에 응답을 돌려주거나, 스냅샷 대신 현재 값을 쓰거나, 잔액을 항상 충분하다고 가정하면 테스트가 실패함을 확인. 위협 모델 T32 추가 |
| **Step 1 전체** | **완료 (2026-10-07)** | §6.8 종료 점검표 모두 충족. 구현: `masters`·`engine`·`campaigns`·`billing`·`records` |
| DRD 정합 | 완료 (2026-10-07) | 입찰·정책 버전 행에 UUID(`bid_id`·`bid_policy_id`) 추가, 결정이 함께 기록. 기존 행은 마이그레이션이 채움(이전 스키마에서 만든 데이터로 검증하는 테스트 포함). 테스트 359개 |
| Step 1 보완 | 완료 (2026-10-07) | 외부 검토 5건 + 입력 검증 3건 재현 후 수정. ① 이미지 교체 반복의 쿼터 우회(P1) → `CreativeImage` 보유 관계로 쿼터 ② 추가 전용 5개 모델의 위치 인자 upsert 우회 → 부모와 같은 명시적 시그니처 ③ 소수 과금 → 입력·정책 반환값 정수 검사, 잔액 상한 `MAX_AMOUNT`(서비스+DB) ④ 재계산과 과금의 경쟁 → 원장 읽기부터 교체까지 한 쓰기 트랜잭션 ⑤ 교체 직후 과거 이미지 404 → 같은 보유 관계로 서빙 판단 ⑥ 잘못된 URL(`https://[`·포트)·`datetime` 범위 오류를 입력 오류로. Bandit 대상에 Step 1 모듈 5개 추가. 테스트 376개. 위협 모델 갱신 |
| **Step 2 전체** | **승인 (2026-10-08, 외부 검토 `1fe79e9` — V1 범위: SQLite·로컬 파일 독립 서버)** | §7.1 종료 점검표(사람의 일: 매체 담당자와 계약 공유). 구현: `serving_api`·`records`(수신함·처리)·`masters`(매체 키) |
| 2-11 마무리 | 완료 (2026-10-08) | 계약 `info.version` **`1.1.0`**(draft 해제, `[v1.1]` 표시 정리, 순서·`occurred_at` 허용 오차 문구를 구현과 맞춤, 400 검사는 404·403 뒤), 매체용 요약 [contracts/README.md](contracts/README.md)를 v1.1로(슬롯 두 종류, `click_url` 이동, 반응 순서·기간·보류와 사유 표), DRD §5.2·5.3 v1.1 반영(0.12), 위협 모델 **T38(클릭 관측)·T39(반응 판정)·T40(성과 집계)** 추가(Step 3의 T41·T42로 번호 이동), 부하 시험 단계 **H(클릭 경유 전체 퍼널)·J(일괄 슬롯 사람별 + 노출 없는 임의 `s` 클릭)·I(보류 해소 지연: 처리 프로세스가 없으면 보류로 남고 뜨면 약 5초에 풀림)** 추가, 규칙을 끄면 실패함을 확인. 150 동시 재측정은 Step DB의 DB-1d로 이관(MySQL로 잼). `load-test.md` §6. **Step 2 전체(v1.1 포함) 구현 완료.** 테스트 671개(시험 코드 변경 없음, 부하 시험만 확장) |
| 2-10 퍼널 집계 | 완료 (2026-10-08) | `records.api.daily_report`(`records/report.py`): 광고주의 일별 노출·클릭·전환(인정된 `ACCEPTED`만, 일괄 슬롯은 사람마다)·소진 포인트와 직전 같은 길이 구간 합계, 구간의 모든 날을 0 으로 채움, CTR·전환율은 합계의 파생 속성(분모 0 이면 `None`). 범위는 결정의 `owner_id`·`campaign_id`·`ad_group_id`(남의 캠페인·광고그룹은 404, 광고주만), 구간은 예산 일 경계·최대 92일(아니면 400), 날짜는 수신 시각의 예산 일(`BUDGET_DAY_OFFSET_HOURS` 반영). 소진은 실제 받은 포인트(잔액 부족분 제외): 캠페인·광고주는 `CampaignSpend`, 광고그룹은 원장 과금에서 읽어 합이 캠페인과 일치. `billing.api`에 `spend_by_day`·`charged_amounts`·`day_start`, `campaigns.api`에 `campaign_ids_of`, 결정 인덱스 `(owner_id, campaign_id, ad_group_id)`(마이그레이션 `records/0008`). 질의 수는 데이터 양과 무관(시험으로 고정). 새 시험 `tests/test_funnel_report.py` 16개, 변형 13종(살아남은 2개는 질의 하한 최적화라 결과에 영향 없는 동등 변형). 테스트 655 → 671 |
| **Step 6-1** 매체 연동 검토 후속(게임 ad-bridge) | **완료 (2026-10-12)** — 결정 반영 → 서버 규칙 6-1a `42de743`·6-1b `a70d769`·6-1c 측정 → 6-1d 문서 | §8.4.2. 사용자 결정 셋(2026-10-12): ① `subject_id`는 매체가 만든 광고 전용 가명 ② 반응 401은 고친 뒤 한 번 재전송·403은 재전송 없음, 매체 비활성화는 그 전 결정을 끝냄(`media_deactivated`) ③ 판정 결과·사유는 매체 서버용. **결정 반영**: 계약 C1 **1.2.0**(호환 — 전송 형식 그대로, 규약 MUST·규칙 5·`getReaction`·`ReactionReasonCode`)과 매체용 요약, DRD 0.32(D-5 해결), 위협 모델 A6·T41, 설계 §2·C1 규칙 5·§8 Step 6·§10 결정 넷. **서버 규칙**(기록 표 방식, 사용자 결정): 6-1a `42de743` `masters_media_deactivation`(켜져 있던 매체를 실제로 끌 때만 한 줄, 추가만, 관리자 화면 읽기 전용, `first_deactivation`), 시험 1,304개 · 6-1b `a70d769` 규칙 `media-period`(`same-media` 바로 뒤, 구간 (결정, 접수], 필수 조건, `basis` v3 `media_deactivated_at`), 시험 1,310개 · 6-1c 질의 수 **결정 10 · 반응 39 · 클릭 27**(전 10 · 38 · 26). 단계마다 `check.sh` 종료 코드 0(20 동시·구간 `match` 12·`pip-audit`·`bandit`), 변형 검사 6·10개 모두 잡음(구현 세션). **6-1d**: 계약 1.2.0 안에서 `media_deactivated`(사유 코드 추가는 호환), 매체용 요약, 설계 §4.7 규칙 표·2-9 순서·§10, DRD 0.33(M5·`basis` v3·규칙 체인), 위협 모델 T45·T39 ⑥·§5.2. 매체(게임) 쪽 요청 셋은 사용자가 전달 |
| **Step 3-4 코드 정리** (리팩터링 3차) | **완료 (2026-10-12)** | §8.3대로 8단계, 한 단계 한 커밋(`a9a5a38`~`4d42b7e`, 8커밋). 단계마다 `check.sh` 통과 뒤 커밋, 시험 1284 → **1303개**(3-4a +16, 3-4g +3). 3-4a `a9a5a38` 특성 시험 · 3-4b `32a909e` `foundation.is_request_key`·`clean_request_key` · 3-4c `d3b086e` masters의 요청 키 검증 사본 삭제(매체 키 발급·교체의 검증 위치·문구 그대로) · 3-4d `317ecc7` billing 요청 키·`Conflict` 문구 상수, campaigns 도우미 넷(캠페인별 소재 묶기·관리자의 캠페인 잠금 조회·화면이 본 시각 대조·`enabled` 타입 검사) · 3-4e `3ab9369` 쓰지 않는 `HOPS` 삭제, 최대 상주 메모리 주석 위치, 미해결 과금 예시 `append` · 3-4f `ff74010` 폼 없는 동작 12곳을 `console.errors.run_action` 하나로 · 3-4g `24fe4dd` 화면의 중복 읽기(B1)와 광고그룹 목록 N+1 · 3-4h `4d42b7e` 시험의 쓰지 않는 import. **검증**(리팩터링 세션): 서빙 질의 수는 결정 10 · 반응 38 · 클릭 26 그대로(리팩터링 전 `4fcb2ef`와 같은 측정으로 비교). 3-4g 실측 — 대시보드 19 → 16, 광고그룹 상세 14 → 13, `list_ad_groups`(그룹 3개) 8 → 4로 그룹 수와 무관. 150 동시 부하 시험 모든 불변식 충족 — 로그의 `1040 Too many connections` 4건은 150 동시에서 연결이 MySQL 상한에 닿는 알려진 현상이고 503 + 재시도로 처리됐다(§9 "MySQL 연결 한도"). **구현 세션 재확인**(`4d42b7e`): `check.sh` 종료 코드 0 — 시험 1303개, `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, 구간 대조 `match` 12줄, `pip-audit`·`bandit` 통과. **계획과 다른 점**: ① 3-4a에서 변형 30개 중 25개가 기존 시험을 통과해(성공·오류 메시지와 소재 순서를 거의 보지 않았다) 시험을 더했다 — `tests/test_service_input_contracts.py` 외에 `tests/test_screen_action_messages.py`(6개, 12곳의 성공·오류 메시지와 돌아갈 곳)와 `test_operator_campaigns`의 `test_creatives_are_listed_in_creation_order_in_both_lists`. 남은 변형 4개는 결과가 같아 시험으로 구별할 수 없는 등가 변형이다 — 매체·슬롯 활성과 키 폐기의 오류 메시지(그 경로는 404만 남음), 슬롯 활성의 404(뷰가 먼저 냄) ② `run_action`은 반환값이 없다(12곳 모두 성공·실패와 상관없이 같은 곳으로 돌아가 쓰는 곳이 없음) ③ 순감은 3-4g를 빼고 코드 −19줄(계획 약 −50, 새 도우미에 붙인 설명만큼 덜 줄었다). **3-4g로 바뀐 동작**: 대시보드의 포인트 위젯과 잔액 알림, 상위 캠페인 표와 알림이 같은 읽기(지갑·캠페인 목록 한 번)를 보고, 상위 캠페인 표의 상태도 화면의 `now` 기준이다. 광고그룹 상세의 위치 정보와 위치별 결과가 같은 읽기를 본다. 시험 `test_the_page_reads_the_wallet_and_the_campaign_list_once`·`test_the_page_reads_slot_policies_once`·`test_list_ad_groups_reads_a_fixed_number_of_queries`. **공개 API 변경**: `campaigns.bid_effects(amount, slot_ids, slots=None)`, `console.queries`의 `alerts_for(user, now, camps, wallet)`·`top_campaigns(user, start, end, camps, limit=TOP)`. 새 도우미: `foundation.api`의 `is_request_key`(1~64자 문자열)·`clean_request_key`(`None`은 그대로, 틀리면 `/request_key` 400), `console.errors.run_action(request, call, *args, success=None, **kwargs)`. 화면 값을 정하는 규칙은 그대로라 C6·설계는 바뀌지 않는다. 환경: 리팩터링 세션의 DB(`ads_refactor3`·`test_ads_refactor3m`)는 그 세션이 지웠다(다른 세션의 DB는 그대로) |
| Step 3-4 코드 정리 계획 | 계획 (2026-10-12) — 8단계(3-4a~3-4h) | 리팩터링 3차(리팩터링 세션 보고, 위치는 `4fcb2ef` 기준)를 §8.3에: 3-4a 시험 먼저 → 3-4b L0 요청 키 검증 공용 → 3-4c L1 masters → 3-4d L2 billing·campaigns(반복 5묶음) → 3-4e L3 records(쓰지 않는 코드·표기) → 3-4f L4 console(`run_action`으로 12곳) → 3-4g 화면의 중복 읽기 B1과 광고그룹 목록 N+1(의도한 동작 변화, perf — 사용자 결정 2026-10-12) → 3-4h 시험 정리. 3-4g 밖은 동작 불변, 순감 약 50줄 |
| **Step 3 전체** (3-0 · 3-1 · 3-2 · 3-3) | **승인 (2026-10-12, 외부 검토 `13f3bc2` 통과)** | 외부 검토 이력(범위 `38647b9..13f3bc2`): `e781f20` 검토에서 P2 1건·P3 2건 → `5e8fa8c`·`de77684`, `5e8fa8c` 재검토에서 P2·P3 → `13f3bc2`, 재검토 통과. `5e8fa8c` 재검토의 열린 항목 두 건 — P2(다른 UUID 표기의 과금 키가 원본 구간 조회와 미해결 검사 양쪽에서 빠짐)와 P3(미해결 검사의 반응 조회가 매체 × 반응 ID 교차 조합을 읽음) — 는 `13f3bc2`로 고쳤고, 재검토에서 해소를 확인해 **닫음**(P2 반례는 미해결 3건으로 내보내기·대조 모두 실패, P3는 청크 4에서 16행 → 4행). §8.1.7 종료 점검표. **검증 범위 — 이번 검토에서 다시 재지 않은 것**: 실제 브라우저, 150 동시 전체 부하, 장애·failover, 다중 웹 워커, 장시간 메모리 증가, 실제 플랫폼 연동, 질의 수 10·38·26, 기본 청크 2,000에서의 대규모 RSS. 이 가운데 150 동시 부하와 클러스터는 구현 세션이 `89c8a38` 시점에 `cluster_check.sh`로 통과시켰다. 남은 사람의 일: HTTP/HTTPS 배포(설계 §7-14). 진행 기록: | 3-0a `e8e3494` 내 정보·비밀번호 서비스(S2) · 3-0b `dd305d6` 광고 만들기 서비스(S3) · 3-0c `4bebbe5` 콘솔 경계 규칙, 가입 묶음 `billing.register_advertiser` · 3-0d `82d93a2` 콘솔 공통 틀·역할별 루트 주소 · 3-1a `e557e0d` 운영 화면(매체·위치·키) · 3-1b `7e1d9fe` 입찰 정책 · 3-1c `b396d0d` 모니터링·중단·재검토(외부 검토 보완 `da0eb88`) · 3-1d `749148a` 광고주·포인트(비활성 표시 `9013a30`, 사용자 관리 화면의 광고주 활성 여부 읽기 전용 `e094a17`) · 3-2f `c4f391f` 내 정보·비밀번호 변경 시도 제한 · axes 기록 읽기 전용 `83dd621`. 외부 검토 3-1d 보완 `ab7a607`(포인트 조정의 원장 멱등 키, 세션 폐기 버전, 역할 읽기 전용·계정 추가 없음, 지갑 없는 옛 계정)·`ab5bc59`(`is_superuser` 읽기 전용)·`1e72031`(매체 키 발급·교체도 요청 키, `console/once.py` 삭제)·`d2e2ee5`(사용자 관리는 편집한 칸만 쓰기, 키 발급·교체는 매체 행 잠금)·`3eb5f77`(비밀번호를 바꾸는 요청은 세션 근거를 최신 행과 대조, 계정 삭제 없음)·`d44b36a`(초기화는 요청자·대상을 ID 순서로 잠금)·`00d3067`(잠금 대상은 화면과 같은 ID 해석, 해석 불가 404). 외부 검토 `00d3067` P2·P3 `8449469`: 비밀번호 변경·초기화의 성공 감사 기록을 변경과 같은 트랜잭션에, 화면의 교착·잠금 대기 초과는 503 + `Retry-After`(§8.1.1), 재검토 대기는 대기 캠페인의 소재만 읽음(P3-4 1단계, 질의 2번), 경쟁 시험 도우미를 `tests/concurrency.py`로 모음(잠금 SQL 도착 신호 `arriving_before`, 잘못된 대상은 잠금 SQL·화면 미실행까지 확인), 시험 1172개. 3-2a 광고주 대시보드 `b8c3d2d`(기간·지표·그래프·포인트)·`6f05beb`(상위 캠페인 표)·`362a4c6`(알림 패널), 시험 1194개. 3-2b 광고주 캠페인 `a75bdad`(목록·상세·수정의 버전 대조·끝내기·정지 사유와 재검토 요청), 시험 1208개. 3-2c 광고 만들기 `b61112a`(한 페이지 폼, 미리보기 `bid_effects`, `Campaign.request_key`, 화면 경로의 413은 HTML, 작은 JS 셋), 시험 1223개. 3-2d 광고그룹 상세 — 서비스 결함 수정 `a909908`(입찰 추가·광고그룹 수정·소재 수정·이미지 교체를 캠페인 행 → 그 행 순서로 잠금, 소재 수정의 버전 대조), 화면 `3baf897`(동작마다 작은 폼, 본인 전용 이미지 경로 S4), 시험 1241개. 3-2e 광고주 포인트 `41d2288`(원장 내역 커서, 과금 줄의 캠페인 이름·못 받은 포인트, 원장 표를 관리자 화면과 공용 — 관리자 원장에도 캠페인 이름, `campaigns.campaign_names`), 시험 1247개. 외부 검토(41d2288) P2 3건·P3 `7fdc76f`: 광고주 상한은 광고주 잠금 행(`AdvertiserQuota`)을 가장 먼저 잡고 그 안에서 셈(서로 다른 캠페인의 동시 만들기·이미지 교체가 상한을 넘었다), 성공한 요청 키는 폼 검증보다 먼저·잠금 안에서 다시 확인, KST로 표현할 수 없는 범위 끝 시각은 칸 오류(500이었다), 광고그룹 이름·게재 위치·이미지 교체도 화면이 본 변경 시각과 대조(`AdGroup.updated_at`). 3-3a·3-3b `38647b9`(접근 제어 전수·화면 전수 점검 시험, 라이트 `--muted` 대비), 3-3c `526046d`(Chrome 화면 점검에서 찾은 8건 — 광고 만들기의 Enter는 집행, 미리보기 `[hidden]`, 운영 표 가로 스크롤, 소재마다 이미지 교체 폼, 키 교체 확인 창, 폼 `id` 겹침, 비밀번호 `autocomplete`, 입찰 충돌 문구). 3-3d `ca2572c`(모니터링 DB 정렬·쪽 나누기, P3-4 2단계). 3-3e `6654077`(구간 manifest 내보내기를 창 단위로, P3-3 — 색인 셋, `scanned_events`는 범위 안, `largest_window=`·`peak_rss=`). 종료 점검 `89c8a38`(JS 없는 주요 흐름의 HTML 폼 기반 서버 통합 시험, C6 규칙 ↔ 서비스 대조, 비밀번호 최대 길이 검증기). 화면 전수 점검 보완 `e781f20`(정상 GET으로는 나오지 않는 화면 — 매체 키 발급·로그인 잠금·가입 시도 제한·오류 화면도 같은 기준으로). 외부 검토 범위 `38647b9..e781f20`. 외부 검토(`e781f20`) 보완 `5e8fa8c`(P2: 창에 놓을 수 없는 과금 원장 줄을 세어 내보내기·`verify_hops` 실패)·`de77684`(P3: 화면 점검 빠뜨림 방지, JS 없는 흐름은 HTML 폼 기반 서버 통합 시험이라고 정확히). 재검토(`5e8fa8c`) P2·P3 `13f3bc2`(판정한 반응의 키를 다른 UUID 표기로 바꾼 과금이 "일치"로 끝났다 → 과금 키는 표준 표기일 때만 그 반응의 키, 백필도 다른 표기로 추측하지 않음, 미해결 검사의 반응 조회는 정확한 쌍만). 위협 모델 T40·T43·T44 행 |
| 외부 검토(`00d3067`) 남은 P3 | **완료 (2026-10-12)** — ② P3-4 2단계 3-3d `ca2572c`, ① P3-3 3-3e `6654077` (3-3에서 처리, 결정 2026-10-11 사용자) | 범위가 커 `8449469`에서 손대지 않았다. 둘 다 지금 규모에서는 급하지 않다. ① **P3-3 구간 정합 manifest 내보내기의 메모리**(Step 4 코드): `records/hops.py` `expected_events()`가 기대 이벤트 전체를 메모리에 만든다 → `produced_at`으로 조회 범위를 먼저 좁히고 창·이벤트 종류·ID 순으로 읽으며 해시를 점진적으로 계산한다. 기존 요약값, 원본에서 독립적으로 기대 이벤트를 만드는 규칙, 같은 읽기 스냅샷은 그대로 지키고, 읽은 행 수와 최대 메모리 측정을 더한다. 검토자도 메모리 부족을 재현하지는 않았고 소스에서 본 확장 위험이다 — **완료 `6654077`**(3-3e): 세 구간 모두 닫힌 창 하나·이벤트 종류 하나씩 읽어 요약한다. **계획과 다른 점**: ⓐ 조회 범위는 `produced_at` 열 하나가 아니라 구간마다 그 생성 시각에 해당하는 열로 좁힌다 — 원본에는 `produced_at` 열이 없어 결정 시각·수신 시각·처리 시각(과금은 그 반응의 처리 시각), outbox는 `created_at`(이벤트 종류별), MongoDB는 `produced_at`. 이를 위해 색인 셋을 더했다(반응 `received_at`·`processed_at`, outbox `(event_name, created_at)`) ⓑ 해시를 점진적으로 계산하지 않고, **닫힌 창 하나·흐름 하나를 통째로 읽어 기존 `summarize`로 요약**한다(전부 읽어 한 번에 요약한 것과 같음을 시험). 메모리 상한은 "창 하나·흐름 하나"이고(ID 순 정렬에 필요), 그것도 크면 `--window hour`, 그래도 크면 외부 정렬 ⓒ 측정은 "읽은 행 수" 대신 `checkpoint.scanned_events`(범위 안에서 읽은 이벤트 수)와 실행 결과 줄의 `largest_window=`(한 번에 든 최대 이벤트 수)·`peak_rss=`(최대 상주 메모리) ⓓ 계획에 없던 것: `--since` 앞과 열린 창은 읽지 않고 빈 창은 건너뛴다, 과금은 판정 흐름 안에서 창의 반응으로 원장 과금 줄을 멱등 키로 찾는다(`billing.charge_entries_for`, 반응이 없는 과금 줄은 처음(`6654077`)엔 원본 구간에서 조용히 빠져 세 구간이 "일치"로 끝났다 → 외부 검토 `e781f20` P2로 생성 시각을 추정하지 않고 **따로 세어 내보내기·대조를 실패로 끝낸다**(`5e8fa8c`, `checkpoint.unresolved_charges`)), 미전송 건수는 미전송 행만 읽는다. 같은 읽기 스냅샷(①·②)과 원본에서 독립적으로 기대 이벤트를 만드는 규칙(매핑은 `expected_events`와 공용)은 그대로다 ② **P3-4 2단계 모니터링 DB 정렬·쪽 나누기**: `campaigns.monitoring_list`는 전부 읽어 파이썬에서 정렬한다(광고주 150명 × 캠페인 상한 20 전제, 코드에 한계 표시) → 마지막 변경 시각(캠페인·소재 중 늦은 쪽)을 DB에서 계산·정렬하고 그 쪽의 소재·요청만 읽는다 — **완료 `ca2572c`**(같은 시각은 캠페인 ID 역순, 쪽마다 질의 4번, §8.1.2 S5) |
| **Step 3 착수 전 결정** | **결정 확정 (2026-10-11)** — 진행은 위 "Step 3 진행" | §8.1 갱신(2026-10-08 작성분을 DB 전환·Step 4 이후 상태로). D3-1 **조정**(JS 없이 동작이 기본, 작은 JS를 덧붙이는 규칙 셋과 MVP에서 붙이는 곳), D3-2·D3-3·D3-6 제안대로, D3-5 제안대로(오늘 포함은 우선 진행, 통합 시험에서 다시 판단), 재검토 조건(설계 §6.6의 분리 길). 위협 모델 Step 3 번호 T43(콘솔 뷰)·T44(관리자 동작)로 바꿈(T41·T42는 Step 4). 3-0에 루트 주소 역할별 이동·`foundation.api` 공용 도우미 전제, 3-2c에 "미리보기" 제출, Step 3 쓰기는 새 이벤트 종류 없음. 열린 항목: HTTP/HTTPS 배포(설계 §7-14). 설계 §10 "Step 3 화면 결정" |
| **Step 4-4 코드 정리** | **완료 (2026-10-11, 외부 검토 승인 — 로컬 구현 검토 닫힘)** | §8.2대로 7단계 + 선택 1, 한 단계 한 커밋. 4-4a `e53a15a`: `missing_event_ids`·`backfill`이 `chunk < 1`이면 `ValueError` · 4-4b `4669418`: 판정 근거 쓰기 경계 시험을 AST로, `records/hops.py`를 `basis=r.basis`로 → 외부 검토 P2 보완 `6b563cf`: 쓰기의 정의를 넓힘(위치 인자·`get_or_create`·`defaults`/`create_defaults`·`**{"basis": …}`·`Reaction(basis=)`, 한계는 실행 중에 만든 `update(**fields)`) · 4-4c `15bc8df`: `reaction_ref`·`parse_reaction_ref`를 `records/processing.py`에 두고 `hops`·`backfill`이 같이 씀 · 4-4d `90d4d6b`: 구간 줄 버전·창 이름과 크기·시각 형식을 `events/hops.py`에 두고 내보내기와 대조가 같이 씀 · 4-4i `4f66ab8`: `_replace_durably`(교체 + 폴더 동기화)를 데이터 파일과 manifest가 같이 씀 · 4-4h `9990f73`: 아홉 곳이 `events.api.mongo_error_text`(오류 종류 + 앞 200자)를 씀 · 4-4k `73b32ab`: `scripts/docker_cli`를 세 스크립트가 각자의 시간 제한(120·180·300초)으로 씀 · 4-4e `4de457f`: 상시 중계 특성 시험(점점 길게 쉬기 최대 30초와 성공 뒤 초기화, 충돌 시 재시도 없이 멈춤, 신호 처리기 복원). **바뀐 동작은 둘뿐**: 4-4a 오류 형태, 4-4h 문구 길이(`ensure_event_store` 300 → 200자). 시험 1006 → **1031개**, `check.sh` 통과(PR 브랜치 `feat;#13`·`doc;#14`를 합친 깨끗한 작업 트리). 질의 수 단계마다 그대로(결정 10 · 반응 38 · 클릭 26), 150 동시(4-4c·4-4d 뒤, 검사 52개·구간 `match` 12줄)·단일 노드 장애 5개(4-4k 뒤)·클러스터 `check.sh`·150 동시·장애 8개(primary-kill 26.2초 자동 전환, 미확인 0) 통과, 변형 검사 단계마다 잡음(4-4e 6/7, 놓친 1건은 등가 변형) — 구현 세션, 외부 검토도 다시 돌려 확인(`load-test.md` §10). 일부러 남긴 중복 C1~C6(§8.2.4), 후속 후보 §8.2.6(`wait_ready` 시간 제한) |
| 4-4 코드 정리 계획 | 계획 확정 (2026-10-10) — 7단계 + 선택 4-4e | 리팩터링 2차 후속(리팩터링 세션 보고, 위치는 `5666946` 기준)을 §8.2에: 4-4a 청크 크기 입구 검사 → 4-4b 판정 근거 경계 시험 AST화(쓰기의 정의 명시) → 4-4c 원장 멱등 키 형식 → 4-4d 구간 계약 값(줄 버전·창 이름 ↔ 크기·시각 형식) → 4-4i 원자적 게시 단계(교체 + 폴더 동기화 함수 하나) → 4-4h MongoDB 오류 문구(9곳, 200자) → 4-4k 시험 `docker()`. 선택 4-4e: 상시 명령의 시험 없는 동작만 특성 시험. 리팩터링 세션 검토로 처음 11단계에서 상시 루프 공용화(4-4f·g)와 `Counter`(4-4j)를 빼 일부러 남기는 중복(C4·C5)으로 옮기고, 파일 종류별 버전을 C6으로. 결정 R2~R6 확정(R1 삭제), 성능 보류 4건 |
| 리팩터링 2차 0~4단계 | 완료 (2026-10-10) | **동작 변경 없음**(`c4a6b63`~`5666946`). 0단계 `c4a6b63`: 청크로 나눠 읽는 조회 6곳의 경계를 고정하는 특성 시험(청크 크기를 넘는 입력, 변형 검사 6회). 1~3단계 `a7531b5`·`281dc17`·`9649501`(events·billing·records): 손으로 짠 청크 루프를 `itertools.batched`로, 중복 계산·옛 별칭·불필요한 dict 정리. 4단계 `5666946`: 시험의 안 쓰는 import. 단계마다 시험 1006개 + `check.sh` 통과, 3단계 뒤 150 동시 부하(이벤트·백필·구간 manifest 대조 포함) 통과. 남긴 것(동작 차이 1건·중복 8건)은 Step 4-4(§8.2) |
| 외부 재검토(`f52d1df`) 후속 | 완료 (2026-10-10) — 외부 검토 보완 닫힘 | P2 1건(구현 `af4c65d`): manifest별 잠금만으로는 겹친 두 내보내기가 세 manifest의 최종 포인터와 최신 감사 고정점을 서로 다른 실행의 것으로 남길 수 있었다 → 내보내기 한 번(세 manifest 게시부터 감사 고정점 커밋까지)을 폴더 단위 잠금(`flock`, `.run.lock`)으로 직렬화(manifest별 잠금은 그 안에서 그대로). 읽기 단계는 잠금 밖. 한 호스트의 로컬 파일시스템 전제. 시험 `test_two_overlapping_exports_leave_the_latest_audit_anchor_equal_to_the_published_pointer`. 설계 §6.3a·§10 H12, DRD §5.6(0.24), 위협 모델 T42 |
| 외부 검토(`b481024`) 후속 | 완료 (2026-10-10) | P2 5건(구현 `f52d1df`). ① **중계 지연 판정**: "하류가 적고 미전송이 있으면 지연 후보" → 부족분이 그 (창, 이름)의 미전송 건수로 설명될 때만, 설명할 수 없는 부족분은 확정 불일치 ② **보존 정리와 대조 범위**: 대조 제외 창을 남은 outbox 줄이 아니라 보존 범위로 — 시작이 보존 기준 시각(지금 − 보존 일수) 이후인 창만 outbox 대조, 기준이 창 한가운데면 창 전체 제외, `checkpoint.retention_cutoff` ③ **구간 manifest 입력 검증**: 구간 종류·계약 버전·창 크기 선언·창 경계와 길이·건수와 해시 형식·(창, 이름) 중복 거부, 창 크기가 다른 manifest는 대조하지 않음 ④ **세대 사슬 동시 게시**: `flock`으로 직전 세대 읽기부터 포인터 교체까지 직렬화, 감사 로그 고정점은 이 실행이 게시한 manifest 해시(한 호스트의 로컬 파일시스템 전제) ⑤ **`cluster_check.sh` 기동 실패**: 기동 종료 코드를 직접 확인, 이전 클러스터 값을 비우고 이번 실행이 만든 클러스터만 정리. 시험 22개 추가(검토 반례를 먼저 재현, 변형 검사 18건). `check.sh` 통과(**시험 1000개**), 단일 노드 장애 시나리오·클러스터 primary-kill 재실행 통과(구현 세션). 설계 §6.3a·§10, DRD §5.6(0.23), 위협 모델 T42, README |
| InnoDB Cluster 로컬 시험 | 완료 (2026-10-10, 외부 검토 `b481024` 보완 `f52d1df`·`af4c65d`으로 닫힘) — 운영 전환은 인프라 요청 후보 | 구현 `b481024`: `docker/innodb-cluster/`·`scripts/mysql_cluster.py`·`scripts/cluster_check.sh [--failure]`, `failure_test --mysql cluster`(8개 시나리오), 시험 표 하나에 기본 키 추가(그룹 복제 오류 3098). 클러스터에서 `check.sh` 통과(시험 977개), 150 동시 통과(문서 세션 재측정), 장애 8개 시나리오 통과. 앱 코드 변경 없음. 상세 §7.3.4c, `load-test.md` §9, 설계 §10 "그룹 복제(InnoDB Cluster) 전제", 인프라 요청 7.3.4 #8 |
| 4-3d 부하·장애 시험에 백필·구간 대조·지연 측정 | 완료 (2026-10-10) | 구현 `1f4733b`. 이벤트 지연 표본기: 생성 시각 뒤 outbox에 처음 보이기까지를 재서, 창 닫힘 여유(120초)를 넘은 늦은 이벤트와 한 번도 못 본 이벤트가 0이어야 통과(H11 B안 전환 조건의 측정, 표본기 시험 3개). 부하 시험 끝에서 세 구간 manifest 일치(`--as-of`로 오늘 창을 닫아 재현)와 **백필 훈련**: 이벤트 60건을 outbox·MongoDB에서 지움 → `export_integrity` 목록 60건 → dry-run은 쓰지 않음 → `--apply` → 중계 → 점검 누락 0 → `verify_events` 통과 → 다시 돌려도 늘지 않음 → 구간 manifest 요약값이 지우기 전과 같음 → 세대 사슬 이어짐. 장애 시험은 모든 시나리오 끝에서 지연과 구간 일치를 확인. `export_hop_manifests`에 `--window day|hour`·`--as-of`. **측정(구현 세션)**: 150 동시 이벤트 6549건 최대 지연 3.4초, 장애 5개 시나리오 통과·복구 뒤 세 구간 12줄 모두 `match`·장애 중 포함 최대 지연 4.3초(MySQL 재시작), 늦은 이벤트·못 본 이벤트 0 → **H11 A안 유지**. 대조: 일하지 않는 중계면 미전송 3148건·`relay_lag_candidate` 8줄로 실패. **Step 4-3 전체 `check.sh` 통과(시험 977개)** |
| 4-3c 구간 대조 `verify_hops` | 완료 (2026-10-10, 외부 검토 `b481024` 보완 `f52d1df`·`af4c65d`으로 닫힘) | 구현 `5019145`. 원본 → outbox, outbox → MongoDB, 원본 → MongoDB를 (창, 이벤트 이름)별로 대조해 `match`·`mismatch`(다른 필드)·`relay_lag_candidate`·`open_window`·`not_comparable`로 분류(원본 → outbox는 지연으로 보지 않음). manifest를 먼저 검증, 세대 사슬을 처음까지 확인, 최신 manifest가 감사 로그 고정점과 같은지 확인(고정점이 없으면 `--no-anchor` 요구). 파이프라인 manifest(`--pipeline`)는 MongoDB 구간과 대조. 확정 불일치·검증 실패·사슬 오류·고정점 불일치는 비정상 종료, 지연 후보만 있으면 정상 종료. 결과 `hop_report`. `foundation.api.latest_audit_detail` 추가. 시험 18개(변형 검사 10건) |
| 4-3b 구간별 정합 manifest `export_hop_manifests` | 완료 (2026-10-10, 외부 검토 `b481024` 보완 `f52d1df`·`af4c65d`으로 닫힘) | 구현 `e01ee21`. `hop_source`(원본에서 독립적으로 다시 만든 기대 이벤트, 재구성을 `records.hops`로 옮겨 `verify_events`와 공유)·`hop_outbox`·`hop_mongo`를 각각 NDJSON + manifest로 게시. 원본·outbox는 한 MySQL 읽기 스냅샷, MongoDB는 스냅샷 밖. 창은 UTC 자정 고정, 창 끝 + `EVENTS_HOP_GRACE_SECONDS`(120) 뒤 닫힘, 열린 창은 `checkpoint.open_windows`에만. 요약 규칙: `ids_sha256`(정렬한 소문자 UUID를 `\n`으로 이음)·`content_sha256`(MongoDB 문서 형태를 RFC 8785 JCS로, UTF-16 키 정렬·ECMAScript 숫자 표기, RFC 부록 예시로 시험). outbox 구간은 보존 정리 전 창만(`not_comparable_windows`), 줄마다 `unsent`. 세대: `previous_sha256` + 각 세대 manifest의 불변 사본, 감사 로그 `events.hop_manifests_exported`에 고정점. 시험 21개(변형 검사 10건) |
| 4-3a 이벤트 백필 `backfill_events` | 완료 (2026-10-10) | 구현 `6c99c3e`. `--input <event_gaps manifest> --out DIR [--apply] [--chunk 500]`: 입력 manifest를 검증한 뒤(실패하면 거부) 원본 MySQL 행에서 이벤트를 다시 만든다. 목록의 `event_id`는 원천 ID에서 다시 계산한 값과 대조, 이벤트 이름·원천 종류 대조. 판정·과금 기록을 라이브와 공유(`processing.judged_event`·`charge_event`) — 라이브 이벤트를 지우고 백필하면 이름·버전·메시지 키·생성 시각·페이로드가 같다. outbox·MongoDB 어디에도 없는 이벤트만 쓴다. 해석 불가(원본 행이 없음·과금 반응을 못 찾음)는 쓰지 않고 비정상 종료, 판정 전 반응의 판정 이벤트는 쓰지 않음, 옛 형식 근거는 `legacy_basis`로 셈. 청크마다 이벤트와 감사 로그(`events.backfilled`)를 함께 커밋. 결과 `backfill_result`. `billing.api.charge_entries` 추가. 시험 18개(변형 검사 12건) |
| 4-3 설계·결정 문서 반영 | 완료 (2026-10-10) | 구현 세션 요청서(기준 `d05d681`)를 반영: 설계 §6.3a, §10 "Step 4-3 백필·구간 manifest 결정"(H1~H7 구현 세션 기본값, H8~H12 문서 세션 제안, 사용자 확정. H11은 A안 — 창 끝 + 2분, 늦은 이벤트가 보이면 B안), DRD §5.6 구간별 manifest 계약·§5.9 작업 표, 위협 모델 T42, `load-test.md` §8 |
| 외부 검토(`10a8808`) 후속 | 완료 (2026-10-10) | P2 1건(구현 `d05d681`): 이벤트 검사기가 봉투(`schema_version`·생성 시각)를 원본과 대조하지 않아, outbox와 MongoDB의 봉투를 같은 잘못된 값(버전 9999, 생성 시각 하루 뒤)으로 바꾸면 두 사본 비교는 통과하고 원본 대조도 정상으로 판정했다 → 원본 대조에 `schema_version`과 생성 시각(결정 = 결정 시각, 접수 = 수신 시각, 판정·과금 = 처리 시각)을 추가. 네 이벤트 종류 모두에서 봉투 변조가 실패함을 시험, 변형 검사 5건. **Step 4 최종 기준**: `d05d681`, `check.sh` 게이트 통과(시험 915개). 재검토에서 Step 4 로컬 구현·검증 완료 판정(다중 노드 failover·인프라 통합·다중 웹 워커·장시간 운용은 범위 밖) |
| 외부 검토(`8e25f03`, Step 4-2 시점) 후속 | 완료 (2026-10-10) | P2 4건(구현 `10a8808`). ① **중계의 내용 비교**: 파이썬 값 비교라 `1`과 `true`·`1.0`(중첩 포함)을 같은 내용으로 인정 → JSON 타입까지 구분하는 정규화 직렬화(키 순서 무시), 타입이 다르면 충돌 ② **NDJSON 게시 원자성**: 데이터 파일과 manifest를 각각 교체해 manifest 교체만 실패하거나 두 실행이 엇갈리면 짝이 맞지 않는 쌍이 남음 → 불변 세대 파일 + manifest 포인터 교체 ③ **점검 범위**: `checkpoint`가 "재개 위치"·"이 시각 뒤 행 제외"로 설명됐지만 실제 조회에 조건이 없었음 → 세 점검을 한 읽기 스냅샷에서, checkpoint는 범위 서술 ④ **부하 검사기**: 이벤트 ID 집합만 비교 → 원본 행 ↔ outbox 내용, outbox ↔ MongoDB 문서 전체 대조. 시험 36개 추가. 문서: MongoDB 장애 문장을 보장(요청 경로는 MongoDB를 호출하지 않음)과 관찰(짧은 재시작에서 503 0)로 나누고 장기 장애의 MySQL 부담을 적음, 뒤처진 상태 표시(DRD §5.1 C2·§4.2 P2 처리, README) 정리, README에 상시 프로세스·보존 정리·`--status`·충돌 대응 안내, Step 5 전환 게이트(설계 §6.3) |
| 4-2 NDJSON manifest·검증 | 완료 (2026-10-10, 외부 검토 보완 반영) | `events/ndjson`: **게시 = 불변 데이터 파일 하나 + manifest의 원자적 교체 하나**. 데이터 파일 이름에 내용 해시(`<이름>.<SHA-256 앞 16자>.ndjson`), manifest(`<이름>.manifest.json`)는 현재 게시본을 가리키는 포인터(파일 이름·SHA-256·행 수·`schema_version`·`source_kind`·checkpoint·만든 시각). 데이터 파일을 완성(임시 파일 → 동기화 → 교체 → 폴더 동기화)한 뒤 manifest를 같은 방식으로 교체 — manifest 교체가 실패하거나 동시에 게시해도 manifest가 가리키는 파일은 온전하고 이전 게시가 보존된다. `verify_ndjson <manifest>`(SHA-256·행 수·줄 형식·가리키는 이름이 폴더 안·같은 이름인지). `export_integrity --out DIR`: 세 점검(`ledger_check`·`event_gaps`·`event_delivery`)을 **하나의 MySQL 읽기 스냅샷**에서 읽어 게시, checkpoint는 범위 서술(스냅샷 종류·시작 시각·원천별 훑은 행 수), 문제가 있으면 비정상 종료, MongoDB 오류면 아무것도 게시하지 않음. 백필 실행 명령은 만들지 않음 |
| 4-1f 부하·장애 시험의 이벤트 검증 | 완료 (2026-10-10, 외부 검토 보완 반영) | `load_test`: 실행마다 무작위 이름의 MongoDB 데이터베이스(끝나면 그 이름만 삭제)와 상시 중계 2개. `verify_events` 검증 범위 — **원본 ↔ outbox: 이름·메시지 키·봉투(`schema_version`, 생성 시각 `produced_at`)·페이로드 전체 / outbox ↔ MongoDB: 문서 전체**: ① 원본 행 ↔ outbox — 이벤트가 정확히 하나씩(빠짐·남음 모두 실패), 원본 행에서 독립적으로 다시 만든 이벤트와 JSON 타입까지 같음 ② 중계가 끝나면 미전송 0, MongoDB ID 집합 = outbox, MongoDB 문서 전체 = outbox. outbox와 MongoDB를 같은 잘못된 값으로 바꿔도(봉투 포함) ①이 잡는다(처음 검사기는 ID 집합만, 다음 판은 봉투의 원본 대조가 없었다 — 외부 검토 `8e25f03`·`10a8808` P2). `failure_test`: 임시 MongoDB 레플리카셋을 함께 띄우고 모든 시나리오에 상시 중계 2개, 새 시나리오 `mongo-restart`·`relay-kill`. 대조: 중계를 일하지 않는 프로세스로 바꾸면 미전송 3052건·MongoDB 불일치로 실패. **최종 기준 커밋 `d05d681`**: `scripts/check.sh` 게이트 통과(시험 915개), 150 동시·`crash`·`mongo-restart` 재실행 통과(구현 세션). **문서 세션 측정(2026-10-10, 코드 `10a8808`, 봉투의 원본 대조 전)**: 150 동시 모든 불변식 충족(상시 중계만으로 미전송 0, 내용 대조 통과, 결정 요청 질의 9 → 10개, 결정 p95 1.56초·반응 p95 1.60초, 일시 오류 503 2건은 재시도로 수신 확인), 장애 시험 5개 시나리오 모두 통과(`mongo-restart` 요청 1260건 중 503 0·미전송 최대 191건 → 0, `relay-kill` 이벤트 내용까지 일치) — `load-test.md` §2·§7 |
| 4-1e 중계 | 완료 (2026-10-10) | `relay_events`: 미전송 행을 `FOR UPDATE SKIP LOCKED`로 오래된 것부터 잡아 `insert_many(ordered=False)`, 같은 `_id`·같은 내용은 통과·다른 내용은 덮어쓰지 않고 멈춤(충돌하지 않은 것은 표시해 커밋), 중복이 아닌 쓰기 오류는 숨기지 않음, `produced_at`은 밀리초로 잘라 저장·비교. 상시 실행은 DB·MongoDB가 끊겨도 점점 길게 쉬며 재시도, SIGTERM 정상 종료, `--once`·`--status`. `purge_sent_events`(보낸 지 7일 지난 행만, 미전송은 지우지 않음). 시험 16개(변형 검사 10건 중 9건 검출, 나머지는 SQL 의미상 같은 변형) |
| 4-1d 과금 이벤트 | 완료 (2026-10-10) | 원장 `CHARGE` 한 줄마다 `ad.charge`를 과금과 같은 트랜잭션에서. `decision_id`는 원장에 열을 더하지 않고 처리 중인 반응의 결정에서(DRD D-6 해결, 설계 §10 "Step 4 이벤트 결정" E1). `requested = charged + shortfall`, 예산 일은 원장 시각 기준, 지갑 잔액·광고주 계정은 싣지 않음. 과금이 없는 반응은 이벤트 없음, 다시 처리해도 한 줄, outbox 쓰기가 실패하면 과금·판정이 함께 되돌려짐. 시험 6개(변형 검사 5건) |
| 4-1c 접수·판정 이벤트 | 완료 (2026-10-10) | 접수(`ad.reaction_received`)는 수신 행과 같은 트랜잭션(매체 보고·서버 관측 클릭 모두, 보고된 사실과 원문만, 재전송은 이벤트를 더하지 않음). 판정(`ad.reaction`)은 `processing._finish`에서 같은 트랜잭션(인정·거부 모두, `basis`를 그대로, `person_id`·`audience`는 `basis`에서, 보류는 이벤트 없음). outbox 쓰기가 실패하면 접수는 저장되지 않고(2xx 없음) 판정은 되돌려짐(`RECEIVED`, 과금 없음). 시험 12개(변형 검사 6건) |
| 4-1b 결정 이벤트 | 완료 (2026-10-10) | `decide()`가 결정 저장과 outbox 쓰기를 한 트랜잭션으로: C1 뷰가 연 트랜잭션 안이면 그대로(저장점·질의 추가 없음), 직접 부르면 스스로 연다. 광고 없음도 이벤트(`selected = null`), 일괄 슬롯은 `subject_id = null`, 입찰가와 적용 금액을 따로, 광고주 계정은 싣지 않음. outbox 쓰기가 실패하면 결정도 저장되지 않고 503. 시험 11개(변형 검사 6건) |
| 4-1a 이벤트 outbox | 완료 (2026-10-10) | `events_outbox`(PK = 이벤트 ID, 원천 ID·이벤트 종류에서 UUIDv5로 결정적으로, `aggregate_id` = `decision_id`, `payload` JSON, `created_at` = `produced_at`, `sent_at`, 색인 `(sent_at, created_at)`). 트랜잭션 밖 쓰기 거부, 같은 이벤트는 한 줄(`ON DUPLICATE KEY UPDATE` 무변경, `INSERT IGNORE`는 STRICT의 다른 오류를 삼켜 쓰지 않음). `events/schemas.py`가 필드 이름·형식을 한 곳에서 정함. 결정 4건(E1~E3·이벤트 ID)은 설계 §10 "Step 4 이벤트 결정". 시험 11개(변형 검사 7건). Step 4 전체 시험 897개 + `check.sh` 통과(구현 세션) |
| 외부 검토(`f2e930b`) 후속 | 완료 (2026-10-09) | P2 2건(구현 `92f95ea`). ① **정합성 검사의 진입 조건**: 트랜잭션 밖에서 부르거나, 동시에 쓰는 연결이 없다는 호출자 보장이 있을 때의 `quiescent=True`만 허용한다. **세션 격리 수준은 판단 근거로 쓰지 않는다** — 세션 값이 `REPEATABLE READ`라도 `SET TRANSACTION`으로 그 트랜잭션만 `READ COMMITTED`로 시작할 수 있어 거짓 불일치가 재현됐다. 그래서 세션 값과 무관하게(RC·RR·SERIALIZABLE) 기존 트랜잭션 안에서는 `ConsistentReadUnavailable`로 거절한다. 설계 §10 "소진액 재계산 규약" ⑥. ② **장애 시험의 복구 판정**: 접수 직후 처리를 끄고 별도 처리 명령 없이, 복구 뒤 상시 처리 프로세스만으로 대기열이 비워지는지와 복구 뒤 실제 처리 건수 > 0을 판정한다. 대조 실험(일하지 않는 프로세스)에서는 남은 759건·처리 0건으로 실패한다. 문서 세션 재측정(코드 `92f95ea`): 세 시나리오 통과, 복구 뒤 상시 프로세스 처리 568·532·503건, 남은 대기열 0(`load-test.md` §7). 전체 시험 + `check.sh` 통과 |
| 리팩터링 0~6단계 | 완료 (2026-10-10) | **동작 변경 없음**, 아래층부터 차례로(`3538d46`~`a71331c`). 0단계 `3538d46`: 합칠 코드의 동작을 먼저 고정하는 특성 시험 3개(일괄 조회는 형식이 틀린 ID를 버린다, 프로젝트 모델의 관리자 화면은 읽기 전용), 변형 검사 4회. 1단계 `b11178f`(foundation): 공용 도우미 `require_admin`·`require_advertiser`·`parse_uuids`·`ReadOnlyAdmin`을 `foundation.api`에 두고 옛 별칭·안 쓰는 재수출 정리. 2~3단계 `6e34b1f`·`0a0e733`(masters·engine·assets·events, campaigns·billing): 앱마다 있던 역할 검사·ID 거르기·읽기 전용 관리자 화면 사본을 공용 도우미로(문구 그대로), 안 쓰는 재수출 정리. 4단계 `c57abe5`(records): 결정 저장을 한 번 더 감싸던 트랜잭션 제거로 **결정 POST 질의 11 → 9**(`load-test.md` §2), 이미 정렬된 목록의 재정렬 제거. 5~6단계 `e1017b2`·`a71331c`: 앱별 `default_auto_field`(전역 설정과 중복) 삭제, 안 쓰는 import 정리. 단계마다 시험 806개 + `check.sh` 통과, 마이그레이션 변화 없음 |
| DB-2 MongoDB 연결 | 로컬 완료 (2026-10-10) — 인프라 서버 확인 남음 | 구현 `b01b425`: `pymongo` 4.18, `EVENT_STORE` 설정(`MONGO_*`), `events/`(`ensure_event_store`·`check_event_store`), `scripts/mongo_admin.py`(`check.sh` 사전 점검)·`scripts/mongo_temp_rs.py`(임시 레플리카셋). 시험 16개, 단일 서버와 임시 레플리카셋 양쪽에서 통과. **이벤트는 아직 쓰지 않는다**(Step 4). 상세는 §7.3.3 DB-2 행 |
| DB-1e SQLite 잔재 제거 | 완료 (2026-10-09) | 구현 `f2e930b`: 오류 분류(`foundation.dberrors`)는 MySQL 오류 번호(1062)만, 설정의 SQLite 비교 문구 제거·연결 수 산정(`max_connections`) 사실 기록, `.gitignore`의 `db.sqlite3`·빈 옛 개발 DB 파일 삭제, 시험 설명의 SQLite 언급 제거(문서 제외 `git grep -i sqlite apps/ads_server` 0건). 문서 정리(문서 세션): 설계 §6.5-6·7·저장소 단계·동시성 검증 결과, DRD 저장소·현재 단계 표·구성도, 위협 모델 구성도·잔여 위험 행·T28, `load-test.md`(MySQL 수치·장애 시험), README(부하·장애 시험 실행법)를 MySQL 기준으로. 이력·결정 기록의 SQLite는 그대로 |
| DB-1d 부하·장애(로컬) | 완료 (2026-10-09) — 인프라 서버 항목 남음 | 구현 `554391d`: ① 150 동시 소요가 들쭉날쭉하던 원인(보류분을 5초마다 전부 재판정) → 앞 단계가 끝나면 같은 결정·매체의 보류분을 깨우고 주기 재확인은 30초 안전망, 재기동 처리 284초 → 15.7초·보류 해소 4.8초 → 1.1초·전체 360초대 → 89초(구현 세션 측정) ② 반응 결정 인덱스 `(decision_id, type, status)`(0010) ③ 상시 처리 프로세스가 DB 끊김에도 죽지 않음 ④ 장애 시험 `scripts/failure_test.py`. 전체 784개 + `check.sh` 통과. **문서 세션 재측정(코드 `f2e930b`)**: 150 동시 모든 불변식 충족(연결 한도 503 4건은 재시도로 수신 확인), 장애 시험 세 시나리오 통과(500 0, 유실 0, 이중 과금 0). 복구 판정은 `92f95ea`에서 강화했고 재측정했다(위 "외부 검토(`f2e930b`) 후속" 행) — `load-test.md` §2·§7 |
| 외부 검토(`6fc9664`) 후속 | 완료 (2026-10-09) | P2 1건(구현 `91bb74d`): `consistent_read`가 이미 열린 `READ COMMITTED` 트랜잭션 안에서는 스냅샷 없이 그대로 읽어 같은 거짓 불일치가 났다(`atomic()`이 다른 연결의 커밋을 막는다는 가정이 틀림). 트랜잭션 안에서는 `ConsistentReadUnavailable`로 거절(세션 격리 수준에 따른 허용 분기는 `92f95ea`에서 없앰 — 위 "외부 검토(`f2e930b`) 후속" 행). 동시에 쓰는 연결이 없다는 호출자 보장일 때만 `check_ledger(quiescent=True)`(관리 명령 `--quiescent`). 설계 §10 "소진액 재계산 규약" ⑥. 전체 778개 + `check.sh` 통과 |
| 외부 검토(`7aac929`) 후속 | 완료 (2026-10-09) | P2 2건(구현 `6fc9664`, 결과 §7.3.4b "검토 보완 두 번" ②). ① 정합성 검사를 `REPEATABLE READ` 한 읽기 스냅샷에서(사이에 커밋된 정상 과금을 거짓 불일치로 보고하던 것, 전역 격리 수준은 그대로) ② 재계산의 행 조회·잠금을 한 문장으로(겹친 재계산이 행을 지우면 중단되던 것 — 예산 일 경계 변경 절차에서도 재현). 실제 두 연결 시험 3개 + 변형 검사, 25회 반복 무실패. 전체 775개, `check.sh` 통과 |
| DB-1c 동시성 | 완료 (2026-10-09) | 구현 `7aac929`, 결과 §7.3.4b. ① **S5** `READ COMMITTED` 확정(150 동시 부하에서 교착 0·불변식 통과 2회 vs `REPEATABLE READ` 교착 8·불변식 2건 실패) ② **S6** 교착·잠금 대기 초과는 일시 오류(반응 처리 `attempts` 불변·다음 주기 재시도, 처리 요약에 따로 집계, API는 503) ③ **재계산·과금 경쟁**(검토 DB-1a P2, 원장 30·소진액 10 재현): 소진액 행을 잠근 뒤 원장을 읽고, 과금은 키로 갱신하고 없을 때만 생성, `check_ledger`가 소진액도 대조(설계 §10 "소진액 재계산 규약") ④ 신규 동시성 시험(가입 지급·재검토 요청·한 지갑의 과금/조정/조회·접수와 판정 혼합)과 재계산 경쟁 8개, 동시성 시험 41개 × 30회·위험한 3묶음 × 60회 무실패. 전체 772개, `check.sh` 통과 |
| 외부 검토(`974c28b`) 후속 | 완료 (2026-10-09) | P2 1건(구현 `a139e39`): 접수 잠금이 보고 매체 없이 결정 ID만으로 잡혀, 다른 매체가 남의 결정에 낸 미커밋 보고가 소유 매체의 정상 접수·판정을 막고 잠금 대기 초과(1205) 때 정상 반응의 `attempts`를 올리던 것. **잠금은 소유 매체의 접수에만**: `lock_for_receipt(decision_id, reporting_media_id)`가 잠그기 전 일반 조회로 소유를 확인하고 없는 결정·남의 결정은 잠금 없이 저장, `wait_for_inflight_receipts`는 반응의 매체 = 결정 소유 매체일 때만 기다림(`FOR UPDATE`에 매체 조건만 붙이면 InnoDB가 조건 평가 전에 잠가 대기가 남음 — 시험이 이 변형을 실패시킴). 실제 연결 시험 5개(잠금 대기 제한 1초에서도 `attempts` 0, 없는 결정은 잠금 없음, 소유 매체끼리는 여전히 줄을 섬) + 변형 검사 3종, 전체 752개, `check.sh` 통과. DRD·설계의 접수 서술 정정("짧은 INSERT 한 번"·"결정을 조회하지 않는다" → 소유 확인 조회 + 소유 매체의 잠금 + INSERT, 존재·소유를 이유로 거절하지 않음) |
| 외부 검토(`0b23b86`) 후속 | 완료 (2026-10-09) | P2 1건(구현 `974c28b`): 더 이른 수신 시각의 접수가 커밋 전이라 보이지 않는 동안 판정하면 뒤의 반응이 인정 대표로 굳던 경계(검토 재현: 앞 노출이 `duplicate_type`으로 거부되고 클릭 거부·정상 과금 누락). **접수·판정 순서 규약**(`records/ordering.py`, 설계 §10 "반응 판정 세부" ⑪): 접수는 결정 행을 잠근 뒤 시각을 정해 커밋까지 쥠, 판정은 시작 전에 같은 잠금을 지나가 진행 중인 접수를 기다림(클릭은 클릭 기간 안의 이후 결정도), 결정 ID 순 잠금으로 교착 없음, 다른 결정은 막지 않음. 시계 전제와 판정 쪽 잠금 대기 초과 처리는 DB-1c 완료 조건으로. 실제 MySQL 연결을 스레드마다 하나씩 둔 시험 7개 + 변형 검사 7종, 전체 747개, `check.sh` 통과 |
| 외부 검토(`3cc540f`) 후속 | 완료 (2026-10-09) | P2 3건(구현 `0b23b86`). ① **중복 반응의 대표 선택을 처리 순서와 무관하게**: 같은 판정 단위·유형의 대표는 먼저 접수된 유효한 반응이고, 먼저 접수된 같은 유형이 처리 전이면 `once-per-type`이 보류(설계 §10 "중복 반응의 대표 선택", 알려진 한계: 먼저 접수된 것이 `stuck`이면 뒤의 것도 보류). 부하 시험 C 단계는 보류가 풀릴 때까지 기다림 ② `daily_report` 반응 집계를 **SQL 한 번**으로(분자·분모를 따로 읽으면 사이 커밋으로 전환율 2.0 — 두 연결로 순서를 고정한 시험) ③ DB-1b 마이그레이션의 **기존 데이터 사전 검사**(모든 DDL 전, 자동 삭제 없음). 시험 11개, 전체 740개, `check.sh` 통과 |
| 2-13 보완 | 완료 (2026-10-09) | 외부 검토(`4f00598`) P2 2건(구현 `3cc540f`). ① 없는 결정의 `basis.person`은 `null`(보고된 사람은 `basis.reaction.reported_subject_id`에만) ② 앞 단계를 인정 근거 `prerequisite_accepted`(최대 1개, 항상 저장)와 처리 전 후보 `prerequisites_waiting`(상한 + 총 개수)로 분리, `basis` `v` 1 → 2. 시험 4개 + 변형 검사 9종 |
| 2-13 판정 사실의 매체 격리·판정 근거 기록 | 완료 (2026-10-09) | 외부 검토(`65331e8`) 후속, 설계 §10 "판정 설계 기준"·"판정 사실의 범위"·"판정 근거 기록". ① 판정 사실로 읽는 모든 반응을 `records/facts.py scoped_reactions` 하나로 묶음(결정 소유 매체의 반응, 개인 슬롯은 + 보고된 사람이 없거나 결정의 사람, 접수 때 정해지는 값으로만 거름). 표시 교체 신호는 `display_signal`(이전 `next_display_at`) ② 구조 검사 `tests/boundaries/test_judgment_scope.py`: `facts.py`가 반응 모델에 닿는 곳은 이 함수 하나, `basis`는 처리 단계에서만 씀 ③ `records_reaction.basis`(마이그레이션 0009): 판정과 같은 UPDATE로 한 번, 보류에는 없음, DB `CHECK`(판정한 행 ⇔ 근거), 이전 판정 행은 `v: 0` "기록 이전". MySQL·SQLite 양쪽 마이그레이션 확인. 회귀 시험 6종 + 변형 검사 14종, 테스트 727개, `check.sh` 통과(구현 커밋 `57a50f1`) |
| 2-12 외부 검토 후속(정의 변경 2건) | 완료 (2026-10-09) | ① **표시 종료 = 이후 결정의 첫 노출 도착 + 5초**: `facts.next_display_at`이 같은 표시 단위(개인 슬롯 = 슬롯·사람, 일괄 슬롯 = 슬롯)의 이후 결정에 접수된 노출 중 `received_at` 최솟값을 질의 한 번으로 구한다(노출은 처리 전·거부여도 센다, 노출 없는 결정은 무시). 응답을 못 받아 적용하지 못한 결정이 기존 광고의 클릭을 `display_ended`로 끊지 않는다. ② **전환율 = 클릭 코호트**: `ReportTotals.converted_clicks`(구간에 받은 인정된 클릭 중 같은 (결정, 사람)의 인정된 전환이 있는 클릭 수, 전환이 구간 뒤여도 조회 시점에 셈)를 추가해 `conversion_rate = converted_clicks / clicks`(≤ 1), 질의 +1, C6 `Totals`·`DailyReportRow`에 `converted_clicks`. 시험: 다음 결정만 있고 노출이 없으면 인정·노출 도착 + 5초(경계 포함, 1마이크로초 뒤 거부)·여러 이후 결정 중 가장 먼저 도착한 노출·처리 전/거부 노출·이전 결정/다른 사람/다른 슬롯은 무관·일괄 슬롯은 누구의 노출이든·질의 1회, 이전 기간 클릭의 전환이 있어도 전환율 ≤ 1·구간 뒤 전환도 코호트에 셈·거부·보류 전환은 안 셈·일괄 슬롯은 자기 클릭의 전환만·일별 합 = 합계·다른 광고주 불포함. 변형 검사 10종(첫 노출→마지막 노출, 상태 필터 추가, 이후 결정 범위, 사람 범위, 경계 부등호, 노출 시각 −1초, 전환율 분자, 사람 일치, 날짜 기준, 코호트 합)을 시험이 9종 잡았고 하나(전환의 `ACCEPTED` 필터 제거)는 `person_id`가 인정 때만 채워져 동등 변형이다 |
| DB-1b 제약·SQL 재설계 | 완료 (2026-10-09) | 조건부 유일 제약 3곳을 MySQL용으로: `billing_charge_once_per_reaction` = 조건 없는 `UNIQUE(reaction_ref)`(NULL 끼리 다름), `billing_one_signup_grant_per_wallet`·`campaigns_one_open_review_per_campaign` = **DB가 계산하는 열**(`GeneratedField`: 가입 지급 줄에만 지갑 ID / 열린 요청에만 캠페인 ID, 나머지 NULL) 위의 유일 제약 → `W036` 경고 0, 상태를 바꾸는 코드는 그대로. 마이그레이션 `billing 0003`·`campaigns 0003`. `records 0007`: **멈출 수 있는 검사를 첫 작업으로**(사람을 알 수 없는 행·같은 키 중복 → MySQL의 DDL은 되돌릴 수 없으므로 스키마를 바꾸기 전에 멈춘다. 같은 DB에서 정리 뒤 재실행 시험 추가). 시험: 원시 SQL을 MySQL 문법으로(`%s`, `ALTER TABLE … DROP INDEX`, 제약을 빼는 시험은 암묵적 커밋 때문에 `TransactionTestCase`에서 하고 반드시 되돌림), 음수 잔액은 `IntegrityError`/`DataError` 둘 다 인정하되 값 불변 확인. **전체 시험 692개 MySQL에서 통과**. 변형 검사: 계산 열의 조건을 바꾸면(OPEN→CLOSED, SIGNUP_GRANT→TOPUP) 시험이 실패, 0007 검사를 뒤로 옮기면 실패 |
| DB-1a 준비 | 완료 (2026-10-08) | `mysqlclient~=2.3.0`, `DATABASES`를 `DB_*` 환경변수 기반 `mysql_config`로(strict·`READ COMMITTED`·utf8mb4·`_as_cs`), 시험·부하·`check.sh`가 MySQL 8.4 컨테이너(`intake/db-standalone`)를 쓰고 **없으면 명확히 실패**(`scripts/mysql_admin.py`), 설정 시험 정리·`MysqlSessionTests`(T25 커밋 내구성 포함), README "MySQL 시험 환경". **실패 목록 §7.3.4a 작성**(조건부 유일 제약·원시 SQL·오류 종류·비트랜잭션 DDL). 소규모 부하 시험은 MySQL에서 불변식 통과 |
| 2-9·2-11 후속 보완 | 완료 (2026-10-08) | 외부 검토(`180a147`) P2 4건. ① **기한 뒤에 도착한 노출이 보류된 클릭을 되살려 과금**(클릭 t+1 보류, 노출 t+302 인정, t+303 재판정 → 클릭 인정·원장 −30) ② **클릭보다 먼저 접수된 전환이 나중 클릭으로 소급 인정**(전환 t+1 보류, 클릭 t+200, t+201 재판정 → 전환 인정·원장 −30) — 둘 다 재현 시험으로 실패를 확인한 뒤, 순서·기한 판정을 "지금 인정돼 있는가"에서 **앞 단계의 도착 시각**(클릭의 노출은 클릭 접수 + 300초 안, 전환의 클릭은 전환 접수 시각까지)으로 바꿈. 같은 코드가 반대 방향 결함도 갖고 있었다: 제때 도착했는데 처리만 늦은 앞 단계 때문에 정상 반응을 거부 → 제때 도착한 처리 전 앞 단계는 **보류**로 바꿈. 사실 수집(`prereq_accepted`·`prereq_waiting`)과 규칙 `funnel-order`·`funnel-window` 수정. ③ **`0007`이 일괄 슬롯의 기존 인정된 클릭을 이행하지 못함**: 사람의 출처를 슬롯 성격으로 선택(개인 = 결정, 일괄 = 반응의 `subject_id`), 사람을 알 수 없는 행은 임의로 채우지 않고 명확한 메시지로 멈춤 — 이행 시험 2개 추가 ④ **비동기 ReplicaSet에서 커밋 후 2xx만으로 failover 유실을 막는다는 서술**: 계획된 전환과 원본 장애 뒤 강제 failover를 구분하고 "수신 2xx의 약속은 노드 하나의 내구성까지"로 정정, DB-1d에 확인한 ID 생존 검사, 허용 유실 범위·복구 절차 결정을 사람의 일(7.3.4 #6)로. **부하 검사기**가 같은 기준(도착 시각)으로 늦게 도착한 노출·소급 전환·전환 기간 초과를 대조(두 금전 사례가 검사기에 잡힘, 변형 검사). 오래된 요약 정리(§7.2 머리말, `load-test.md`, DRD 엔터티 수). 새 시험 15개, 변형 검사 15종(동등 변형 1개 제외). 테스트 671 → 686 |
| 2-9 보완 | 완료 (2026-10-08) | 외부 검토 3건. ① **"(결정, 사람, 유형)당 인정 1건" 안전망이 MySQL에서 사라지던 것**(결정): 조건부 유일 제약(`WHERE status = ACCEPTED`)은 MySQL·MariaDB가 지원하지 않아 처리 프로세스 2개의 동시 판정이나 `once-per-type` 설정 누락 때 이중 과금을 막는 마지막 장치가 없어짐 → 인정된 행에만 `accepted_key`(`<결정>:<사람>:<유형>`)를 채우고 나머지는 NULL, **조건 없는 `UNIQUE(accepted_key)`** + `CHECK`(인정 ⇔ 키 있음)로 교체(NULL 끼리는 서로 다른 값이라 SQLite·MySQL·PostgreSQL에서 같게 동작, `person_id`의 `CHECK`는 이 키가 대신함, 인정 직전 사람이 없으면 오류). 같은 종류의 조건부 유일 제약 3곳이 더 있음을 확인해 전환 점검 항목으로 기록(설계 §10 "MySQL 전환 점검") ② 마이그레이션 `0007`이 이미 인정된 행이 있는 DB에서 실패하던 것: 새 제약 전에 기존 인정 행의 사람(결정의 사람)과 키를 채우는 단계를 넣고 `tests/test_migrations_funnel_backfill.py`로 고정(단계를 빼면 실패 확인) ③ 보류는 처리 프로세스가 떠 있어야 풀린다는 운영 전제를 설계 §10에 명시하고 2-11 부하 재측정에 "보류 해소 지연" 추가. 테스트 654 → 655 |
| 2-9 반응 판정 확장 | 완료 (2026-10-08) | 규칙 6개 추가(`click-source`·`subject`·`occurred-at`·`campaign-open`·`funnel-window`·`funnel-order`, 새 사유 8개; `viewer-limit`은 만들지 않음)와 **보류**(`RECEIVED` 유지·`attempts` 불변·`checked_at`, 재확인 간격 5초, 기한 300초 뒤 `missing_prerequisite`). 판정 단위는 개인 = 결정, 일괄 = (결정, 사람): 인정할 때 `person_id`를 확정해 저장하고 유일 제약을 (결정, 사람, 유형)으로 확장(인정된 행에 `person_id` `CHECK`), 반응 요청 `subject_id`(저장·재전송 비교·응답). 사실 수집은 `records/facts.py`(읽기만, 질의 수는 다른 반응 수와 무관), 필수 조건(`guard`)을 `MANDATORY_RULES`(결정·매체·광고·클릭 출처·사람·종료 전 수신)로 넓힘, `campaigns.api.campaign_end_times`, 결정 인덱스 `(slot_id, subject_id, decided_at)`, 마이그레이션 `records/0007`. 계약: 반응 `subject_id` 필수. **설계 문구와 다르게 한 두 곳**(설계 §10 "반응 판정 세부" ⑤): ① 처리 전 `RECEIVED`는 "있음"이 아니라 의존 반응을 보류(인정된 전환 뒤에는 항상 인정된 클릭) ② `occurred_at` 하한에도 허용 오차(부하 시험에서 같은 초 안의 정상 노출이 전부 거부되는 것으로 발견). 부하 시험·검사기를 새 규칙에 맞추고 퍼널 불변식 추가(변형 6종). 새 시험 `tests/test_funnel_rules.py` 42개(종단 3개 포함)·검사기 시험 7개, 변형 19종(살아남은 `Coalesce` 정렬은 불필요해 제거). 노출 없는 임의 `?s=` 클릭이 거부되는 시험(검토 2-8 #3) 포함. 위협 모델은 2-11. 테스트 605 → 654 |
| 2-8 보완 | 완료 (2026-10-08) | 외부 검토 4건. ① **매체가 서버 관측 클릭을 지울 수 있던 것**(중간): 클릭 ID가 소스의 공개 이름공간 `uuid5`라 매체가 같은 ID로 아무 반응이나 먼저 접수시키면 진짜 클릭이 "중복"으로 조용히 버려짐 — 재현 시험(클릭 0건) 후 ID를 `SECRET_KEY` HMAC(UUID v8)으로 바꾸고, 중복 판정을 출처가 `server`인 행으로 좁혀 같은 ID의 매체 행은 오류로 기록(안전망). 검토의 유일 제약 `(매체, 출처, ID)` 안은 과금 멱등 키 `reaction_ref`에도 출처가 필요해져 채택하지 않음 ② 개인 슬롯 토큰에서 `subject_id` 제거(가명 ID가 URL·기록·로그에 드러나던 것, 코드·시험 감소, 계획·설계·계약 문서 맞춤) ③ 2-9 시험에 "노출 없는 사람의 임의 `?s=` 클릭 거부"를 필수로 명시 ④ `ASSET_PUBLIC_BASE_URL` 공용 결정을 설계 §10에 기록(이미지를 옮길 때 `click_url`용 설정 분리), `clicks.py`의 문자열 비교를 `masters.Audience`로. 새 시험 3개·변경 시험 정리, 변형 4종. 테스트 603 → 605 |
| 2-8 클릭 관측 | 완료 (2026-10-08) | `GET /c/{token}`(`serving_api/clicks.py`, 루트 경로, 인증·쿠키 없음, GET 만): Django `signing` 토큰(서명된 `decision_id`뿐), 결정 응답 `ad.click_url`(계약 `required`로, 일괄 슬롯은 `?s={subject_id}` 자리). `records.observe_click`: 유효 토큰은 **항상 302 → 결정 스냅샷의 `redirect_url`**(요청 값과 무관), 위조·변조·없는 결정·광고 없던 결정은 404, 클릭은 수신함에 `CLICK`으로 기록(`reaction_id` = 서버 비밀 HMAC(결정/사람)으로 중복 1건, 시각 = 서버 수신). `records.Reaction`에 `source`(`media`·`server`)·`subject_id` 열 추가(마이그레이션 `records/0006`; 계획의 `source`에 더해, 일괄 슬롯 클릭의 사람을 남기려고 `subject_id`도 지금 추가 — 매체 보고의 `subject_id`는 2-9). 일괄 슬롯은 `?s=` 없음·형식 오류면 이동만, 기록 실패·처리 실패는 이동을 막지 않고 로그. 저장소 장애로 이동할 곳을 모르면 503. 계약: `Ad.click_url` 필수(`format: uri` 대신 패턴, `{subject_id}` 자리 때문), 예시 `sharedWithAd`, `/c/{token}`에 503. 새 시험 `tests/test_click_observation.py` 22개(302·헤더·쿠키, 열린 리다이렉트 없음, 위조 11종, 중복 1건, 일괄 슬롯 사람별·형식 오류, 기록/처리 실패, HEAD/POST 405, 동시 10 클릭 40회 반복), 변형 12종으로 실패 확인, `test_access` 공개 목록에 `/c/` 등록. 위협 모델은 계획대로 2-11에서 한꺼번에 추가(공개 GET·토큰 위조·미리보기). 테스트 581 → 603 |
| 2-7 보완 | 완료 (2026-10-08) | 설계 결정 변경(§10 "일괄 슬롯 노출 방어": 슬롯별 인원 상한 없음, 사람별 과금 유지, 방어는 이후 광고 서버 쪽 이상치 감지)에 따라 `Slot.max_viewers`·DB 제약·`MAX_VIEWERS`·서비스 검증·감사 상세·관리자 목록·`SlotView` 필드·C6 `Slot.max_viewers`·DRD 열/ERD·관련 시험을 삭제. 마이그레이션: 적용된 DB가 없어(push 전, `db.sqlite3` 비어 있음) `masters/0002`를 `audience`만 추가하는 형태로 다시 만들고 제거용 `0003`은 두지 않음(삭제 이력은 git과 설계 §10). 2-9에서 `viewer-limit` 규칙·`viewer_limit` 사유는 만들지 않는다(계약·계획에서 제외됨). `audience` 동작(변경 불가·`subject_id` 규칙·결정 스냅샷)은 그대로이고 회귀 없음. 위협 모델 T35의 시험 목록 갱신. 테스트 581개 유지(상한 관련 시험 삭제, `audience` 유효성 시험 추가. 열 목록 비교 시험은 슬롯 등급 같은 정당한 열 추가 때마다 깨져 두지 않음 — 결정 근거는 설계 §10). `scripts/check.sh` 통과, `git grep max_viewers`는 마이그레이션 `0002`(역사)와 설계·계획의 결정 기록에만 남음 |
| 2-7 슬롯 성격 | 완료 (2026-10-08) | `masters.Slot`에 `audience`(`individual`·`shared`, 만든 뒤 변경 불가, 기본값 없음)·`max_viewers`(`shared`일 때만 1~100000, DB `CHECK` — `NULL`이 `CHECK`를 통과하는 것을 시험이 잡아 `isnull=False` 명시), `create_slot(..., audience="individual", max_viewers=None)`·`SlotView`·관리자 목록. 결정: `records.decide`가 슬롯을 찾은 **뒤** `subject_id`를 검사(개인 필수·일괄 금지, 400 `/subject_id`; 순서는 슬롯 404 → 매체 비활성 403 → 400), 결정에 `audience` 스냅샷과 사람 유무 `CHECK`, 응답·조회에 `audience`. 계약: C1 `Decision.audience` `required`로, 예시·프레임워크 시험 갱신, **C6 `Slot`에 `audience`·`max_viewers` 추가**(광고주가 슬롯 선택 때 본다). 마이그레이션 `masters/0002`·`records/0005`. 새 시험 `tests/test_slot_audience.py` 16개(모델·서비스·결정·API), 변형 8종(변경 불가 검사·두 방향의 `subject_id` 검사·응답의 `audience`·`max_viewers` 타입/개인 검사·스냅샷 값·검사 순서)으로 실패 확인. 기존 시험의 개인 슬롯 결정에 `subject_id` 보강. 테스트 565 → 581. DRD M2·R1·ER 갱신, 위협 모델 T35 ⑩. **`max_viewers`는 이후 2-7 보완에서 제거** |
| C1 v1.1 결정·계약 | 완료 (2026-10-08) | 반응 퍼널 규칙(순서·클릭을 거친 전환만·기간·표시 중 5초 창), 일괄 슬롯(`audience`·~~`max_viewers`~~ — 이후 2-7 보완에서 제거, 설계 §10 "일괄 슬롯 노출 방어"), 클릭 출처 = 서버 관측(`click_url`, 매체 `CLICK`은 호환용으로 남기되 판정 제외, 이후 대조용 B안 확장 가능), 퍼널 집계는 광고 서버 담당을 설계 §10에 확정. 계약 `1.1.0-draft`(더하기만 하는 변경, 새 응답 필드는 구현 때 필수로). **[정정 2026-10-09]** 이후 "배포 전 계약 교체"로 정정됨 — 응답 필드는 더하기만 했지만 클릭 경로·퍼널 규칙이 바뀌어 1.0대로 구현한 매체와 호환되지 않는다(계약 v1.1 머리말, 설계 §10 "계약 v1.1"). 계약은 2-11에서 `1.1.0`. 슬롯 등급은 설계 §7-12(V1 제외). 구현 계획 §7.2(2-7~2-11, Step 3 전) |
| 2-6 보완 | 완료 (2026-10-08) | 외부 검토 3건(모두 시험 도구): 부하 검사기가 원장 내부 수치만 맞으면 통과 → 각 과금을 결정의 적용 금액(+부족분)·광고주·캠페인·접수 시각·정책과 대조, 수신 확인한 반응의 (매체, 반응 ID)→(결정 ID, 유형) 연결을 저장된 행과 대조(키의 매체 범위 유지), 재전송 시험이 호출마다 `occurred_at`을 새로 만들어 초 경계에서 409가 섞임 → 논리 반응의 ID·본문을 스레드 시작 전에 한 번 만들어 재사용. 변조 사례(금액 31·타 광고주 지갑·타 캠페인·타 접수 시각·타 결정 연결·타 유형)와 부족분의 정상/가짜 구분을 검사기 테스트로 고정, 변형 9종. 게이트에서 발견한 기존 테스트의 간헐 실패(`table is locked`가 재시도 범위 밖의 조회에서 나던 것, 40회 중 1회)도 수정(120회 연속 통과). 테스트 557 → 565 |
| 2-6 동시성 검증 | 완료 (2026-10-08) | `scripts/load_test.py`(임시 파일 SQLite·WAL·`synchronous=FULL`, 실제 미들웨어를 거치는 스레드형 WSGI, 별도 프로세스 `process_reactions`, 계약의 재시도 규칙을 지키는 클라이언트)로 150 동시: 결정 150·반응 150·같은 결정/유형 150(1건만 인정)·같은 reaction_id 150(201 하나)·지속 유입 중 SIGTERM+프로세스 2개+재기동·버스트 초과(429+Retry-After). **수신 확인 전부 저장(유실 0), 이중 과금 0, 잔액=원장 합계, 소진액=원장, 처리 후 `RECEIVED` 0**. 503·재시도 없이 전부 첫 시도 성공. 결정 요청 1건 = 질의 11개, `slot_name` 조회 비용 ≈ 0.1 ms. 요청 제한 수치는 측정 근거로 **유지 확정**. 검사기 자체를 변조 사례로 시험(변형 9종). 시험 중 발견: 처리 프로세스가 신호 처리기 설치 전에는 SIGTERM으로 즉사 → 시작 로그(`started`)를 남겨 준비를 확인. `scripts/check.sh`에 소규모(20 동시) 단계 추가. 결과·한계: [load-test.md](load-test.md). 테스트 548 → 557 |
| 2-5 반응 처리 | 완료 (2026-10-08) | `records/processing.py`(반응 하나 = 트랜잭션 하나: 규칙 → 과금 → 상태), 규칙 체인 `records/rules/`(`known-decision`·`same-media`·**`ad-shown`(추가)**·`once-per-type`, 설정 `REACTION_RULES`, 모르는 이름은 즉시 오류, 규칙을 빼도 근거 없는 보고는 `guard`가 거부), 과금은 결정의 `applied_amount`·`received_at`·`reaction_ref` = `<media_id>:<reaction_id>`(자정 뒤 재처리에서도 접수 일 기준), 같은 결정·유형의 `ACCEPTED`는 DB 부분 유일 제약, 처리 실패는 되돌리고 `attempts` 증가·한도 초과는 `stuck`으로 보고(자동 거부 없음), 수신 직후 한 번 바로 처리(실패해도 접수 응답 불변), 관리 명령 `process_reactions`(`--once`·`--interval`·`--batch`·`--retry-stuck`, 동시에 여러 개 안전). 소스 검사: 과금 호출·반응 상태 변경은 `processing.py`뿐. 테스트: 규칙별·원자성(과금 뒤 실패 롤백)·멱등·자정 뒤 재처리·큐 격리·동시 처리 2개·수신 직후 처리, 변형 검사 11종. 테스트 514 → 543. 위협 모델 T37. **검토 보완(같은 날)**: `same-media`를 설정에서 빼면 타 매체의 보고가 다른 광고주에게 과금되던 것(P1: 결정 존재·매체 소유·광고 있음을 규칙 설정과 무관한 필수 조건 `guard`로 강제, 교체 가능한 정책과 구분해 문서화), SIGTERM 뒤에도 큐를 다 비울 때까지 처리하던 것(반응 사이·배치 사이에서 종료 확인, 남은 것은 `RECEIVED`로 두고 재기동 뒤 재개), `--batch 0` 무한 반복과 옵션 검증 전에 `--retry-stuck`이 상태를 바꾸던 것(옵션을 모두 검증한 뒤 변경, `CommandError`). 조건부 유일 제약의 MySQL 미지원은 전환 시 점검 항목으로 기록. 테스트 543 → 548. 2-6 부하 항목에 같은 결정·유형을 서로 다른 반응 ID로 동시 보고, 지속 유입 중 SIGTERM, 재기동 후 재개 포함 |
| 2-4 반응 수신 | 완료 (2026-10-08) | `records.Reaction`(수신함: `UNIQUE(media_id, reaction_id)`, 원문 `raw` 보존, `RECEIVED`로 시작, 유형·상태·사유 `CHECK`), `PUT .../reactions/{reaction_id}`(**처음 201 / 같은 내용 재전송 200 / 다른 내용 409**, 다른 매체의 같은 ID는 충돌 없음, 없는·남의 결정에 대한 보고도 접수), `GET`(만든 매체·해당 결정 아래만, 아니면 같은 404). **2xx = 커밋됨**: 저장을 바깥 트랜잭션 안에서 하고 커밋 뒤에만 응답(저장·조회·커밋 실패는 503 + `Retry-After`, 재시도하면 처음 접수). 유일 제약 충돌 안전망, 유일 제약 외 무결성 오류는 숨기지 않음. 요청 검증(유형 enum·RFC 3339 UTC 시각·추가 속성 금지·경로 ID 400). 테스트: 계약 대조, 실제 커밋 실패, 스레드 동시 요청(같은 키 10개 → 201 하나, 충돌 요청 9개 → 승자 하나, 서로 다른 20개 전부 저장), 변형 검사 12종. 테스트 480 → 506. 위협 모델 T36. **검토 보완(같은 날)**: 소수 초 7~9자리를 6자리로 절삭해 다른 시각을 같은 재전송(200)으로 인정하던 것(6자리까지만 받고 초과는 400, 계약 `DateTimeUtc`에 문법 명시, 응답은 보낸 정밀도 유지), 시각 정규식의 `\d`가 전각·아라비아 숫자를 받던 것(ASCII 제한, 구현과 계약이 같은 입력을 받는지 대조하는 테스트), 기존 행이 있으면 CHECK 등 다른 무결성 오류도 중복으로 처리하던 것(유일 제약 충돌일 때만). 테스트 506 → 514 |
| 2-3 결정 API | 완료 (2026-10-08) | `POST /decisions`(201 + `Location`, 저장한 뒤에만 응답, 저장 실패 503), `GET /decisions/{id}`(본인 매체만, 형식 틀린·없는·남의 ID는 같은 404), `GET /health`(인증·저장소 접근 없음). 실제 URL `/api/media/v1/` 마운트(`serving_api.views`·`requests`·`urls`), 요청 본문 검증(필수·UUID·추가 속성 금지, 오류를 한 번에 보고). **DRD D-1~D-3 반영**: 꺼진 슬롯은 광고 없음으로 기록·비활성 매체 403·없는/남의 슬롯 404, `context` 저장(50개·4 KiB 바이트·깊이 4·직접 식별자 키 금지), `slot_name`은 응답 때 조회. 모든 응답을 계약에 대조하는 테스트 + 변형 검사 12종(각 규칙을 끄면 실패). 테스트 446 → 474. 위협 모델 T35. **검토 보완(같은 날)**: `context`의 짝 없는 서로게이트가 500이던 것(공통 `parse_json`에서 키·값·중첩 모두 400), 저장 뒤 `slot_name` 조회 실패가 "저장하지 않았다"는 503과 달리 결정을 남기던 것(저장과 응답 조립을 한 트랜잭션으로, 실제 커밋 테스트 포함), 조회 경로가 계약 밖 UUID 표기를 받던 것(같은 404). 변형 검사 5종 |
| PK 규칙 적용 | 완료 (2026-10-08) | 모든 모델의 PK를 UUIDv7로(자동 증가 없음), 버전 행·원장·결정은 UUID 식별자가 PK가 됨, 새 PK 열(`attempt_id`·`log_id`·`ad_group_slot_id`·`creative_image_id`·`wallet_id`·`spend_id`). 원장 `seq`(+`UNIQUE(wallet, seq)`)와 점검·커서 전환, 관리자 정렬은 시각 열. 마이그레이션을 앱별 새 `0001`로 재생성(옛 데이터 복구 단계·테스트 2개 제거). 모델 규약 테스트 추가. 변형 검사 3종(점검의 `seq` 검사·`seq` 계산·PK 기본값). 테스트 443 → 446. DRD D-8 해결 |
| 2-2 매체 인증·요청 제한 | 완료 (2026-10-07) | `masters.MediaKey`(평문 미저장, 발급·유예 교체·즉시 폐기, 감사), `serving_api.auth.media_endpoint`(401+challenge·403·429, 인증 → 요청 제한 → 뷰), 토큰 버킷(프로세스 메모리 한계 명시), `media_key` 관리 명령. 계약 경로의 임시 뷰로 4개 operation의 401·403·429를 계약에 대조. 변형 검사 5종(상수시간 비교·비활성 검사·`WWW-Authenticate`·폐기 키 허용 등) 확인. 테스트 407 → 439(+32). 위협 모델 T34. **검토 보완(같은 날)**: 토큰 버킷이 시각을 잠금 밖에서 읽어 처리 순서가 뒤바뀌면 같은 경과 시간을 두 번 충전(시각 조회부터 저장까지 한 임계 구역으로, 순서 역전 회귀 테스트), 인증 저장소 장애(`OperationalError`)가 500이던 것을 인증·뷰 전체를 감싸는 데코레이터에서 503 + `Retry-After`로 변환(`OperationalError`만, 다른 예외는 가리지 않음), 키 거절 로그 테스트가 비밀값 첫 글자가 `A`일 때(1/64) 정상 키를 만들어 실패하던 것, Bandit 대상에 `serving_api` 추가(`assert` → 명시적 설정 예외), 라이브러리 표 열 수 정리 |
| 2-1 계약 확정 | 완료 (2026-10-07) | 계약 응답 규칙 충돌 해소(2-2의 403 ↔ 2-3의 201), C1 `POST /decisions` 404 추가, 필수 헤더 표시, 요청 제한·전환·title 확정, C3 공유 파일 규칙. 계약 파일 검증·응답 검증 틀(`tests/contract_support.py`, `format` 검사 연결) + C3 provider 계약 테스트. **Step 1 마이그레이션 보완**: 교체된 과거 이미지의 보유 관계를 과거 결정·감사 로그로 복구(records 0003). 테스트 376 → 400(+24). **검토 보완(같은 날)**: 조회 두 API의 403 계약 누락, 쿠키 금지 검사가 `response.cookies`를 놓침, Problem 본문 `status` ≠ HTTP 상태 허용, 401 `WWW-Authenticate` 필수화·형식 확정, 304·204 본문 금지 검사, `Retry-After`는 ASCII 숫자만(각각 변형 검사로 실패 확인). 테스트 400 → 407(+7) |
