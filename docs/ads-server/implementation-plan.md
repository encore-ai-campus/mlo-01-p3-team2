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
  models.py                    # + SignupAttempt (IP, 시각) — 6-5b에서 지움
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
3. **가입 시도 제한** — **6-5b에서 제거**(설계 §10 "가입 시도 제한", §8.4.6. 아래는 0-2 때의 계획): `SignupAttempt(ip, created_at)` 행을 남기고, 최근 1시간 안의 시도가 `SIGNUP_MAX_PER_IP_PER_HOUR`(기본 5, 설정값, 설계 §7-5)를 넘으면 429. 오래된 행은 가입 처리 중 기회가 될 때 삭제(별도 스케줄러 없음). 프로세스가 여러 개여도 일관되도록 **메모리 캐시가 아니라 DB**를 쓴다.
4. **로그인 잠금(axes)**: `AXES_FAILURE_LIMIT = 5`, `AXES_COOLOFF_TIME = 5분`, **아이디+IP 조합**으로 잠금(설계 §5.1). 백엔드 `AxesStandaloneBackend`를 `ModelBackend`보다 앞에 두고 미들웨어를 등록한다. 잠긴 사용자에게는 "5분 뒤 다시 시도" 안내 화면을 보여준다.
   - **IP 판정**: 기본은 `REMOTE_ADDR`만 신뢰한다. 리버스 프록시 뒤에 둘 때는 **신뢰할 프록시 수를 명시**한다(6-5c부터 prod는 필수·1 이상 — 앞단 nginx). 그렇지 않으면 `X-Forwarded-For` 위조로 잠금을 피할 수 있다.
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
| | `test_signup_rate_limit_per_ip` | 한도 초과 시 429, 다른 IP는 영향 없음 — 6-5b에서 지움(제한 제거, 대신 `test_signup_has_no_attempt_limit_even_from_one_ip`) |
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
| `test_advertiser_cannot_open_admin_area` | 404 (6-6에서 지움 — 모든 관리자 경로를 보는 `test_admin_pages_are_hidden_from_anonymous_and_advertisers`가 대신한다) |
| `test_admin_cannot_open_advertiser_area` | 403 (6-6에서 지움 — `test_advertiser_pages_send_anonymous_to_login_and_refuse_admins`가 대신한다) |
| `test_admin_url_default_rejected_in_prod` | 기본 `admin/`이면 기동 실패 |
| `test_owned_or_404_hides_others_objects` | 광고주 A가 B의 객체를 요청하면 404 |
| `test_every_url_is_protected_or_marked_public` | URL 전수 점검 |
| `test_signup_cannot_escalate_role` | 0-2와 중복 확인 (6-6에서 지움 — 0-2의 `test_signup_ignores_role_field`가 세 필드를 직접 본다) |

**완료 증거**: 테스트 통과, 광고주 계정으로 관리자 경로 접근 시 404, 새 URL 추가 시 전수 점검이 잡는 것을 의도적으로 확인.

## 0-4. HTTP 계층 보안

**산출물**: `foundation/http.py`(JSON 파싱 헬퍼·표준 오류 응답), `foundation/middleware.py`(요청 접두사 CSRF 예외, `no-store`), `config/settings/prod.py`의 보안 설정, 오류 템플릿(`400/403/404/500`), `tests/test_http_security.py`

**할 일**

1. **보안 헤더**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, HSTS(prod, TLS 종단이 프록시면 `SECURE_PROXY_SSL_HEADER`), `SECURE_SSL_REDIRECT`는 환경변수. — **6-5d에서 HSTS·HTTPS 리다이렉트는 앞단 nginx로 옮겼다**(설계 §10 "배포 구성", prod는 `CSRF_TRUSTED_ORIGINS` 필수)
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
| `test_security_headers_present` | nosniff, 프레임 금지, Referrer-Policy, (prod) HSTS — 6-5d부터 HSTS는 nginx |
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
| | `test_format_decided_by_content_not_extension` | PNG 내용에 `.jpg` 이름 → PNG로 저장 (6-6에서 지움 — 검증은 이름을 받지 않으므로 `test_accepts_valid_png_and_jpeg`의 형식 단언과 같다) |
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
| | `test_no_set_cookie_header` | **[6-17c에서 합침]** 계약 시험 `test_no_cookie_is_set_and_no_auth_is_required`(익명·로그인, 200·304·404, `Vary` 포함 — §8.4.18) |
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
| `test_policy_cannot_be_overwritten_by_existing_pk` | 기존 PK의 새 인스턴스·upsert로 정책 행을 못 바꿈 (6-6에서 지움 — 추가 전용 모델 전부를 보는 `test_positional_and_keyword_upserts_and_new_instance_saves_cannot_overwrite`가 대신한다) |
| `test_slot_pricing_unit_immutable`(6-10d에서 `test_slot_audience_immutable` — 과금 단위가 없어져 슬롯 성격만) | 변경 시도 거부 |
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
  policies/{base,highest_bid}.py   # 6-14: highest_bid → weighted_by_bid
  registry.py            # 이름 → 구현 (정책, 필터)
tests/test_engine_pricing.py  tests/test_engine_filters.py  tests/test_engine_policies.py
```

**할 일**

1. **타입**(설계 §4.3 필드 표 그대로): `Candidate`, `Eligible`(= `Candidate` + `applied_amount`), `AdRequest`(`subject_id`, `slot_id`, `now`), `Selection`(`chosen: Eligible | None`, `trace: dict`). 모두 불변. 금액은 `int`(`bool`·`float` 거부), 시각은 UTC 지정(naive 거부), 생성 시 검증.
2. **`effect_of(bid, floor, cap) -> Effect(eligible, applied_amount, reason)`**: 설계 §4.2 표를 코드로. `reason`은 C6 `SlotEffect`와 같은 값(`within_range`·`capped_at_cap`·`below_floor`). 콘솔의 `effects`·`bid-preview`는 이 함수를 그대로 부른다(`no_policy`·`slot_inactive`는 `masters` 값으로 콘솔이 붙인다).
3. **`is_expired(ends_at, now)`**: `ends_at`이 `None`이면 거짓, `ends_at ≤ now`이면 참(**종료 시각 포함**, C6의 "끝나는 시각(미포함)"과 같은 뜻). 선택 필터·`campaigns`의 전환 작업·수정 가드가 모두 이 함수를 쓴다.
4. **필터 체인**: 순서 고정, 각 필터는 `(Eligible, request) -> 거절 사유 | None`. 순서: ① `status`(캠페인 `ACTIVE`, 광고그룹 `enabled`) ② `period`(`period_start ≤ now`, `not is_expired`) ③ `floor`(`below_floor`) ④ `budget`(`remaining_daily_budget ≥ applied_amount`) ⑤ `balance`(`wallet_balance ≥ applied_amount`). 적용 금액은 필터 앞에서 `effect_of`로 계산한다. 거절은 사유별 **개수만** `DecisionResult.rejected`에 담는다(후보가 많아도 커지지 않게, `records`가 `Decision.rejected_counts`로 저장). 후보는 **처음 걸린 필터**의 사유로 한 번만 센다. 사유 값: `campaign_not_active`·`ad_group_disabled`·`not_started`·`expired`·`below_floor`·`budget_exhausted`·`insufficient_balance`.
5. **`SelectionPolicy` 프로토콜과 `highest-bid/v1`**(**[6-14에서 바뀜 — 구현 6-14b `967b19c`]** `weighted-by-bid/v1`, §8.4.15): 적용 금액 최대, **동점이면 `rng`로 무작위**, `trace`에 동점 후보 ID 목록과 뽑힌 값. 후보가 없으면 `chosen=None`. `request`는 읽지 않는다.
6. **`decide(candidates, request, rng, policy="highest-bid/v1"(**[6-14에서 바뀜 — 구현 6-14b `967b19c`]** `"weighted-by-bid/v1"`), filters=DEFAULT) -> DecisionResult(selection, considered, rejected)`**: 가격 계산 → 필터 → 정책 선택. 알 수 없는 정책·필터 이름은 즉시 오류(`UnknownName`, 조용히 기본값으로 바꾸지 않는다). 요청 슬롯과 다른 슬롯의 후보가 섞이면 오류. `floor` 필터 없이 `budget`·`balance`만 쓰면(하한 미만 후보가 적용 금액 없이 남음) 오류. 같은 시드면 **입력 순서와 무관하게** 같은 결과가 나오도록 동점 후보를 광고그룹 ID로 정렬한 뒤 뽑는다.

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
| `test_highest_bid_picks_max_applied_amount` | 상한에 닿은 두 입찰은 동점 — **[6-14에서 바뀜 — 구현 6-14b `967b19c`]** 가중 추첨 시험으로(§8.4.15) |
| `test_tie_break_reproducible_with_seed` | 같은 시드 → 같은 선택 — **[6-14에서 바뀜 — 구현 6-14b `967b19c`]** 가중 추첨 시험으로(§8.4.15) |
| `test_tie_break_is_uniform` | 3자 동점 3,000회 → 각 후보 비율이 허용 범위 안 — **[6-14에서 바뀜 — 구현 6-14b `967b19c`]** 가중 추첨 시험으로(§8.4.15) |
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
| `Creative` | `creative_id`, `ad_group`, `title`, `redirect_url`(https), `image_name`(assets 이름), `image_bytes`, `enabled`, `created_at`, `updated_at` | `image_name` 인덱스. 광고그룹당 개수는 설정 `MAX_CREATIVES_PER_AD_GROUP`(V1 = 1)로 서비스가 제한. **[6-9에서 바뀜]** 소재는 광고주 소유 목록(`owner`·`archived_at`)이고 광고그룹과는 연결 표(`AdGroupCreative`)로 이어지며 선택은 광고그룹의 `creative`. `enabled`와 광고그룹당 개수 설정은 없다(§8.4.10) |
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
5. **광고그룹**: 슬롯 목록 변경 시 모두 같은 단위·활성 슬롯이어야 한다(`unit_mismatch`). `pricing_unit`을 보내면 항상 `unit_immutable`. **[6-10에서 바뀜]** 과금 단위가 없어져 두 오류도 없다 — 활성 슬롯이면 아무 슬롯이나 함께 고르고, `pricing_unit`은 모르는 필드로 400(§8.4.11).
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
| `test_campaigns_services` | `test_ad_group_unit_must_match_slots` / `test_pricing_unit_immutable`(6-10d에서 `test_an_ad_may_combine_any_slots` / `test_pricing_unit_is_no_longer_a_field`(6-12c에서 `test_update_ad_group_replaces_slots_atomically`로 합침) — 과금 단위 없음) | `unit_mismatch`·`unit_immutable`(6-10d에 없어짐) |
| | `test_bid_out_of_range_is_stored` | 하한 미만·상한 초과 입찰 저장 |
| | `test_bid_stale_version_conflict` | 동시 두 입찰 중 한쪽이 `StaleVersion` |
| | `test_bid_is_append_only` | |
| | `test_other_users_objects_are_404` (`@tag("security")`) | 모든 광고주용 함수가 남의 캠페인·광고그룹·소재를 404 |
| | `test_quota_limits` | 개수·총량 초과 `limit_exceeded` |
| | `test_creative_image_validated_and_https_only` | 위장·초과 이미지, `http://` 거부 |
| | `test_one_creative_per_ad_group_in_v1` | 설정을 올리면 늘어남 — **6-9c에서 바뀜**(광고그룹당 상한 없음): `test_an_ad_group_links_several_creatives_and_keeps_its_choice` |
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
  policies/{base,by_unit}.py          # ChargePolicy, by-unit/v1 (6-10c 에서 by_unit → share, share/v1)
  management/commands/recompute_spend.py  management/commands/check_ledger.py   # recompute_spend 는 6-16f 에서 없어짐
  migrations/0001_initial.py
tests/test_billing_ledger.py  tests/test_billing_budget.py  tests/test_billing_charge.py
console/views/auth.py (가입 흐름이 지급을 호출)
```

**모델**

| 모델 | 필드 | 제약 |
|---|---|---|
| `Wallet` | `owner`(FK `foundation.User`, 유일), `balance`, `created_at` | `balance ≥ 0`(DB `CHECK`) |
| `LedgerEntry`(추가 전용) | `entry_id`, `wallet`, `entry_type`(`SIGNUP_GRANT`·`CHARGE`·`ADMIN_ADJUST`·`TOPUP`), `amount`(부호 있는 정수), `balance_after`, `campaign_id`(UUID, FK 아님), `reaction_ref`(유일, 과금 멱등 키), `charge_policy`, `shortfall`, `note`, `created_at` | `(wallet) + SIGNUP_GRANT` 유일(부분 유니크), `reaction_ref` 유일(`NULL` 제외) |
| `CampaignSpend` | `campaign_id`, `budget_day`(날짜), `spent` | `(campaign_id, budget_day)` 유일. **원장에서 다시 계산할 수 있는 파생값** — **6-16f 에서 없어짐**(소진액은 원장에서 센다, §8.4.17) |

**`billing.api`**

| 함수 | 내용 |
|---|---|
| `grant_signup(user)` | 설정값 `SIGNUP_GRANT_POINTS`(기본 **50,000**)를 `SIGNUP_GRANT`로 지급, 지갑 생성. **한 사용자에 한 번만**(재호출은 변화 없음) |
| `adjust(actor, user_id, amount, note)` | 관리자 조정(부호 있는 정수, 사유 필수). 잔액을 0 밑으로 내리는 음수 조정은 거부. 감사 |
| `charge_for_reaction(owner_id, campaign_id, reaction_type, pricing_unit, applied_amount, reaction_ref, now)` | 설정된 `ChargePolicy`가 0이라고 하면 `None`(과금 없음). **멱등** 과금(Step 2-5에서 호출). 한 트랜잭션에서 ① `CHARGE` 항목 ② 잔액 ③ `CampaignSpend`(③ 은 6-16f 에서 없어짐). **남은 잔액만큼만 차감**하고 부족분은 `shortfall`에 기록. 같은 `reaction_ref`는 처음 결과 그대로 |
| `get_wallet(user, now)`, `list_ledger(user, before, limit)` | 잔액·`spent_today`(원장의 오늘 CHARGE 합)·`resets_at`, 원장 내역(최신순, `(항목, 다음 커서)` 반환) |
| `balances(owner_ids)`, `spend_today(campaign_ids, now)` | **한 번의 질의**로 여러 값(결정 조립용, N+1 방지) |
| `budget_day_of(instant)`, `next_reset(instant)` | **예산 일 경계 함수 한 곳.** `BUDGET_DAY_OFFSET_HOURS`(기본 0 = UTC 자정). 소진액 집계와 화면의 리셋 시각이 같은 함수를 쓴다 |
| `recompute_spend()` | 원장에서 `CampaignSpend`를 다시 만든다(경계 설정을 바꾼 뒤 실행) — **6-16f 에서 없어짐**(소진액은 원장에서 센다, §8.4.17) |
| `check_ledger()` | 모든 지갑에서 `balance == Σ amount`, `balance_after`의 연속성을 확인(어긋나면 목록 반환·명령은 비정상 종료) |
| `ChargePolicy` / `by-unit/v1` | 반응 유형이 광고그룹 과금 단위와 같을 때만 과금, 금액은 Decision의 적용 금액. 어떤 정책이었는지 `charge_policy`에 이름 기록(R8). 정책 이름은 설정으로 고른다. **[6-10에서 바뀜]** `share/v1`: 모든 유형을 결정에 남긴 그 유형의 비율로 내림(적용 금액 × % ÷ 100), `by-unit/v1`은 코드에서 지웠다(§8.4.11) |

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
| `test_budget_day_offset_and_recompute_matches_ledger` | 오프셋을 +9로 바꾸고 `recompute_spend` → 소진액이 원장 재집계와 일치 — 6-16f 에서 `test_changing_the_budget_day_offset_needs_no_recompute` |
| `test_spent_today_resets_at_boundary` | |
| `test_charge_policy_by_unit`(6-10c에서 `test_charge_policy_by_share` — 비율로 과금) | 단위가 같은 반응만 과금, 다른 유형은 0, 정책 이름 기록 |
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
| `test_unit_aware_candidates`(6-10d에서 지움 — 과금 단위 없음) | 슬롯 단위와 다른 광고그룹은 후보가 되지 않음 |
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
4. 슬롯 A에 결정 → 광고주 1 선택(적용 30), 슬롯 B → 적용 20, 슬롯 C → 광고주 1 제외. 같은 적용 금액 동점 상황에서 두 광고주가 고르게 뽑힘(시드 고정). **[6-14에서 바뀜 — 구현 6-14b `967b19c`]** 가중 추첨이라 슬롯 A 는 두 광고주 모두 나갈 수 있다 — 시험은 시드를 고정해 광고주 1 을 본다.
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
| 광고그룹 `GET·POST`, `GET·PATCH` | `list_ad_groups`·`create_ad_group`(`bid_amount` 선택)·`get_ad_group`·`update_ad_group` | `pricing_unit`을 보내면 항상 `unit_immutable`(**[6-10에서 바뀜]** 모르는 필드로 400). 응답의 `effects`는 **콘솔이 `masters`+`engine.effect_of`로 채운다**(Step 3) |
| 입찰 `GET`, `POST`(`expected_version`, 첫 입찰은 `null`) | `list_bids`·`add_bid` | `bid-preview`와 `effects`도 같은 방식으로 콘솔이 구성(적용 금액 계산은 `engine` 한 곳) |
| 소재 `GET·POST`(업로드), `GET·PATCH`, `PUT .../image` | `list_creatives`·`create_creative`·`get_creative`·`update_creative`·`replace_creative_image`(**[6-9에서 더해짐]** 연결 `link_creative`, 선택 `update_ad_group(creative_id)`(**[6-13e 에서 없어짐]** 선택은 `link_creative(…, select=True)` 하나), 보관 `archive_creative`, 광고주 목록 `list_owned_creatives`, 광고 만들기 `create_ad` — §8.4.10) | 업로드 검증 실패는 `assets.ImageRejected`(`reason`)로 전달, HTTP 변환(`invalid_image`)은 콘솔 몫 |
| 관리자 기능(중단·해제·반려·정책·조정) | `suspend_campaign`·`release_campaign`·`reject_review_request`, `masters.*`, `billing.adjust` | C6에는 없음(Django admin, 설계 §3) |
| `/reports/daily`, `/alerts` | **서비스 [구현 2-10 `records.api.daily_report`]**, 콘솔 JSON·`/alerts`는 Step 3 | 이벤트·반응 처리(Step 2) 이후. `alerts`는 현재 상태에서 계산하는 읽기 전용이라 Step 3 |
| 오류 코드 | `stale_version`·`unit_mismatch`·`unit_immutable`·`suspended`·`not_suspended`·`review_pending`·`ended`·`limit_exceeded` 모두 같은 `code` 값의 예외(**[6-10에서 바뀜]** `unit_mismatch`·`unit_immutable`은 없다) | `invalid_transition`은 계약에 없는 내부 방어용(409 `conflict` 계열)이라 계약에 추가할지 Step 3에서 정함 |

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
| **DB-2 MongoDB 연결 [로컬 완료 2026-10-10 `b01b425`, 인프라 서버 확인 남음]** | `pymongo`, 연결 설정(환경변수, 인증, 레플리카셋 이름), 관리 명령으로 `ad_events` 컬렉션·색인(`_id = event_id`) 생성, 상태 확인(연결·쓰기 권한·색인). **이벤트는 아직 쓰지 않는다**(Step 4) | 로컬 단일 노드 Replica Set과 인프라 서버 양쪽에서 연결·색인 확인, 연결 실패 시 앱이 영향을 받지 않음(아직 쓰지 않으므로). **결과(2026-10-10)**: 로컬 — 공유 컨테이너(Standalone·인증)와 임시 단일 노드 레플리카셋(인증 켜짐, `scripts/mongo_temp_rs.py`) 양쪽에서 시험 16개 통과(변형 검사로 확인). `ensure_event_store`는 컬렉션(공통 봉투 검증)과 색인 (`event_name`, `produced_at`)·(`payload.decision_id`, `produced_at`)을 만든다. 여러 번 불러도 같고, 같은 이름에 다른 키의 색인이 있으면 지우지 않고 멈춘다. `check_event_store`는 연결·8.x·레플리카셋 이름·쓰기 권한(별도 확인용 컬렉션, 계약 컬렉션은 건드리지 않음)·컬렉션·색인을 보고 하나라도 실패하면 비정상 종료한다. 쓰기는 과반 확인(`w=majority`), `_id = event_id`(UUID 표준 표현), 비밀번호는 URI 밖. 연결은 처음 쓸 때 만들고 앱 기동·요청 경로는 연결하지 않으며(`test_the_app_does_not_connect_at_all`), prod는 `MONGO_HOSTS`가 없어도 기동한다(Step 4에서 필수로 — **Step 6-3에서 바뀜**: 웹은 계속 선택이고, 중계는 설정이 없으면 바로 비정상 종료한다. 설계 §10 "이벤트 저장소 설정"). `check.sh`가 맨 앞에서 MongoDB 접속을 점검한다(없으면 멈춤). **남은 항목(인프라 서버)**: 3대 Replica Set(keyfile 인증)에서 연결·색인·쓰기 권한 확인 |

### 7.3.4 인프라 쪽에 요청·확인할 것 (사람의 일)

1. **Backend 서버에 `mysqlclient` 빌드 의존성**(`mysql-community-devel`, 컴파일러·`pkg-config`) 또는 미리 만든 wheel — `roles/backend`는 지금 `mysql-router-community`만 설치한다.
2. **MySQL Router 설정**: 누가 어떤 값으로 bootstrap하는가(포트 6446/6447, `router` 계정). ReplicaSet이면 앱은 읽기·쓰기 포트로 접속한다.
3. **앱 전용 데이터베이스 이름과 생성 방식**(`dev` 계정이 `CREATE DATABASE`를 할 수 있다). 개발·스테이징 서버가 따로 있는지.
4. **`max_connections`·`innodb_lock_wait_timeout` 기본값** 확인(Django 연결 수 = 워커 수 × 스레드 수). **[Step 6-3 O6, 2026-10-12]** 이 값들과 함께 배포 구성에서 다음도 정한다(설계 §10 "DB 읽기·쓰기 시간 제한"):
   - **DB 읽기·쓰기 시간 제한**(mysqlclient `read_timeout`·`write_timeout`). 지금은 없어서 DB가 응답 없이 멈추면 요청과 상시 처리가 오래 묶일 수 있다. 정하기 전까지 멈춤 감지는 반응 처리 상태 줄과 `process_reactions --status`(6-3c `90fce97`)가 맡는다.
   - **웹 워커 시간 제한**: 예를 들어 gunicorn 기본 30초가 잠금 대기(`innodb_lock_wait_timeout`, 기본 50초)보다 짧으면, 잠금 대기 초과의 503 대신 워커가 끊겨 프록시의 502가 나간다.
   - 주의: 읽기 시간 초과는 MySQL **2013**이다. 다시 하면 되는 오류(1205·1213)가 아니라서 C1에서는 503(성공 미확인)이 되고, 반응 처리에서는 실패 횟수가 올라 stuck으로 갈 수 있다. Step 5-5의 오류 분류(설계 §8 Step 5)와 함께 본다.
5. **MongoDB `ad_events`용 데이터베이스 이름**과 `dev` 계정의 쓰기 권한 범위 확인(`readWriteAnyDatabase`라 충분하지만 이름을 정한다).
6. **강제 failover의 허용 유실 범위 결정**: 비동기 ReplicaSet은 원본 노드 장애 뒤 강제 승격에서 복제 지연분(수신 확인한 반응·결정 포함)을 잃을 수 있다. 허용할지, 매체가 2xx 뒤에도 `GET`으로 생존을 확인하는 절차를 둘지, 무손실 복제 구조(반동기·그룹 복제 — 서버 3대 이상이라 인프라 구성 변경)를 요청할지 정한다. 정하기 전에는 "유실 0"을 단일 노드 기준으로만 쓴다. — **(2026-10-10)** 8번(InnoDB Cluster)으로 바꾸면 자동 failover와 그룹 과반 인증으로 이 문제를 줄인다. 로컬 클러스터 시험에서는 primary 강제 종료에도 확인한 쓰기 유실 0이었다(§7.3.4c). 허용 범위의 결정 자체는 여전히 사용자 몫이다.
7. 앱 배포 방식(프로세스 관리자·`process_reactions`·`relay_events` 상시 실행, `purge_sent_events`·`export_hop_manifests` 주기 실행, 로그 위치)은 인프라가 "서비스 영역"으로 남겨 둔 부분이라 별도로 정해야 한다.
8. **[요청 후보 2026-10-10] 운영 MySQL을 InnoDB ReplicaSet에서 InnoDB Cluster로**: 서버 3대(그룹 복제, 단일 primary, **자동 failover**) + MySQL Router. 6번의 강제 failover 유실 문제를 구조로 줄이는 안이고, 로컬 3노드 클러스터에서 앱 코드 변경 없이 점검·부하·장애 시험이 모두 통과했다(§7.3.4c). 요청에 담을 것:
   - 노드 3대(과반 유지를 위해 홀수), 같은 8.4 LTS(Server·Shell·Router). 설정: GTID·ROW 바이너리 로그·`binlog_checksum=NONE`, InnoDB 외 엔진 비활성, `innodb_flush_log_at_trx_commit=1`·`sync_binlog=1`
   - 클러스터 옵션: 일관성 `BEFORE_ON_PRIMARY_FAILOVER`(failover 직후에도 확인한 쓰기를 읽음), `expelTimeout`(로컬 5초 — failover 시간과 오탐의 균형), 자동 재합류
   - 계정 분리: 클러스터 관리(`failover`), Router 부트스트랩 계정, 앱 계정(`dev`, DML·DDL). 앱은 **Router 읽기·쓰기 포트로만** 접속
   - 운영 수치 확인: 실제 failover 시간(로컬 약 22~26초)과 계획된 전환 시간(로컬 부하 중 약 53초), 네트워크 분리 때의 동작, `max_connections`(4번)
   - 앱 쪽 전제: 모든 표에 기본 키(이미 충족), 일시 오류는 503 + 재시도(이미 충족). 설계 §10 "그룹 복제(InnoDB Cluster) 전제"
9. **[요청 2026-10-13, Step 6-5] 광고 서버 앞단 nginx**(설계 §10 "배포 구성", 사용자가 전달):
   - nginx와 certbot으로 TLS를 끝내고, 80 → 443 리다이렉트와 HSTS(처음에는 짧게)를 nginx가 붙인다. Django는 HTTP로 받고 이것들을 하지 않는다.
   - **접속 허용 목록**: 강의실 라우터 IP와 메타버스 서버 IP. 메타버스 서버를 빼면 매체 API(C1)가 막힌다. certbot이 HTTP-01 검증을 쓰면 `/.well-known/acme-challenge/`만 허용 목록에서 뺀다(또는 DNS-01).
   - Django로 넘길 때 `Host`는 그대로, `X-Forwarded-For`에 접속 IP를 붙인다(`$proxy_add_x_forwarded_for` 또는 `$remote_addr`). 앱은 오른쪽에서 1번째 값을 쓴다(`TRUSTED_PROXY_COUNT=1`, prod 필수).
   - `client_max_body_size`는 Django 상한(이미지 `ASSET_MAX_BYTES` 2MB + 64KB)보다 크게(예: `3m`) — 그래야 상한을 넘는 업로드도 Django가 413 화면으로 답한다(nginx 기본 1MB면 1MB 넘는 소재 업로드가 nginx의 HTML 413으로 막힌다).
   - 정적 파일·이미지를 nginx가 직접 서빙하지 않는다(모두 Django로 넘긴다, 설계 §10 "정적 파일 서빙"). 배포 때 `collectstatic` 뒤 Django를 재시작한다.
   - Django(WSGI 서버)는 127.0.0.1(또는 내부망)에만 바인딩한다. 열려 있으면 nginx(TLS·허용 목록)를 우회하고 `X-Forwarded-For`를 위조할 수 있다.
   - 정하지 않은 것: WSGI 서버 선택, 시간 제한 순서(nginx 응답 대기 ≥ 워커 ≥ 잠금 대기, 4번과 함께), nginx 502/504의 본문 형식, 요청 ID(`X-Request-ID`는 보내지 않거나 UUID 형식으로).

### 7.3.4a DB-1a 결과: MySQL 8.4에서의 시험 실패 목록 (2026-10-08) — 아래 표의 7개는 DB-1b(2026-10-09)에서 모두 해결, 전체 692개 통과

시험 환경: 인프라가 준 `intake/db-standalone/`(MySQL **8.4.11** 컨테이너, `root`), 설정은 `DB_*` 환경변수·`mysql_config`(`STRICT_ALL_TABLES`, `READ COMMITTED`, `utf8mb4`·`utf8mb4_0900_as_cs`). 전체 시험 688개 중 **통과 681, 실패 7개**(보고는 8건: 한 시험이 실행·정리에서 두 번 오류). 처음에는 686개 중 17건 보고였고, 그 가운데 9건은 시험 도구가 `DATABASE_PATH`·SQLite를 전제한 것이라 DB-1a에서 고쳤다(시험 2개 추가). 소규모 부하 시험(20 동시)은 **불변식 전부 통과**(조건부 유일 제약 없이도 — 코드 쪽 점검만으로). 전체 시험 약 27초, 부하 시험 약 28초.

DB-1a에서 이미 고친 것(T25가 인용하던 `test_sqlite_pragmas`는 `test_commit_is_durable_on_this_server`로 교체, 위협 모델 갱신): 설정 시험이 환경을 다시 만드는 곳(`tests/helpers.py`의 `DB_ENV`·`PROD_ENV`), SQLite PRAGMA 시험을 MySQL 세션 시험으로 교체(`MysqlSessionTests`: strict·격리 수준·문자셋·정렬·UTC·**커밋 내구성(T25)**), `check.sh`·`load_test.py`의 DB 준비(`scripts/mysql_admin.py`: 접속 점검, 실행마다 새 `ads_load_*` DB).

**남은 실패 7개 — DB-1b에서 고친다(원인별)**

| 원인 | 시험 | DB-1b 처리 |
|---|---|---|
| ① **조건부 유일 제약 3곳이 만들어지지 않음**(`W036` 경고 3개 — `billing_charge_once_per_reaction`, `billing_one_signup_grant_per_wallet`, `campaigns_one_open_review_per_campaign`) | `test_ledger_db_constraints`, `test_only_one_open_review_request_per_campaign`, `test_charge_concurrent_same_ref_once`(**같은 반응 키로 과금 2건**), `test_check_deploy_has_no_warnings`(경고) | S8: 조건 없는 유일 제약 + NULL 키로 교체(데이터 이전 포함). **이 세 시험이 실제로 실패했다는 것은 이 제약이 없으면 DB가 이중 과금을 막지 못한다는 증거** |
| ② **원시 SQL이 SQLite 문법** (`?` 자리표시자, `DROP INDEX name`은 MySQL에서 `ON 테이블` 필요) | `test_a_double_charge_is_found`(부하 검사기 시험) | 제약을 빼는 시험을 `ALTER TABLE … DROP INDEX/CONSTRAINT`로, 자리표시자는 `%s`로 |
| ③ **범위를 벗어난 값의 오류 종류**: `PositiveBigIntegerField`가 MySQL에서 `UNSIGNED`라 음수 잔액이 CHECK(`IntegrityError`) 전에 `DataError`(1264)로 거부된다 | `test_balance_never_below_zero` | 거부 자체는 같다. 시험이 두 오류를 모두 받아들이게 하되 **어느 쪽이든 행이 바뀌지 않음**을 확인 |
| ④ **MySQL DDL은 트랜잭션이 아니다** — 마이그레이션이 중간에 멈추면 이미 적용된 열(`accepted_key`)이 남아 다음 실행이 `Duplicate column`으로 깨진다. `records 0007`은 `AddField` 뒤에 사람을 알 수 없는 인정 행을 검사해 멈추므로 **운영에서도 같은 상태가 된다** | `test_an_accepted_reaction_whose_person_cannot_be_known_stops_the_migration_with_a_clear_message`(보고 2건: 실행·정리. 6-6에서 마이그레이션 이행 시험과 함께 지움 — 이 마이그레이션 이전 상태의 DB가 없다, §8.4.7 D-2) | **검사(`RunPython`)를 스키마 변경보다 앞에 둔다**(멈춰도 DB가 그대로). 이 순서를 지키는 시험 추가. 다른 마이그레이션도 데이터 검사가 스키마 변경 뒤에 있는지 점검 |

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
| Step 5(확장) | 조건부·기록만: Debezium outbox 라우터 → Kafka(중계 대체 — **전환 게이트**: 전송 확인·보존 기준, 라우터의 UPDATE·DELETE 처리, 봉투 매핑, 설계 §6.3), Spark → Delta 메달리온(설계 §10 "분석 계층 대응"), 스키마 저장소, C4 수신(`records.api` 집계 안쪽 교체). **5-5 결정 요청 멱등**(Step 6-2에서 기록, 착수 조건은 따로 — 결정 수가 정산·빈도 제한·보고 정확도의 기준이 될 때 또는 매체가 요청할 때, 설계 §8 Step 5) |
| Step 6 **[진행 중, 2026-10-12~]** | **Step 3 이후 수정** — 연동 검토·운영·외부 검토에서 나오는 수정을 하나씩 쌓는다(6-1, 6-2 …, 수정마다 계기·결정·계획·완료 증거). 상세는 §8.4. 6-1 매체 연동 검토(게임 ad-bridge) 후속 **완료(2026-10-12)**: 결정 반영(C1 1.2.0), 서버 규칙 `media_deactivated` 6-1a `fcee77b`·6-1b `7c4714b`(기록 표 방식), 질의 수 기준선 10 · 39 · 27, 계약 반영 6-1d. 6-2 외부 검토(코드 `7c4714b`·문서 `30b0195`) 후속 **완료(2026-10-12)**: 결정 반영과 문구 정정(계약 1.2.0 안), 매체 생명주기 잠금 6-2a `3827185`·6-2b `e872006`, 숫자 범위 6-2c `9189af8`, 응답 검사 6-2d `253334b`, 질의 수 기준선 11 · 40 · 28, 계약 1.3.0(6-2f, §8.4.3). 6-3 초기 운영 보완(리팩터링 세션 검토 O1~O8) **6-3a~6-3i 완료(2026-10-13)**: 결정 반영(설계 §10)·README 운영 보완·§7.3.4 #4(DB 시간 제한), 서버 작업 6-3a `9e6e374`·6-3b `ea23a81`·6-3c `90fce97`·6-3d `a733e95`·6-3e `5d2d517`, 질의 수 기준선 그대로(11 · 40 · 28), 구현 뒤 문서 반영(6-3g), 리팩터링 4차 뒤 6-3h `1509c10`(프록시 설정 누락 경고)·6-3i `6d80ecb`(관리자 첫 화면 처리 현황 카드). 6-4 코드 정리(리팩터링 4차) **완료(2026-10-13)**: `dd21833`~`39bb3da`, 6-4f로 서빙 경로 밖 질의 수만 줄고(해제 7 → 6, 기간 종료 5 → 4, 광고그룹 만들기 11 → 10) 서빙 질의 수는 그대로(§8.4.5). 6-5 배포 구성 전환(nginx 앞단·Django는 HTTP 전제, 가입 시도 제한 제거, 신뢰할 프록시 수 prod 필수, 정적 파일은 Django) **완료(2026-10-13)**: 6-5a `b9edb2b`(결정·계획) · 6-5b `5e69276` · 6-5c `6c5aa6d` · 6-5d `f744769` · 6-5e `dd53bda`, 질의 수 그대로(§8.4.6). 6-6 코드 정리(리팩터링 5차, 시험 코드 포함) **완료(2026-10-13)**: `3d48354`~`0db492e`(7커밋 + 완료 기록), 시험 1,355 → 1,305(폐기 39·합치기 11, 위협 모델 인용은 먼저 대체 시험으로), 전체 시험 156초 → 120초, 서빙 질의 수 그대로, 콘솔 광고그룹 상세 13 → 12(§8.4.7). 6-7 리팩터링 5차 보고 후속(장애 시험의 임시 폴더·outbox PK 기본값·운영 화면의 409) **완료(2026-10-13)**: 6-7a `e9096a7` · 6-7b `113abe3` · 6-7c `068c98f` · 6-7d `a23873c`, 시험 1,305 → 1,306, 서빙 질의 수 그대로, 질의 줄이기는 보류 그대로(§8.4.8). 6-8 브라우저 검토 후속(모니터링 링크·게재 위치를 만들 때의 빈 사유) **완료(2026-10-13)**: 6-8a `61880b8` · 6-8b `25c52d9` · 6-8c `0eb674b`, 시험 1,306 → 1,308, 서빙 질의 수 그대로(§8.4.9). 6-9 구조 재편(캠페인·광고·소재 — 캠페인 따로 만들기, 광고 + 소재 만들기, 소재 목록·재사용·선택·보관, 소재 끄기 제거, 용어 "광고") **완료(2026-10-13)**: 6-9a `4669baf` · 6-9b `576f3cd` · 6-9c `724a276` · 6-9d `4503452` · 6-9e `35767b7` · 6-9f 측정·완료 기록, 시험 1,308 → 1,337, 서빙 질의 수 그대로(§8.4.10). 6-10 과금 재설계(구성별 반응 비율, 과금 단위 제거, 화면 용어 "구성") **완료(2026-10-13)**: 6-10a `3d6e017`·`ccb65d6` · 6-10b `1be3658` · 6-10c `335e81b` · 6-10d `d557905` · 6-10e `d5a4b46` · 6-10f 측정·완료 기록, 시험 1,337 → 1,341, 서빙 질의 수 11 · 40 · 37(클릭도 과금, §8.4.11). 6-11 광고 상세의 이미지 칸(고르기만·올리기만, 사용자 요청) **완료(2026-10-13)**: `5fe343c`(+ 시험 보완 `e621248`, §8.4.12). 6-12 코드 정리(리팩터링 6차, 시험 코드 포함) **완료(2026-10-13)**: `78effec`~`800797b`(+ 시험 먼저 `e621248`), 시험 1,343 → 1,335, 동작 불변(화면 84개의 상태·이동·질의 수·HTML 비교), 서빙 질의 수 그대로(11 · 40 · 37), 동작 변화가 필요한 발견은 "보고만" R1~R19(§8.4.13). 6-13 검토 지점 보완(R1~R19의 동작 변화) **완료(2026-10-14)**: `efe83c4`~`77db030` + 마무리 6-13g, 시험 1,335 → 1,342, 서빙 질의 수 그대로(11 · 40 · 37) — 6-13a 화면 오류 표시·응답 코드(R1·R2·R6) · 6-13b 서비스 동작(R3·R4·R5·R9) · 6-13c 접근성(R8) · 6-13d 시험 보강(R11·R12·R13, R7은 그대로) · 6-13e 소재 선택 경로 하나(R17) · 6-13f 엔진 후보·정책 제약·구성 성격(R18) · 6-13g 스크립트(R19)·측정 (§8.4.14). 6-14 선출 정책 교체(최고가 → 상한 근접 가중 추첨 `weighted-by-bid/v1`, k = 2) **완료(2026-10-14)**: `d254675`·`967b19c` + 6-14c 측정, 시험 1,342 → 1,343, 서빙 질의 수 그대로(11 · 40 · 37)(§8.4.15). 6-15 프론트·백 서버 분리(팀 메타버스와 같은 구조, 운영 화면도 프론트) **완료(2026-10-14)**: `22b2d8c`~`1a9a891` + 6-15f, 화면 41개 전후 같음, 시험 1,343 → 1,351 + 프론트 13, 서빙 질의 수 그대로(§8.4.16). 6-16 결함·DRD 축소·검토 지점(리팩터링 7차 점검 후속 — 시계 의존 시험·미리보기 500·결정의 `bid_id`·오류 화면의 세션, 표 −4, DRD 현재형 정리, R20~R27) **완료(2026-10-14)**: `ce3be44`~`f63ecff`(6-16l 실제 검토 후속 포함), 표 24 → 20, 시험 1,351 → 1,349, 서빙 질의 수 11 · 36 · 36(§8.4.17). 6-17 코드 정리(리팩터링 7차, 시험 코드 포함) **완료(2026-10-14)**: `3d807a2`~`e28743f` + 6-17f, 시험 1,349 → 1,345 · 프론트 13 → 12, 동작 불변(화면 70개 비교), 서빙 질의 수 그대로(11 · 36 · 36), 동작 변화가 필요한 발견은 "보고만"(R28)(§8.4.18). 6-18 시험 축소와 운영·개발 분리(운영용 ≤ 300·합계 ≤ 500, 개발 도구·시험은 `tests/` 아래, 배포 후 점검 명령) **진행 중(2026-10-14~)**(§8.4.19). 남은 것은 운영하면서 할 것(§8.4.4)과 6-5의 정하지 않은 것(WSGI 서버·시간 제한·nginx 오류 형식·요청 ID, §8.4.6) |

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
- 광고주가 입력한 문자열(제목·이름·이동 주소)은 **항상 이스케이프**하고, 이동 주소는 `https`만 링크로 만들며 `rel="noopener noreferrer nofollow"`, 관리자 화면에는 **도메인을 눈에 띄게** 표시한다(6-8b부터 관리자 화면의 이동 주소와 썸네일은 새 탭으로 연다).

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
| **3-3 마무리** | 접근 제어 전수(관리자↔광고주 상호 차단, 익명 리다이렉트), 보안 헤더·CSP 위반 없음, 접근성 기본(레이블·키보드·대비), 모바일 폭, 브라우저 확인(캡처, **JS를 끈 상태로도 주요 흐름**), 위협 모델 **T43(콘솔 뷰)·T44(관리자 동작)** 연결(T38~T40은 2-8·2-9·2-10, T41·T42는 Step 4가 사용), **외부 검토(`00d3067`) 남은 P3 두 건**(구간 정합 manifest 내보내기의 메모리, 모니터링 DB 정렬·쪽 나누기 — §10, 결정 2026-10-11 사용자), 종료 점검표. [3-3a·3-3b `38647b9`] 접근 제어 전수 시험(`tests/test_access_sweep.py`): 모든 화면 경로를 실제 값으로 채워 역할마다 GET·POST — 광고주 화면은 익명이면 로그인으로·관리자는 403, 관리자 화면은 익명·광고주 모두 404. 화면 전수 점검 시험(`tests/test_screens_quality.py`): 모든 화면의 보안 헤더, CSP 위반 마크업(인라인 스크립트·`style`·`on` 속성), 접근성 기본(`lang`·대체 글·입력 이름표·버튼 이름·`main`), 디자인 토큰 대비(WCAG AA, 두 테마). [외부 검토 `e781f20` P3 `de77684`] 점검할 화면 목록은 광고주·운영 경로를 모두 실제 값으로 GET 해 HTML 화면이 목록에 없으면 실패하고(`test_no_console_or_operator_screen_is_left_out`), 관리자 사이트는 등록된 모든 모델의 목록·상세와 본인 비밀번호 변경·대상 비밀번호 초기화를 등록에서 만든다(전에는 손으로 적은 일부 화면). 정상 GET으로는 나오지 않는 화면(키 발급·로그인 잠금·가입 제한·오류)은 `e781f20`. 라이트 테마 `--muted`를 `#5f6673`으로(오류 배경 위 대비가 4.23으로 부족했다). [3-3c `526046d`] Chrome으로 화면을 점검해 찾은 것: ① 광고 만들기의 칸에서 Enter가 숨긴 "단위 보기"를 눌러 고른 이미지를 말없이 잃었다 → 첫 제출 버튼을 숨긴 "집행"으로(설계 §10 D3-1 보충) ② 이미지 미리보기의 `hidden`이 `display:block`에 져 깨진 그림이 보였다(`[hidden]` 규칙) ③ 고를 수 없는 게재 위치는 흐리게, 단위를 고르면 안내를 숨김, 그림이 아닌 파일은 미리보기를 숨김 ④ 운영 화면의 넓은 표가 페이지를 넘겼다(가로 스크롤) ⑤ 광고그룹의 이미지 교체 폼을 소재마다 따로(한 소재의 거절 사유가 모든 소재 아래에 붙고 이름표 `id`가 겹쳤다) ⑥ 매체 키 교체에 확인 창(즉시 만료면 그 키를 쓰는 매체 서버가 바로 인증 실패) ⑦ 같은 화면에 있는 폼끼리 `id`가 겹침(키 발급·교체, 광고그룹 이름·위치) ⑧ 비밀번호 칸 `autocomplete`, 입찰 충돌 문구를 다른 충돌과 같게. 화면 점검 시험에 비밀번호 `autocomplete`·겹친 `id` 검사를 더함. [3-3d `ca2572c`] 모니터링의 DB 정렬·쪽 나누기(P3-4 2단계, §8.1.2 S5) — 시험 `test_the_latest_of_several_creatives_counts`·`test_a_page_reads_only_its_own_campaigns`·`test_pages_split_one_order_without_overlap`. [3-3e `6654077`] 구간 manifest 내보내기를 창 단위로(P3-3 — 계획과 다른 점은 §10 "외부 검토(`00d3067`) 남은 P3" ①) — 시험 `WindowedSummaryTests` 4개(`test_the_source_hop_matches_summarizing_everything_at_once`·`test_the_outbox_hop_matches_summarizing_everything_at_once`·`test_it_reads_only_closed_windows_after_since_one_window_and_kind_at_a_time`·`test_unsent_counts_read_only_the_unsent_rows`)와 `test_several_windows_agree_and_only_the_range_is_read`. 공개 API: `events.api`에서 `outbox_documents`·`mongo_documents`를 없애고 `summarize_windows`·`table_stream`·`outbox_streams`·`mongo_streams`를 더함, `unsent_counts(size)`는 DB를 직접 읽음. `records.api`는 `source_documents` → `source_streams`(`expected_events`는 부하 검사기의 전수 대조용으로 남음). `billing.api`에 `charge_entries_for`(반응 멱등 키로 원장 과금 줄). 외부 검토(`e781f20`) P2 `5e8fa8c`에서 `records.api.unresolved_charges`·`billing.api.charge_refs_after`(원장 과금 줄을 ID 순으로 한 묶음씩)를 더함 — 창에 놓을 수 없는 과금 원장 줄을 세어 `checkpoint.unresolved_charges`에 적고 0보다 크면 내보내기·`verify_hops`가 실패(설계 §6.3a). [종료 점검 `89c8a38`] **JS 없는 주요 흐름 — HTML 폼 기반 서버 통합 시험**(브라우저가 아니다: 서버가 그린 HTML의 폼을 HTMLParser로 읽어 JS 없는 브라우저가 보낼 것만 시험 클라이언트로 냄 — 가입·로그인·광고 만들기의 단위 고르기·미리보기·집행·캠페인 수정·새 입찰·관리자 중단·재검토 요청·해제·포인트, 꺼진 칸·없는 칸·파일을 못 보내는 폼은 보낼 수 없음, CSRF 검사 — `tests/test_no_js_journey.py`, 문구 `de77684`). **실제 브라우저로 본 범위**: 3-3c Chrome 점검(`526046d`), 외부 검토가 Chrome에서 앱 스크립트를 막은 상태로 단위 보기 → 미리보기 → 집행 → 캠페인 수정 → 새 입찰까지 확인, **C6 규칙 ↔ 서비스 대조**(값 목록·금액 상한·칸 길이를 계약 파일에서 읽어 서비스에 직접 — `tests/test_console_contract_rules.py`). 대조에서 찾은 것: 비밀번호 최대 128자가 화면 폼에만 있어 서비스·서버 명령은 더 긴 비밀번호를 받았다 → 비밀번호 검증기 `MaximumLengthValidator`(`PASSWORD_MAX_LENGTH`, 설계 §10 "비밀번호") | 브라우저로 주요 흐름 확인, `scripts/check.sh` 통과, 종료 점검표 — 접근 제어·화면 전수 시험(`38647b9`, `e781f20`, `de77684`), Chrome 점검과 회귀 시험 `test_enter_in_a_field_creates_instead_of_redrawing`·`test_each_creative_has_its_own_image_form`(6-11에서 지움 — 광고 상세에 이미지 교체 폼이 없어졌다)(`526046d`), JS 없는 흐름·C6 대조(`89c8a38`), 외부 검토(`e781f20`) 보완 `5e8fa8c`(창에 놓을 수 없는 과금 원장 줄은 내보내기·대조 실패)·`de77684`(화면 점검 빠뜨림 방지), 재검토(`5e8fa8c`) 보완 `13f3bc2`(과금 키는 표준 표기일 때만 그 반응의 키, 반응 조회는 정확한 쌍만) |

각 단계의 공통 완료 조건: ① 서비스 `api`만 호출(경계 테스트) ② 다른 광고주/권한 없는 역할 접근 테스트 ③ XSS·CSRF 회귀 테스트 ④ 감사 로그가 필요한 동작은 감사 확인 ⑤ 변형 검사 ⑥ 위협 모델 행 ⑦ `scripts/check.sh` 통과 후 커밋.

### 8.1.4 착수 전에 정한 것 [확정 2026-10-11, 사용자 — 기록은 설계 §10 "Step 3 화면 결정"]

| # | 질문 | 정한 값 | 이유 |
|---|---|---|---|
| D3-1 | 화면에 JS를 쓰나 | **조정**: JS 없이 동작하는 것이 기본(폼 제출·링크), 필요한 곳에만 **작은 JS를 덧붙인다** — 규칙 셋(§8.1.1). MVP에서 붙이는 곳: 광고 만들기의 과금 단위별 위치 거르기, 소재 이미지 미리보기, 제목·이름 글자 수, 되돌릴 수 없는 동작(캠페인 종료·광고 중단 등)의 확인 창. 모두 규칙이 없고 서버가 다시 검증한다 | CSP를 바꾸지 않고 편의만 더한다. 규칙 셋으로 나중의 화면 교체 비용을 키우지 않는다 |
| D3-2 | 차트 | **서버가 만든 인라인 SVG**(라이브러리 없음), 옆에 같은 값의 표(접근성) | CDN·인라인 스크립트 금지, 의존성 0 |
| D3-3 | 광고 만들기 형태 | **단계 제목이 있는 한 페이지 폼 + 원자적 `create_ad`**. 위저드(다중 페이지·초안 저장)는 하지 않는다. **[6-9에서 바뀜]** 캠페인은 따로 만들고, 광고 만들기는 광고 + 소재(새로 올리기·재사용)를 한 트랜잭션으로(§8.4.10 S1·S2) | 초안 저장 상태·고아 객체·중복 제출 위험이 없다 |
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

- ~~**HTTP/HTTPS 배포**~~ **[확정 2026-10-13 — 설계 §10 "배포 구성", 구현은 §8.4.6 6-5]**: 광고 서버 앞 nginx가 TLS를 끝내고 Django는 HTTP 전제로 동작한다. 아래는 결정 전의 기록이다. [사용자 결정 대기, 설계 §7-14]: 운영 설정은 HTTPS 전용(Secure 쿠키·HTTPS 리다이렉트·HSTS)이라 HTTP로 배포하면 콘솔 로그인이 되지 않는다. 대안 A(콘솔은 HTTPS, 매체 API만 내부망 HTTP)·B(시연용 HTTP, 접속 제한)·C(Frontend에 TLS 종단, 앱 코드 변경 없음 — 환경값 `BEHIND_TLS_PROXY`). 개발·시험(dev 설정)은 영향이 없다.

### 8.1.7 Step 3 종료 점검표

- [x] 3-0~3-3 구현, 커밋마다 `scripts/check.sh` 통과(구현 세션 보고 — 마지막 수치 `e781f20` 시점 시험 1277개)
- [x] **콘솔 뷰에 규칙 없음**(설계 §6.6): 콘솔은 서비스 `api`만 부르고 `django.db`·`engine`·모델 매니저를 쓰지 않는다(경계 시험 `tests/boundaries/test_console_rules.py`, 3-0c). 화면에 필요한 서비스는 §8.1.2 S1~S9로 보강했다
- [x] **관리자 화면(3-1a~3-1d)**: 매체·위치·키, 입찰 정책(일괄 포함), 모니터링·중단·재검토, 광고주·포인트. 모델 직접 편집은 읽기 전용, 쓰기는 서비스를 부르는 운영 화면으로만(`<ADMIN_URL_PATH>operator/`, 관리자가 아니면 404). 사용자 관리는 프로필·비밀번호 초기화만(설계 §10 "광고주 비활성화는 송출도 멈춘다")
- [x] **광고주 화면(3-2a~3-2f)**: 대시보드·알림, 캠페인, 광고 만들기(한 페이지 폼 + 원자적 `create_ad`), 광고그룹 상세, 포인트, 내 정보·비밀번호 변경(로그인과 같은 시도 제한)
- [x] **두 번·겹쳐 내도 한 번만, 옛 폼은 덮지 않음**: 두 번 하면 안 되는 동작은 결과 행에 같은 트랜잭션으로 저장하는 요청 키(매체 키 발급·교체, 포인트 조정, 광고 만들기 — §8.1.1), 수정 폼은 화면이 본 값과 대조(`expected_updated_at`·`expected_version`), 쓰기는 광고주 → 캠페인 → 광고그룹·소재 순서로 잠근다(설계 §10 "캠페인 행 잠금 규약")
- [x] **접근 제어 전수**(3-3a `38647b9`): URL 설정 전체(정규식 경로 제외)를 실제 값으로 채워 역할마다 GET·POST — 광고주 화면은 익명이면 로그인으로·관리자는 403, 관리자 화면은 익명·광고주 모두 404
- [x] **화면 전수 점검**(3-3b `38647b9`, `e781f20`, `de77684`): 모든 화면(정상 GET 화면과 키 발급·로그인 잠금·가입 제한·오류 화면 — 가입 제한 화면은 6-5b에서 없앰)의 보안 헤더, CSP 위반 마크업 없음, 접근성 기본, 디자인 토큰 대비(WCAG AA). 광고주·운영 경로를 모두 GET 해 빠뜨리면 실패, 관리자 사이트는 등록된 모든 모델
- [x] **JS 없이 주요 흐름**(D3-1): HTML 폼 기반 서버 통합 시험(`89c8a38`, 브라우저가 아니다). **실제 브라우저**: 3-3c Chrome 점검(`526046d`, 8건 수정), 외부 검토가 Chrome에서 앱 스크립트를 막고 단위 보기 → 미리보기 → 집행 → 캠페인 수정 → 새 입찰 확인
- [x] **C6 규칙 ↔ 서비스 대조**(`89c8a38`): 값 목록·금액 상한·칸 길이. 찾은 것: 비밀번호 최대 128자 → 비밀번호 검증기(비대화형 `createsuperuser`는 Django가 검증기를 돌리지 않음 — 코드로 막지 않고 문서에 남김, 사용자 결정 2026-10-12)
- [x] **미뤄 둔 P3 두 건**(외부 검토 `00d3067`, 사용자 결정 2026-10-11): 모니터링 DB 정렬·쪽 나누기(3-3d `ca2572c`), 구간 manifest 창 단위 읽기(3-3e `6654077`, 보완 `5e8fa8c`·`13f3bc2` — 창에 놓을 수 없는 과금 원장 줄은 세어 내보내기·대조를 실패로)
- [x] `threat-model.md` 갱신: T43(콘솔 뷰, ⑩~⑭까지), T44(관리자 동작, ⑥까지), T42 ⑧(3-3e), T2·T40 인용 보강
- [x] 설계 §10에 Step 3 결정 반영("Step 3 화면 결정", "비밀번호 변경의 시도 제한", "로그인 잠금 기록 관리", "광고주 비활성화는 송출도 멈춘다", "캠페인 행 잠금 규약", "비밀번호"), DRD 갱신(0.25~0.31), C6 갱신(`expected_updated_at`, 광고그룹·소재 응답 `updated_at`), 진행 상태 표(§10) 갱신
- [x] **외부 검토 완료**(`38647b9..13f3bc2`, 3-1~3-2의 단계별 외부 검토는 §10 진행 기록)
- [x] **사람의 일 — HTTP/HTTPS 배포**(설계 §7-14, §8.1.6): 운영 설정은 HTTPS 전용이라 HTTP로 배포하면 콘솔 로그인이 되지 않는다. 대안 A·B·C 중 결정 — **결정 2026-10-13**(설계 §10 "배포 구성": nginx가 TLS를 끝내고 Django는 HTTP 전제, 구현은 §8.4.6 6-5)

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
| 클릭의 결정 소유 매체 재조회 (리팩터링 4차 D-R1, 2026-10-13) | `records/services.py` `_record_click` → `records/ordering.py` `lock_for_receipt`의 `_owner` | 클릭은 결정을 이미 읽었는데 접수 잠금 전 소유 확인이 결정의 매체를 다시 읽는다. 줄이면 클릭 28 → 27. 동시성 핵심 경로라 보류 | 반응 처리량·클릭 지연이 측정상 병목일 때 |
| 판정의 결정 두 번 읽기 (리팩터링 4차 D-R1, 2026-10-13) | `records/ordering.py` `wait_for_inflight_receipts` → `records/processing.py` `_process` | 판정 전 대기와 판정이 같은 결정을 따로 읽는다. 줄이면 반응 40 → 39, 클릭 −1. 동시성 핵심 경로라 보류 | 반응 처리량·클릭 지연이 측정상 병목일 때 |
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

**무엇을 담나**: Step 3 승인(2026-10-12) 뒤 연동 검토·운영·외부 검토에서 나오는 수정이다. 기능 단계(Step 3·4)를 다시 열지 않고 여기에 수정 단위로 쌓는다. 수정 하나가 **`6-N`**(생긴 순서)이고, 그 안의 단계는 `6-Na`·`6-Nb` …다. 새 수정이 생기면 마지막 절 다음에 절을 하나 더한다.

### 8.4.1 진행 기준 (모든 수정 공통)

1. 수정마다 **계기 · 결정 · 단계 · 완료 증거 · 매체 쪽 요청(있으면)**을 적는다. 결정은 설계 §10, 진행은 §10 표에 행 하나.
2. **결정은 바로, 계약은 구현 뒤에**: 사용자가 정한 것은 바로 설계 §10에 남긴다. 아직 구현되지 않은 서버 동작(새 사유 코드·판정 규칙)은 **구현이 끝난 뒤** 계약·DRD·위협 모델에 넣는다 — 계약이 없는 동작을 약속하지 않게. 그때까지 설계 §10에 "[구현 예정]"으로 표시한다.
3. **계약 버전**: 전송 형식이 그대로이고 매체에 새 요구가 생기면 부 버전(1.x, 호환)을 올리고 "변경" 절을 둔다. 호환되지 않으면 `/v2`다(설계 §10 "계약 v1.1"·"계약 v1.2").
4. 코드 단계는 Step 3-4와 같다: **한 단계 = 한 커밋**, 단계마다 `scripts/check.sh` 통과, 동작이 바뀌는 곳은 시험으로 고정, 질의 수 기준선이 바뀌면 기록한다 — **지금 기준선은 결정 11 · 반응 40 · 클릭 28**(6-2e, 2026-10-12. 그 전은 10 · 39 · 27(6-1c), 10 · 38 · 26).
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
| **6-1a `masters`** | 매체 비활성화 기록 표(매체, 비활성화 시각). `set_media_active(False)`가 **실제로 활성 → 비활성으로 바꿀 때만** 같은 트랜잭션에서 한 줄 추가. 관리자 화면은 읽기 전용. `api`에 "이 구간에 비활성화가 있었나" 조회 하나 | 마이그레이션, 감사·읽기 전용 화면 시험 갱신 | **완료 `fcee77b`** — `masters.MediaDeactivation`(마이그레이션 `masters/0004`, 색인 `(media, deactivated_at)`), 조건부 UPDATE라 동시에 꺼도 한 줄·이미 꺼진 매체를 다시 끄거나 켜면 기록 없음, `masters.api.first_deactivation(매체, after, until)` = (after, until] 안의 가장 이른 시각, 읽기 전용 모델 17 → 18. 시험 1,304개 |
| **6-1b `records`** | 판정 사실에 "결정 뒤, 접수 전 비활성화"를 더한다. 새 규칙 `media-period`(사유 `media_deactivated`)를 `REACTION_RULES`의 `same-media` 바로 뒤에 둔다. 판정 근거에 사용한 비활성화 시각을 기록한다 | 규칙 단위 시험. 처리 시험: 결정 → 비활성화 → 재활성화 → 노출이면 거부, 비활성화 전 접수·늦은 판정이면 인정, 재활성화 뒤 새 결정이면 인정, 서버 클릭도 같음 | **완료 `7c4714b`** — 구간 (결정 시각, 접수 시각](결정과 같은 순간에 끈 것은 결정 전, 접수와 같은 순간에 끈 것은 접수 전), 기준 매체는 결정을 만든 매체(다른 매체의 보고는 `media_mismatch`가 먼저), 필수 조건(`MANDATORY_RULES`)에도 넣음, `basis` v2 → v3(`media_deactivated_at`), `set_media_active(now=)` 시각 주입. 시험 1,310개 |
| **6-1c 측정** | 질의 수 재측정(반응 경로 +1 예상), `check.sh` | 기준선 변화 기록 | **완료(커밋 없음)** — 결정 10 · 반응 39 · 클릭 27(전 10 · 38 · 26, 6-1a `fcee77b` 시점과 같은 측정 도구로 비교). 판정할 때 비활성화 조회 1번(반응 처리, 접수 때 바로 처리되는 클릭) |
| **6-1d 문서** | 구현 세션이 커밋 해시와 함께 따로 요청: 계약 `ReactionReasonCode`에 `media_deactivated`와 반응 판정 규칙 표, DRD 반응·매체 표, 위협 모델(매체 비활성화 우회) | 문서 반영 | **완료 (2026-10-12)** |

**검증**(구현 세션): 단계마다 `check.sh` 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, 구간 대조 `match` 12줄, `pip-audit`·`bandit` 통과. 새 시험의 변형 검사는 6-1a 6개·6-1b 10개 모두 잡았다. 등가 변형이던 규칙의 `decision_exists` 조건은 지웠다(결정이 없으면 비활성화 사실도 없다).

**방식** [확정 2026-10-12, 사용자 — 기록 표 방식으로 착수]: 매체에 "활성 회차" 열을 두는 방법도 있다. 하지만 결정·반응 표(쓰기가 많은 표) 둘에 열을 더하고 접수 경로 셋을 고쳐야 한다. 그래서 **접수 경로를 건드리지 않는 기록 표 방식**을 권한다(구현 세션). 이 방식도 결과는 정확하다(비활성화가 여러 번이어도 맞음).

**매체(게임) 쪽 요청** — 사용자가 전달(2026-10-12):
1. `subject_id`를 광고 전용 가명으로(필수, 계약 1.2): `campus_profile.user_uuid`를 그대로 보내지 말고 게임 서버만 아는 비밀로 만든 값 — 예: `HMAC-SHA256(ADS_SUBJECT_SECRET, "ads-subject/v1:" + user_uuid)` 앞 16바이트 → UUID. 분석에서 광고 반응과 사용자를 이어야 하면 비밀을 가진 게임 쪽이 가명 ↔ 사용자 대응을 접근 통제 아래에서 내보낸다.
2. 401·403 처리(검토 P3-1 보완): 401로 막힌 노출은 설정을 고친 뒤 같은 `reaction_id`·같은 내용으로 다시 보내는 운영 경로(자동 반복 없음). 403은 지금처럼 다시 보내지 않는다.
3. 판정 결과(검토 P3-2 확정): `status`·`reason_code`는 게임 서버 안에서만 쓰고 브라우저 응답에서는 뺀다. 화면에 판정이 필요하면 알려 달라(필요한 최소 표시를 같이 정한다).

### 8.4.3 6-2 외부 검토 후속 (코드 `7c4714b`·문서 `30b0195`, 2026-10-12)

**계기**: 외부 검토가 P2 4건·P3 2건을 냈다. 구현 세션이 코드와 실제 MySQL로 다시 확인했고 6건 모두 맞다(두 연결 임시 시험으로 재현하고 실행 뒤 지움). 구현 세션이 더 찾은 것 둘: ① 매체 비활성화 순서 문제와 같은 원인으로 **결정 쪽에도** 구멍이 있다 — 비활성화가 커밋되기 전에 만든 결정은 `decided_at`이 비활성화 시각보다 뒤가 되어, 매체를 다시 켠 뒤 그 결정의 반응이 인정된다(재현) ② `context` 숫자: 2^64를 넘고 double 범위 안인 정수는 오류 없이 실수로 바뀌어 저장되고 되읽으면 다른 값이다(재현). 503 건은 계약의 결정 `POST` 설명에 "멱등하지 않다, 무해하다"가 이미 있고, 틀린 것은 `Unavailable` 설명이다.

| # | 결정 [확정 2026-10-12, 사용자] | 지금 반영(결정·문구 정정) | 구현 뒤 반영(6-2f) |
|---|---|---|---|
| 1 | 매체 비활성화와 판정·결정의 순서 — **B. 매체 행 = 매체 생명주기 잠금**: 비활성화는 지금처럼 배타 잠금(UPDATE)을 잡은 뒤 시각을 정하고, 판정은 시작 전에 결정 소유 매체 행을 공유 잠금으로 한 번 지나가며(진행 중인 비활성화의 커밋을 기다림), 결정은 저장 트랜잭션 안에서 매체 행을 공유 잠금으로 읽어 활성 여부를 확인한다. ORM에 없는 `FOR SHARE`는 SQL로 | 설계 §10 "매체 비활성화와 판정·결정의 순서"(원인·규약·잠금 순서·전제), "반응 판정 세부" ⑪ (사)와 6-1 ③ 행에서 가리킴 | **6-2f 완료**: 설계 §10 [구현 예정] → 해시, 위협 모델 T45 대책 ⑥(순서 규약, 시험 8개)·§5.2 |
| 2 | `context` 숫자 범위: 정수·실수 모두 **−(2^53−1) ~ 2^53−1**(중첩 객체·배열 안 포함). 범위 밖이면 저장 전에 400. 큰 정수·정확한 소수는 문자열로 보낸다 | 설계 §10 "결정 API 세부" ⑪ | **6-2f 완료**: 계약 1.3.0(`Context` 설명·규약 크기 제한·"v1.3 변경" 1번), 매체용 요약 "알아 둘 값", 위협 모델 T35 ⑪·T12, DRD 0.35(R-12·결정 `context`·C1 입력·D-2에 숫자 범위, 스키마 변화 없음) |
| 3 | 503의 뜻 — **A. 문구만 정정**: "성공을 확인하지 못했다(저장됐을 수도 있다)". 반응은 같은 `reaction_id`로 다시 보내거나 `GET`으로 확인, 결정은 다시 요청(새 결정이 생겨도 무해, 계약 결정 `POST` 설명대로). 완전한 해결(결정 요청 멱등)은 Step 5 **5-5**로 남긴다 | 계약 `Unavailable`·`createDecision`(1.2.0 안), 매체용 요약 3번, 설계 §10 "503은 성공을 확인하지 못했다는 뜻"·"결정 API 세부" ⑨ 정정, 설계 §8 Step 5 5-5·§2, 이 계획 §8 요약 | 설계 §10 "503은 …"에 주석 정정 기록(코드 주석 세 곳·시험 주석 두 곳은 6-2d `253334b`), 위협 모델 T35 ⑧ 정정 |
| 4 | DRD 물리 제약은 실제 MySQL 구현대로 적고 논리 규칙과 물리 구현을 나눈다 | DRD 0.34: §4.3 표기에 구분(MySQL은 조건부 유일 제약을 만들지 않음, W036), O6 `open_campaign`·B2 `signup_grant_wallet`(DB 계산 열 + `UNIQUE`) 행, `reaction_ref`는 NULL 허용 일반 `UNIQUE`, §4.4 무결성 표 세 행. **D-7**(충전 외부 거래 ID, 계획)도 같은 방식(`TOPUP` 줄에만 채우는 NULL 허용 `UNIQUE` + `CHECK`)으로 적었다(문서 세션 판단) | 없음 |
| 5 | 응답 스키마 확장 — **A.** 공개 응답 스키마(`Ad`·`Decision`·`Reaction`·health)는 추가 필드를 허용하고, 서버 출력은 시험에서만 스키마를 닫아 검사한다. 요청 스키마는 닫힌 채 둔다. 호환으로 허용하는 것은 새 선택 필드 추가뿐 | 설계 §10 "공개 응답 스키마의 추가 필드" | **6-2f 완료**: 계약 1.3.0(응답 스키마 `Ad`·`Decision`·`Reaction`·`/health`에서 `additionalProperties: false`를 빼고 규약 "필드 추가"에 "서버는 계약에 적힌 필드만 내보낸다(시험으로 검사), 응답 필드의 호환 변경은 새 선택 필드 추가뿐"), 매체용 요약, 위협 모델 T33 ⑥ |
| 6 | C1 공통 설명: 공개 경로에 `/c/{token}`, 인증보다 먼저인 전역 전송 상한, 전환 판정 요약을 현재 규칙으로, "클릭은 매체가 보고하지 않는다"로 통일 | 계약 규약 "인증"(전역 상한 2 MiB + 64 KiB → 인증 전 413, 그보다 작으면 인증 → 16 KiB)·`PayloadTooLarge`·"확정된 항목" 전환·반응 `PUT` 설명(1.2.0 안), 설계 §10 전환 행 정정 | 없음 |

**계약 버전**: 지금 반영한 정정은 형식·동작 변화가 없어 **1.2.0 안의 정정**으로 했다(문서 세션 판단, 구현 세션 의견과 같음 — 계약 "v1.2 변경" 끝의 "문구 정정", 설계 §10 "계약 v1.2"). 범위 밖 숫자 400(2번)은 매체에 새 요구라 구현 뒤 **1.3.0**과 "v1.3 변경" 절로 올렸다(6-2f, §8.4.1 3번, 설계 §10 "계약 v1.3").

**단계** (구현 세션 계획, 한 단계 = 한 커밋, **완료 2026-10-12**)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-2a `masters`·`records` — 판정 쪽** | `masters.api`에 매체 행 공유 잠금 통과 함수(SQL `FOR SHARE`). `records.ordering.wait_for_inflight_receipts`가 결정 행 다음에 결정 소유 매체 행을 지나간다. 남의 보고는 지금처럼 바로 돌아간다 | 두 연결 시험: 비활성화 커밋을 미룬 채 판정을 시작하면 판정이 기다리고 커밋 뒤 거부(검토 재현), 판정 순서를 바꿔도 상태·과금·근거가 같음. 비활성화 전에 접수된 반응은 그대로 인정. 다른 매체의 보고, 다른 매체 반응의 판정은 기다리지 않음 | **완료 `3827185`** — `masters.api.media_active_for_share(매체)`(ORM이 만든 조회에 `FOR SHARE` 절만 붙임), 커밋을 미뤄 두는 시험 도우미 `tests/concurrency.Uncommitted`(기존 접수 순서 시험도 씀). 시험 `JudgmentWaitsForDeactivationTests` 4개. 시험 1,314개 |
| **6-2b `records` — 결정 쪽** | `decide`가 저장 트랜잭션 안에서 매체 행을 공유 잠금으로 읽어 활성 여부를 확인. 비활성이면 403, 결정 없음 | 두 연결 시험: 비활성화 커밋을 미룬 채 결정을 요청하면 기다린 뒤 403·결정 0건. 결정이 진행 중이면 비활성화가 그 커밋을 기다리고, 그 결정의 이후 반응은 `media_deactivated`. 결정끼리, 다른 매체의 결정은 서로 막지 않음 | **완료 `e872006`** — 잠금은 커밋까지(C1 뷰는 응답 조회까지 한 트랜잭션). 시험 `DecisionWaitsForDeactivationTests` 4개. 시험 1,318개 |
| **6-2c `foundation` — 숫자 범위** | `parse_json`에서 모든 숫자(중첩 포함)를 ±(2^53−1)로 제한, 범위 밖이면 400 | 10^400·−10^400·2^64+1·2^53 → 400·결정 0건. ±(2^53−1)과 실수 경계값 → 201, 되읽은 값이 같음 | **완료 `9189af8`** — 상한 `MAX_JSON_NUMBER` = `MAX_AMOUNT`, 상한보다 자릿수가 많은 정수는 변환하지 않고 거절, 본문 전체 오류라 `errors[]` 없음(`detail`이 범위와 "문자열로"를 알림). 시험 1,320개 |
| **6-2d 시험·주석 — 계약 정합** | `contract_support`가 우리 응답을 검사할 때 응답 스키마 사본을 닫는다(계약이 아직 닫혀 있어 지금은 결과가 같다). 503을 "저장하지 않았다"로 적은 코드 주석 두 곳(`serving_api/views.py` 결정 뷰, `serving_api/auth.py`의 `OperationalError` 처리)을 사실대로 | 계약에 없는 응답 필드를 넣으면 시험이 실패(변형 검사) | **완료 `253334b`** — `properties`가 있는 객체 스키마를 모두 닫은 사본(응답 스키마·`components`)으로 검사, 자유 형식 `Context`는 열어 둠. 오류 본문 `Problem`도 닫혀 검사됨(지금 응답은 통과). 503 주석은 코드 세 곳·시험 두 곳. 시험 1,322개 |
| **6-2e 측정**(커밋 없음) | 질의 수 재측정, `check.sh` | 기준선 변화 기록. 예상: 결정 10 → 11, 반응 39 → 40, 클릭 27 → 28 | **완료(커밋 없음)** — 결정 11 · 반응 40 · 클릭 28(전 10 · 39 · 27). 6-2a 직후(`3827185`)는 10 · 40 · 28이라 반응·클릭 +1은 6-2a 판정 대기, 결정 +1은 6-2b다. 6-2c·6-2d는 변화 없음 |
| **6-2f 문서** | 구현 세션이 커밋 해시와 함께 따로 요청: 계약 1.3.0과 매체용 요약, 설계 §10 [구현 예정] → 해시(⑪ (사)·6-1 ③ 포함), 위협 모델 T45·T35, DRD 검증 규칙의 숫자 범위, 질의 수 기준선(위 표의 "구현 뒤 반영") | 문서 반영 | **완료 (2026-10-12)** — 위 표의 "구현 뒤 반영", 설계 §2·§3·§8·§10("계약 v1.3" 행 추가), 부하 시험 문서의 결정 질의 수 |

**검증**(구현 세션): 단계마다 `check.sh` 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신(스키마 변화 없음), 20 동시 부하·불변식, 구간 대조 `match` 12줄, `pip-audit`·`bandit` 통과. 시험 1,310 → 1,314(6-2a) → 1,318(6-2b) → 1,320(6-2c) → 1,322(6-2d). 변형 검사는 6-2a 5개·6-2b 4개·6-2c 6개·6-2d 5개 모두 잡았다. 처음에 놓친 것과 보강: 6-2a의 `FOR UPDATE` 변형은 SQL 문자열로만 잡혔는데 6-2b의 "결정끼리 막지 않음" 시험이 동작으로 잡는다. 6-2b의 "잠금을 트랜잭션 밖에서 읽기" 변형은 시험이 결정을 바깥 트랜잭션 안에서 불러 놓쳤고, 결정을 저장 직전에 멈추는 시험으로 바꿔 잡는다. 6-2d의 "맨 바깥 인라인 스키마를 닫지 않기" 변형은 `/health` 사례를 더해 잡는다.

**구현 세션 판단 하나**: 다른 매체가 남의 결정에 보낸 보고는 지금처럼 기다리지 않는다. 이런 보고는 지금도 인정된 유형 같은 다른 근거 값을 판정 시점에 읽고, `media_deactivated_at`도 같은 취급이라 새 예외가 생기지 않는다(설계 §10 "매체 비활성화와 판정·결정의 순서" (마)). 근거 값까지 고정할지는 사용자가 원하면 다시 정한다.

**매체(게임) 쪽 요청** — 6-2 서버 작업이 끝나 이제 유효하다(사용자가 전달):
1. `context` 안의 숫자는 ±(2^53−1) 안으로 보낸다(범위 밖은 400, 계약 1.3.0). 큰 ID·정밀한 값은 문자열로 보낸다.
2. 응답을 우리 계약 스키마로 검증한다면 모르는 필드를 허용하게 한다(1.3.0부터 응답 스키마가 열린다, 계약 규약 "모르는 필드는 무시").
3. 503: 반응은 지금처럼 같은 `reaction_id`로 재시도한다. 결정은 다시 요청하면 된다 — 새 결정이 생겨도 과금·표시에 영향이 없다.

### 8.4.4 6-3 초기 운영 보완 (O1~O8, 코드 `253334b`·문서 `164a7a6`, 2026-10-12)

**계기**: 리팩터링 세션이 Step 6-2 완료 시점(코드 `253334b`, 문서 `164a7a6`)을 초기 운영 관점으로 검토해 O1~O8을 냈다. 구현 세션이 근거를 코드에서 모두 확인했고, 다음 셋을 더 확인했다.
- `TRUSTED_PROXY_COUNT`를 빠뜨리면 가입 제한뿐 아니라 로그인 잠금(axes, 아이디 + IP 기준)과 감사 로그의 IP도 무너진다.
- 로그 시각은 이미 UTC다(Django가 `TIME_ZONE = "UTC"`로 프로세스 시간대를 맞춘다). 다만 `Z` 표기가 없다.
- 매체 행을 잠그는 것은 키 발급·교체와 활성 전환이다. 키 폐기는 매체 행을 잠그지 않는다.

**목적**: 계약(C1 등)은 바꾸지 않고, 첫 운영에서 걸릴 것을 막는다. 리팩터링 4차(L0 → L4, `DB_NAME=ads_refactor4`)가 같은 작업 트리에서 동시에 진행된다.

| # | 결정 [확정 2026-10-12, 사용자] | 지금 반영 | 구현 뒤 반영(6-3g) |
|---|---|---|---|
| O1 | 웹 서버가 `.env` 때문에 dev 설정으로 뜸 — **B**: `.env.example`에서 `DJANGO_SETTINGS_MODULE` 줄을 지운다. 웹 진입점(`wsgi`·`asgi`)은 `.env`의 설정 모듈을 무시한다(`load_env()` 전에 실제 환경변수에 있던 값, 없으면 prod). `manage.py`의 기본 dev는 그대로 두고(로컬 재현 절차 유지), 운영 호스트의 명령은 실제 환경변수로 prod를 지정한다 | 설계 §10 "웹 진입점의 설정 모듈", README(운영 호스트의 설정 모듈, 지금 `.env`의 dev 줄 주의) | **6-3g 완료**: README의 웹 진입점 문구, 위협 모델 T21(시험 3개) |
| O2 | 처리하지 못한 반응이 보이지 않음 — **A는 지금, B는 리팩터링 4차 뒤**. A(명령 쪽): `records.api.inbox_status()`(대기·보류·stuck·가장 오래된 대기 시간, 보류와 stuck은 겹치지 않게), `process_reactions --status`, 상시 처리 중 60초마다 상태 줄과 stuck 건수가 바뀌면 바로 출력(D1-①), stuck으로 넘어가는 순간 오류 로그 한 줄, 보류는 debug 로그로 규칙·사유. 읽기 전용 `ReactionAdmin`은 두지 않는다(D1-②). B: 관리자 첫 화면의 처리 현황 카드(세부는 B 구현 때 — **카드 선택지 A 확정 2026-10-13, 사용자**: 반응 처리 현황만, 중계 현황·판정 기준값은 두지 않음) | 설계 §10 "반응 처리 현황 노출"·§7-9 | **6-3g 완료**(A): README의 `--status`와 `idle` 줄의 뜻, 위협 모델 T37 ⑬(시험 4개). **6-3i 완료**(B): README(`--status` 행·알려진 사항의 관리자 화면), 설계 §10·§7-9, 위협 모델 T37 ⑬(시험 2개 더함) |
| O3 | 가입 제한(IP당 시간당 5회)이 단체 가입을 막음 — **B를 두 단계로**. 지금: `SIGNUP_MAX_PER_IP_PER_HOUR`를 환경값으로(기본 5, 세는 방식 그대로). 리팩터링 4차 뒤: `check --deploy`에 프록시 설정 누락 경고(`BEHIND_TLS_PROXY=1`인데 `TRUSTED_PROXY_COUNT=0`). **둘 다 임시방편이라 이후 보완이 필요하다** — 단체 가입은 환경값을 올렸다 내리는 운영 동작에 기대고 올리면 설계 §7-2 위험도 커진다. 프록시 경고는 설정 조합으로 추정한다(배포 방식 §7-14 미정). **→ 6-5에서 대체**(2026-10-13, 사용자: 가입 시도 제한을 두지 않고 신뢰할 프록시 수를 prod 필수로 — 두 임시방편을 걷어낸다, §8.4.6) | 설계 §10 "가입 시도 제한", README 배포 점검(프록시 수) | **6-3g 완료**(1단계): README "단체 가입"(`.env.example`은 6-3d가 고침), 위협 모델 T2(시험 2개)·T6(경고는 6-3h). **6-3h 완료**(2단계): README `check --deploy`·배포 점검, 설계 §10 "가입 시도 제한", 위협 모델 T6(시험 2개)·§6 잔여 위험(잡지 못하는 두 구성) |
| O4 | 로그로 요청을 추적하기 어려움 — **A**: `RequestIdFilter`가 컨텍스트 값이 비었으면 `record.request.request_id`로 채운다(Django의 4xx·5xx 요약 줄에도 `request_id`). 화면(교착·잠금 초과)과 클릭(`/c/{token}`)의 503에 원인 로그 한 줄(트레이스백 없이 오류 종류와 MySQL 오류 번호만). 응답은 바뀌지 않는다 | 설계 §10 "운영 로그" ①② | **6-3g 완료**: README "로그", 위협 모델 T22(O7과 함께 시험 6개) |
| O5 | MongoDB 설정이 빠져도 운영 서버가 정상처럼 돎 — **B**: 웹은 MongoDB를 쓰지 않으므로(헬스 체크 포함) 설정이 없어도 된다. `relay_events`는 `NotConfigured`를 일시 장애로 보지 않고 즉시 0이 아닌 코드로 끝난다. DB-2의 "Step 4에서 필수" 계획을 이 결정으로 바꾼다. **운영하면서 C(중계·내보내기 명령이 시작할 때 설정·접속 확인)로 바꾼다** | 설계 §10 "이벤트 저장소 설정", 이 계획 §7.3.3 DB-2 행 | **6-3g 완료**: README(중계는 설정이 없으면 끝남), 위협 모델 T41 ⑤(시험 3개) |
| O6 | DB 읽기·쓰기 시간 제한이 없음 — **C**: 배포 구성으로 미룬다(§7.3.4 #4, 연결 풀·워커 시간 제한과 함께). 그때까지 멈춤 감지는 O2의 상태 줄과 `--status` | 설계 §10 "DB 읽기·쓰기 시간 제한", §7.3.4 #4 | 없음 |
| O7 | 상시 명령의 장애 메시지에 시각이 없음 — **A + 로그 시각 형식 맞춤**: 상시 명령의 장애 문구와 상태 줄 앞에 UTC 시각(ISO 8601, `Z`, 문구는 그대로). 로그 형식의 시각도 ISO 8601 `Z`. 이후 B(logger로 전환, 다른 세션의 시험 3개 수정 필요)를 고려한다 | 설계 §10 "운영 로그" ③ | **6-3g 완료**: README "로그"의 시각 형식 |
| O8 | 운영 문서 — **B**: 상시·주기 작업 목록의 원본은 README, 설계 §7-9는 README를 가리킨다 | 설계 §10 "운영 작업 목록"·§7-9, README "상시·주기 작업"(빠진 `clearsessions`·`axes_reset_logs` 추가)·배포 순서·배포 점검·prod 필수값·매체 행 잠금(6-2) | 없음 |

구현 뒤 반영(6-3g, 구현 세션이 해시와 함께 따로 요청)에는 위 열 말고도 설계 §10의 [구현 예정] → 해시, 이 절의 완료 표시와 질의 수 확인 결과가 들어간다.

**계약**: 바뀌지 않는다(C1 요청·응답 형식과 상태 코드 그대로). 매체 쪽 요청도 없다.

**단계** (구현 세션 계획, 한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 시험은 변형 검사, **6-3a~6-3i 완료 2026-10-13**)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-3a O1** | `.env.example`의 `DJANGO_SETTINGS_MODULE` 줄 삭제, `wsgi`·`asgi`의 설정 모듈 결정 | `.env`에 dev가 있어도 웹 진입점은 prod로 기동을 시도한다(필수값이 없으면 실패). 실제 환경변수로 지정하면 그 값을 쓴다. `runserver`·부하·장애 시험은 영향 없음 | **완료 `9e6e374`** — `config.env.load_env_for_web()`(`.env`를 읽기 전의 실제 환경변수, 없으면 prod, `.env`의 다른 값은 읽음)를 `wsgi`·`asgi`가 쓴다. `.env.example`의 줄 자리에 이유. 시험 `WebEntrySettingsTests`(실제 `wsgi`·`asgi` 모듈을 새 프로세스로 불러 확인). 시험 1,325개 |
| **6-3b O4 + O7** | `RequestIdFilter` 보완, 화면·클릭 503 로그, 로그 시각 ISO 8601 `Z`, 두 상시 명령의 장애 문구·상태 줄에 시각 접두 | Django 요약 줄에 `request_id`, 503 로그 한 줄(트레이스백 없음), 기존 문구 시험 그대로 통과 | **완료 `ea23a81`** — `foundation.logging.UtcFormatter`, 503 원인은 `ApiErrorMiddleware`·`serving_api/clicks.py`(클릭은 결정 ID도). 두 명령은 경계 규칙 때문에 각자 `stamped()` 한 줄(모양은 시험이 묶음), `--status`에는 붙이지 않음. 응답은 그대로. 시험 `tests/test_ops_logging.py`. 시험 1,332개 |
| **6-3c O2-A** | `inbox_status`·`--status`·60초 상태 줄과 변화 시 출력·stuck 전환 로그·보류 debug 로그 | 보류와 stuck이 겹치지 않음, stuck 전환 로그는 한 번만, 서빙 질의 수 그대로. 커밋하면 리팩터링 세션에 알린다 | **완료 `90fce97`** — `inbox_status()`(질의 한 번: `received`·`held`·`stuck`·`oldest_age_seconds`, 가장 오래된 대기는 stuck 제외), 한가할 때 `idle {현황}` 줄(시작 직후·stuck 변화·`HEARTBEAT_SECONDS` = 60), 처리한 것이 있으면 기존 요약 줄. 한가할 때 주기마다 질의 +1, stuck 전환 확인은 실패 경로에서만 +1. 시험 `tests/test_ops_inbox_status.py`(가짜 시계). 시험 1,338개 |
| **6-3d O3(1단계)** | dev·prod에서 `SIGNUP_MAX_PER_IP_PER_HOUR`를 환경값으로(기본 5) | 설정 시험(환경값 읽기, 기본 5) | **완료 `a733e95`** — 1 이상만(0 이하·정수 아님은 기동 실패, `env_int(minimum=)`), `.env.example`에 값과 주의. 세는 방식 그대로. 시험 `SignupLimitSettingTests`(dev·prod). 시험 1,340개. **6-5b에서 걷어낸다**(가입 시도 제한 제거, §8.4.6) |
| **6-3e O5-B** | `relay_events`가 `NotConfigured`면 즉시 0이 아닌 코드로 종료. `prod.py`·`.env.example` 주석과 설정 시험의 이름·설명 수정 | 상시 실행에서도 설정이 없으면 바로 끝난다. 접속 장애(`PyMongoError`)는 지금처럼 다시 시도한다 | **완료 `5d2d517`** — `CommandError`(종료 코드 1, "이벤트 저장소 설정이 없어 중계를 멈춥니다: NotConfigured: …", `--once`도 같음). 보낼 이벤트가 없으면 설정을 읽지 않아 첫 이벤트 때 드러남. 설정 시험 이름 `test_prod_web_starts_without_an_event_store`. 시험 `tests/test_ops_event_store.py`(6-6c 에서 `test_event_relay.py` 로 옮김). 시험 1,342개 |
| 6-3f | 없음 — O6-C는 문서만(§7.3.4 #4) | — | 해당 없음(문서 `2ed04cc`에서 반영) |
| **6-3g 측정과 문서** | 질의 수 probe로 결정 11 · 반응 40 · 클릭 28이 그대로인지 확인하고 구현 뒤 반영 요청문을 낸다 | 기준선 그대로, 문서 반영(위 표의 "구현 뒤 반영") | **완료** — 결정 11 · 반응 40 · 클릭 28 그대로(HEAD `5d2d517`). 문서는 위 표의 "구현 뒤 반영"과 설계 §2·§7-9·§8·§10 해시 |
| **6-3h O3(2단계)** | 리팩터링 4차 뒤: 배포 점검에 프록시 설정 누락 경고(시스템 체크). 등록할 곳: `foundation/checks.py`(`deploy` 태그 시스템 체크)를 두고 `FoundationConfig.ready()`에서 import한다(리팩터링 세션과 정함, 2026-10-13) | `check --deploy`에서 TLS 종단 프록시 뒤인데 수가 0 이하면 경고. 프록시가 아닌 샘플 prod 환경의 경고 0, 동작·응답·질의 수 그대로 | **완료 `1509c10`** — 시스템 체크 `foundation.W001`(Warning): `SECURE_PROXY_SSL_HEADER`가 있고 `TRUSTED_PROXY_COUNT` ≤ 0. 결정의 "=0"을 "0 이하"로 넓혔다(하한 없는 환경값이라 음수도 들어오고, 그때도 `REMOTE_ADDR`만 쓴다). 실제 prod 설정의 네 조합 중 프록시 1·수 0만 `--fail-level WARNING`에서 종료 코드 1. 잡지 못하는 두 구성은 코드 주석과 위협 모델 §6. 시험 `tests/test_http_security.py` `DeployCheckTests`. 시험 1,355개. **6-5c에서 걷어낸다**(신뢰할 프록시 수를 prod 필수로, §8.4.6) |
| **6-3i O2-B** | 리팩터링 4차 뒤: 관리자 첫 화면의 처리 현황 카드. 무엇을 보일지 등 세부는 그때 정한다(착수 때 선택지 A로 정함) | 카드가 네 값을 보이고 stuck이면 강조, 빈 수신함이면 경고 없음, 서빙 질의 수 그대로 | **완료 `6d80ecb`** — 선택지 A(반응 처리 현황만, 2026-10-13 사용자). 관리자 첫 화면(`console/templates/operator/admin_index.html`)의 "운영 동작" 표 위, 템플릿 태그 `console_format.reaction_status`(= `records.api.inbox_status()`). 첫 화면 질의 +1(`records_reaction_pending_idx`). 반응 목록 링크 없음(D1-②). 시험 `tests/test_ops_inbox_status.py` `AdminIndexInboxCardTests`. 시험 1,357개 |

6-3h·6-3i는 리팩터링 4차(§8.4.5)가 끝난 뒤 시작해 6-3a~6-3g와 따로 완료를 적었다(번호는 문서 세션 판단).

**검증**(구현 세션): 단계마다 `check.sh` 종료 코드 0. 시험 1,322 → 1,325(6-3a) → 1,332(6-3b) → 1,338(6-3c) → 1,340(6-3d) → 1,342(6-3e), 리팩터링 4차(1,353) 뒤 → 1,355(6-3h) → 1,357(6-3i). 변형 검사는 6-3a 5개·6-3b 10개·6-3c 11개·6-3d 5개·6-3e 3개·6-3h 8개·6-3i 7개 모두 잡았다. 질의 수는 6-3i 뒤(HEAD `6d80ecb`)에도 결정 11 · 반응 40 · 클릭 28 그대로다. 메모: 6-3c에서 `--status`의 `return`을 지운 변형은 상시 루프로 들어가 끝나지 않아 세지 않았고, 멈추지 않는 두 형태로 다시 확인했다. 6-3d는 경계 1 사례를 더한 뒤 모두 잡는다. 6-3e에서 `PyMongoError` 재시도 튜플에 `NotConfigured`를 다시 넣는 것은 앞의 처리가 먼저 잡아 등가 변형이다.

**운영하면서 할 것**(번호 없음): O5를 C로(중계·내보내기 명령이 시작할 때 설정·접속 확인), O7을 B로(상시 명령의 출력을 logger로) 고려, ~~O3의 근본 보완(단체 가입 방식, 배포 방식 §7-14가 정해진 뒤 프록시 검사)~~ → 6-5가 대신한다(가입 시도 제한 제거·프록시 수 필수, §8.4.6), O2 카드에 중계 현황(선택지 B)이나 판정 기준값(선택지 C)을 운영 수치가 쌓이면 다시 검토. **[열림]** C1(매체 API) 503 로그(지금 트레이스백, `serving_api/auth.py`)를 새 한 줄 형식과 맞출지(설계 §10 "운영 로그").

**조정**: 리팩터링 4차와 같은 작업 트리에서 겹치지 않게 나눈다.
- 6-3이 맡는 파일(리팩터링이 건드리지 않음): `config/settings/*`, `.env.example`, `foundation/logging.py`, `foundation/middleware.py`, `serving_api/clicks.py`, `process_reactions`·`relay_events` 명령, `tests/test_settings.py`, `tests/helpers.py`.
- 그 밖에 손댈 파일: `config/wsgi.py`·`asgi.py`(6-3a)는 리팩터링 세션과 맞춘다. `records/processing.py`·`api.py`(6-3c)는 6-3 커밋 뒤에 리팩터링 세션이 다룬다.
- 새 시험은 공유 시험 파일 대신 새 파일에 두어 겹침을 줄인다.

### 8.4.5 6-4 코드 정리 (리팩터링 4차, 기준 코드 `5d2d517`·문서 `950946b`, 완료 2026-10-13)

**무엇**: 6-3a~6-3e 뒤의 코드를 하위 층부터 정리했다(L0 `foundation` → L1 `masters`·`events`·`assets` → L2 `billing`·`campaigns`). 같은 규칙·질의를 한 곳으로 모으고 쓰지 않는 공개 이름을 지운다. 동작은 바뀌지 않는다. 6-4f만 의도한 변화가 있는데, 바뀌는 것은 질의 수뿐이다. 계약·설계는 바뀌지 않는다.

**정한 것** [확정 2026-10-13, 사용자]
- **D-R1**: 서빙 경로의 질의 줄이기(A1·A2)는 하지 않는다 → §8.2.5 보류 표의 두 행(클릭의 결정 소유 매체 재조회, 판정의 결정 두 번 읽기).
- **D-R2**: 서빙 경로 밖의 질의 줄이기(6-4f)는 이번에 포함한다.

**단계** (한 단계 = 한 커밋)

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-4a 시험 먼저** | 한 곳으로 모을 규칙을 기존 시험이 잡는지 변형 검사로 확인했다. 변형 49개 중 30개는 기존 시험이 잡았고, 17개는 새 시험 11개(`tests/test_consolidated_rules.py` — 6-6c 에서 도메인 파일로 나눔)로 잡았다. 남긴 2개: ① 캠페인별 원장 합계의 유형 조건(`campaign_id`는 `CHARGE` 줄에만 있어 등가) ② `missing_event_ids`의 청크 안 순서(기존 순서 시험은 청크마다 하나만 빠진다. 이번 정리는 순서를 바꾸지 않는다) | `dd21833` |
| **6-4b L0 foundation** | 정수 검사 `is_int(value)`(int이고 bool이 아님)를 `foundation.api`로 공개 | `6195e59` |
| **6-4c L1 masters** | 키 활성 판정 2벌(목록 표시·인증)을 `_key_active(k, now)` 하나로, 매체 조회 3벌을 `_get_media(media_id, rows)` 하나로, 정수 검사는 `is_int`. `_now`를 처음 쓰는 곳보다 위로 옮겼다. 늘 `None`이고 읽는 곳이 없는 `IssuedKey.expires_at`을 지웠다 | `ce0c569` |
| **6-4d L1 events·assets** | `events.api`에서 밖에서 쓰지 않는 공개 별칭 `window_start`·`canonical_json`·`manifest_sha256`을 지웠다. `missing_event_ids`의 MongoDB 조회는 `_absent_from_mongo`로. 낡은 주석 2곳을 고쳤다. `assets.api.CONTENT_TYPES`를 검증의 `FORMAT_INFO`에서 만든다(형식 표 한 벌) | `604d05c` |
| **6-4e L2 billing·campaigns** | 그날 과금 합계 2벌을 `_charged_on(day, **scope)` 하나로 모았다(`_ledger_spent` 삭제). 중복 과금 결과 2벌은 `_duplicate`로, `spend_by_day`·`spend_by_campaign`은 `_spend_totals`로, 캠페인 종료 시각 검사 2벌은 `_check_ends_at`로 합쳤다. 정수 검사는 `foundation.is_int`(billing의 `_is_int` 삭제). 질의·문구·잠금 순서는 그대로다 | `814a0bc` |
| **6-4f 질의 수 줄이기** (perf, 의도한 변화) | 해제·종료 전이가 열린 재검토 요청을 닫을 때, 한 건씩 저장하던 것을 UPDATE 한 번으로 바꿨다. 캠페인 행 잠금 안이고 상태·닫은 시각은 그대로다. `create_ad_group`은 방금 넣은 게재 위치를 다시 읽지 않는다. **질의 수**: 해제 7 → 6, `apply`의 기간 종료 5 → 4, 광고그룹 만들기 11 → 10. 시험: 종료할 때 이미 닫힌(반려된) 요청은 바꾸지 않는다는 것을 더했다(`test_ending_a_suspended_campaign_closes_only_the_open_review_at_that_moment`). OPEN 조건을 지우는 변형이 살아남았기 때문이고, 예전 반복문에도 같은 빈틈이 있었다. 변형 7개 모두 잡음 | `39bb3da` |
| **6-4g 측정** | 150 동시 부하 시험과 서빙 질의 수 | 부하 통과, 결정 11 · 반응 40 · 클릭 28 그대로 |

**검증**(리팩터링 세션): 단계마다 `check.sh` 종료 코드 0. 시험 1,342 → 1,353(6-4a +11).

**정리하지 않는 것**(리팩터링 세션 판단)
- 일부러 남긴 중복:
  - `create_advertiser`의 필드 검증 try/except 3개
  - `engine/types._int`: `engine`은 프로젝트 모듈을 import하지 않는다
  - `events/hopcheck.py`의 정수 검사: `events` 본체는 `foundation`에 의존하지 않는다
  - 두 상시 명령의 `stamped()`: 6-3b의 결정
  - `records.services._atomic_if_needed`: 바꾸면 동작이 바뀐다
- 이번에 줄이지 않은 질의·읽기:
  - `masters.add_policy_version_bulk`의 슬롯마다 질의
  - `hopcheck`의 데이터 파일 두 번 읽기(아래 보고)
  - 백필의 과금 줄마다 반응 조회
  - 게재 위치 POST 화면(`ad_group_slots`)의 화면 전체 읽기
- 서빙 경로의 두 가지는 §8.2.5 보류(D-R1).

**보고**(설계 변경 아님): `hopcheck.load_hop`은 `ndjson.verify`가 검증한 manifest와 데이터 파일을 다시 읽어 쓴다. 그 사이 다른 프로세스가 폴더를 바꾸면, 검증한 바이트와 대조에 쓰는 바이트가 다를 수 있다.

**다음**: 6-3h(O3 프록시 설정 누락 경고, 등록할 곳은 §8.4.4)·6-3i(O2-B 관리자 화면 카드) — 둘 다 완료(`1509c10`·`6d80ecb`, §8.4.4).

### 8.4.6 6-5 배포 구성 전환 (nginx 앞단·HTTP 전제, 기준 코드 `6d80ecb`·문서 `6b4f662`, 완료 2026-10-13)

**계기**: 사용자가 광고 서버 앞에 nginx와 certbot을 두기로 하면서, HTTPS를 앞단과 Django 양쪽에서 다루는 설계를 중복으로 판정했다. 구현 세션이 코드·문서의 영향 지점을 조사했다(2026-10-13). 그 과정에서 6-3 O3 문제(같은 내부망에서 IP 기준 가입 제한이 정상 사용자를 막음)의 뿌리가 Step 0-2의 전제("IP가 사람을 구분한다")와 정하지 않은 배포 방식(설계 §7-14)이고, 6-3d 환경값과 6-3h 경고는 그 위에 얹은 임시방편임을 확인했다. 사용자는 HTTP 전제로 정리하고, 가입 시도 제한은 보안이 후퇴하더라도 지운 뒤 위협 모델로 관리하기로 했다. 운영 중 보완은 그 뒤에 한다.

**결정** [확정 2026-10-13, 사용자]

| # | 결정 | 지금 반영(6-5a) | 구현과 함께 반영 |
|---|---|---|---|
| 1 | **배포 구성**: 광고 서버 앞 nginx(certbot)가 TLS·80 → 443·HSTS·접속 허용 목록(강의실 라우터 IP + 메타버스 서버 IP)을 맡고 요청을 넘기기만 한다. Django는 127.0.0.1(또는 내부망)에만 바인딩. 첫 운영은 부트캠프 내부 한정. 브라우저·매체 서버 모두 광고 서버 nginx로 바로 온다(프록시 1단) | 설계 §7-14 닫음·§10 "배포 구성"·§2·§8(Step 3·6), 이 계획 §7.3.4 #9·§8.1.6·§8.1.7 | README "운영 배포"(6-5d), 위협 모델 §2·§3 신뢰 경계(6-5d) |
| 2 | **Django는 HTTP 전제**: prod의 HTTPS 리다이렉트·HSTS·`BEHIND_TLS_PROXY` 제거, 세션·CSRF 쿠키 Secure 유지, `CSRF_TRUSTED_ORIGINS` prod 필수, `check --deploy`의 `security.W004`·`W008`은 "nginx 담당" 사유로 침묵하고 `W021` 침묵은 지움(경고 0 유지) | 설계 §10 "배포 구성" | 6-5d: README·`.env.example`, 위협 모델 §6(HTTPS·접속 통제는 nginx에 의존, Django 포트가 열리면 우회) |
| 3 | **IP 판정 골격 유지**: `client_ip`·로그인 잠금(아이디 + IP)·감사 로그 IP 그대로. prod `TRUSTED_PROXY_COUNT` 필수·1 이상(기본값 없음, dev는 0). 6-3h `foundation.W001` 제거 | 설계 §10 "배포 구성", §8.4.4 O3·6-3h 행 | 6-5c: README 배포 점검·`check --deploy` 절, 위협 모델 T6·§6("설정 조합으로만 잡음" 닫힘) |
| 4 | **가입 시도 제한 제거**: `SignupAttempt`·`SIGNUP_MAX_PER_IP_PER_HOUR`·가입 화면의 429를 지운다. 로그인 잠금은 그대로 | 설계 §10 "가입 시도 제한"·§5.1·§7-5, §8.4.4 O3·6-3d 행 | 6-5b: 계약 C6 `/signup`, DRD(가입 시도 표·가입 흐름·L2), 위협 모델 T2·T43, README "단체 가입" |
| 5 | **정적 파일은 Django**(WhiteNoise), nginx는 통로만 | 설계 §10 "정적 파일 서빙" | 6-5e: `requirements.txt`, README, DRD 정적 파일 행, 설계 §9 호환 게이트 결과 |
| 6 | **콘솔 분리 대비**: 프론트 서버가 브라우저 대신 Django를 부르면 IP 판정을 신뢰할 프록시 주소 기준으로, Django 바인딩을 내부망으로 | 설계 §6.6 "다시 점검할 것" 두 행 | 없음 |

**받아들이는 것**(보안·운영 정책의 공백 — 위협 모델에서 관리하고 운영 중 보완한다)
- 부트캠프 내부 사용자의 다중 계정: 가입 횟수 제한이 없다. 알아채는 것은 감사 로그 `account.signup`(IP = 강의실)과 운영 화면의 광고주 목록(최근 가입순), 정리는 관리자 비활성화·포인트 조정이다. 재검토는 메타버스 포인트 연계(C5) 때와 외부망 공개 때(설계 §7-2).
- Origin 헤더가 없는 POST의 Referer 검사와 로그인 뒤 이동 주소(`next`)의 https 강제가 빠진다. CSRF 토큰 검사와 "같은 호스트로만"은 그대로다.
- HTTPS와 접속 통제는 nginx 설정에 전적으로 의존한다. Django 포트가 열리면 nginx를 우회할 수 있다(바인딩 규칙에 의존).

**계약**: C1(매체 API)은 바뀌지 않는다(매체 쪽 요청 없음). C6(콘솔 API 초안)은 `/signup`의 "IP당 가입 시도 횟수가 제한된다"와 429를 뺀다 — 서버에서 제한을 지우는 6-5b와 같은 커밋.

**문서를 고치는 방식**: 이번 수정은 **사용자 지시로 구현 세션이 문서도 고친다**(문서 세션은 6-5가 끝날 때까지 광고 서버 문서를 손대지 않는다). 위협 모델이 인용한 시험이 실제로 있는지 경계 시험(`tests/boundaries/test_threat_model_sync.py`)이 검사하므로, 시험을 지우거나 바꾸는 단계는 그 사실을 적은 문서(위협 모델·README·DRD·계약)를 **같은 커밋**에 담는다. 결정·계획은 먼저(6-5a), 완료 기록은 마지막(6-5f)이다.

**단계** (한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 시험은 변형 검사, 단계마다 사용자 확인 뒤 착수)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-5a 결정·계획** | 설계 §7-14·§10·§6.6·§5.1·§7-5·§2·§8, 이 계획 §7.3.4 #9·§8.1.6·§8.1.7·§8.4.4·이 절·§8 요약·§10 | 문서만 | **완료 `b9edb2b`** |
| **6-5b 가입 시도 제한 제거** | `foundation/signup_limit.py`, `SignupAttempt`(마이그레이션 `foundation/0003`, 테이블 삭제), 가입 뷰의 호출과 429 화면(`signup_limited.html`), `SIGNUP_MAX_PER_IP_PER_HOUR`(base·dev·prod·`.env.example`), `foundation.api` 공개 이름 2개, 관련 시험 | 같은 IP의 6번째 가입도 된다, 마이그레이션 최신, 로그인 잠금 시험 그대로 | **완료 `5e69276`** — 새 시험 `test_signup_has_no_attempt_limit_even_from_one_ip`(한 IP에서 실패 6번·가입 6번, 지우기 전 코드에서는 6번째 시도가 429로 실패함을 먼저 확인), 지운 시험: 가입 제한 2개·`SignupLimitSettingTests` 2개·화면 점검의 가입 제한 사례. `env_int(minimum=)`은 6-5c가 쓰므로 남김. 같은 커밋의 문서: 계약 C6 `/signup`(429·문구), DRD 0.36(A2 [제거]·가입 흐름·보존 기간·L2), 위협 모델 T2(인용 시험 교체)·T6·T43 ⑪·§6 문구, README "단체 가입" 삭제·배포 점검 문구. 시험 1,357 → 1,354 |
| **6-5c 신뢰할 프록시 수 필수** | prod `TRUSTED_PROXY_COUNT` 필수·1 이상(`env_int`에 `required`), 6-3h `foundation/checks.py`와 import·시험 제거, 시험의 prod 환경(`PROD_ENV`)과 `check.sh` 배포 점검 환경 | 없거나 0이면 prod 기동 실패, `check --deploy` 경고 0 | **완료 `6c5aa6d`** — `env_int(..., required=True, minimum=1)`(`env_int`에 `env_str`·`env_list`와 같은 `required`), 기본값 없음(1을 기본으로 두면 Django 포트가 노출됐을 때 위조가 통한다), dev는 0 그대로. 6-3h `foundation/checks.py`·`apps.py` import·`DeployCheckTests`의 경고 시험 2개 삭제. 시험 `test_prod_requires_a_trusted_proxy_count_of_at_least_one`(0·−1·문자 거절, 2는 받음, dev 0)과 필수값 목록에 추가, 시험의 prod 환경·`check.sh` 배포 점검 환경에 `TRUSTED_PROXY_COUNT=1`. 변형 6개 모두 잡음. 같은 커밋의 문서: 위협 모델 T6(인용 시험 교체)·§6("설정 조합으로만 잡음" → "Django 포트가 nginx 밖에 열리면 우회"), README prod 필수값·배포 점검·`check --deploy` 절, `.env.example` 주석. 시험 1,354 → 1,353 |
| **6-5d Django HTTPS 제거** | prod의 HTTPS 리다이렉트·HSTS·`BEHIND_TLS_PROXY` 제거, `CSRF_TRUSTED_ORIGINS` 필수, 경고 침묵 교체(W004·W008, W021 제거), HTTPS 시험 정리 | prod에서 리다이렉트·HSTS 꺼짐·Secure 쿠키 켜짐, `https` 출처의 로그인 POST가 신뢰 출처가 있으면 통과·없으면 403, `CSRF_TRUSTED_ORIGINS`가 없으면 기동 실패, 경고 0 | **완료 `f744769`** — prod의 `SECURE_SSL_REDIRECT`·`BEHIND_TLS_PROXY`(`SECURE_PROXY_SSL_HEADER`)·HSTS 3줄·`env_bool` import 삭제, 쿠키 Secure에 이유 주석, `SILENCED_SYSTEM_CHECKS` = W004·W008(사유), `CSRF_TRUSTED_ORIGINS = env_list(..., required=True)`. 시험: `test_prod_leaves_https_to_the_front_proxy_but_keeps_secure_cookies`(예전 환경값이 남아도 리다이렉트·HSTS·프록시 헤더 없음, Secure 쿠키 켜짐)가 HSTS 헤더·HTTPS 강제 시험 2개를 대신하고, `test_a_login_post_from_the_https_front_needs_the_trusted_origin`(https 출처의 로그인 POST — 신뢰 출처가 없으면 403, 있으면 302), prod 필수값 목록에 추가, 시험의 prod 환경·`check.sh`에 `CSRF_TRUSTED_ORIGINS`. 변형 6개 모두 잡음. 같은 커밋의 문서: README(prod 필수값·"배포 구성"·`check --deploy` 절), `.env.example`(HTTPS 3줄 삭제·`CSRF_TRUSTED_ORIGINS` 필수 주석), `config/env.py` 주석, 위협 모델 §2·§3 신뢰 경계(nginx)·T10·§6("HTTPS·접속 통제는 앞단 nginx에 의존"), 이 계획 0-4 절 표시. 시험 1,353 그대로(2개를 지우고 2개를 더함) |
| **6-5e 정적 파일** | `whitenoise`(`requirements.txt`), 미들웨어, `STATIC_ROOT` 주석 | `collectstatic` 결과를 로그인 없이 Django가 서빙(콘솔·관리자 CSS 200, `Content-Type`·`nosniff`), 호환 게이트(전체 시험·`check.sh`) | **완료 `dd53bda`** — `whitenoise~=6.12.0`, `whitenoise.middleware.WhiteNoiseMiddleware`를 `SecurityMiddleware` 바로 뒤(보안 헤더 안쪽, 로그인·역할 검사 앞), `STATIC_ROOT`·`.env.example` 주석. 시험 설정은 `STATIC_ROOT`를 빈 임시 폴더로(없으면 WhiteNoise가 경고), dev도 prod처럼 `STATIC_ROOT`를 환경변수로 받고 부하 시험은 임시 정적 폴더를 넘긴다(전체 점검의 부하 시험에서 "No directory" 경고가 나서). 시험 `tests/test_static_serving.py`(모은 콘솔·관리자 CSS·JS가 로그인 없이 200·`Content-Type`·`nosniff`, 모으지 않은 파일 404). 변형 2개 모두 잡음(미들웨어를 빼면 404, `SecurityMiddleware`보다 앞에 두면 `nosniff`가 빠짐). 같은 커밋의 문서: README(dev·배포 순서의 `collectstatic`·알려진 사항), DRD 0.37 §2.2, 설계 §9 WhiteNoise 게이트. 시험 1,353 → 1,355, `pip-audit`에 whitenoise 포함 통과 |
| **6-5f 측정·완료 기록** | 질의 수 probe, 설계 §2·§8·§10의 [구현 예정] → 해시, 이 절·§8 요약·§10 | 결정 11 · 반응 40 · 클릭 28 그대로 | **완료(이 커밋)** — 질의 수 결정 11 · 반응 40 · 클릭 28 그대로(HEAD `dd53bda`). 설계 §10 세 행의 [구현 예정] → 해시와 구현 세부, §2·§8(Step 0-2·0-4·6-3·6-5 표시), §10 "웹 진입점의 설정 모듈"의 HSTS·리다이렉트 문장, DRD 0.38(C1·C3 HTTPS는 nginx에서 종단), 이 계획 0-2 IP 판정 줄. 문서 전체에서 바뀐 사실과 어긋나는 문장을 찾아 고쳤다(기록·이력 문장은 그대로 두고 "6-5에서 바뀜"만 표시) |

**검증**(구현 세션): 단계마다 `check.sh` 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`(6-5e부터 whitenoise 포함)·`bandit` 통과. 시험 1,357 → 1,354(6-5b) → 1,353(6-5c) → 1,353(6-5d, 2개를 바꿈) → 1,355(6-5e). 변형 검사는 6-5c 6개·6-5d 6개·6-5e 2개 모두 잡았고, 6-5b는 새 시험이 지우기 전 코드에서 실패함(6번째 시도가 429)을 먼저 확인했다. 질의 수는 결정 11 · 반응 40 · 클릭 28 그대로다. 메모: 6-5d의 첫 변형 검사는 시험 이름 여럿을 한 변수로 넘겨(zsh는 변수를 단어로 나누지 않는다) 모두 로드 오류로 "잡힘"이 나와 버리고 다시 돌렸다. 6-5e의 첫 `check.sh`에서 부하 시험(dev 설정)이 WhiteNoise의 "No directory" 경고를 내, dev도 `STATIC_ROOT`를 환경변수로 받고 부하 시험이 임시 폴더를 넘기게 했다.

**정하지 않은 것**(이 수정과 독립): WSGI 서버 선택과 `requirements.txt`, 시간 제한 순서(§7.3.4 #4), nginx 502/504의 본문 형식, nginx의 요청 ID 형식(§7.3.4 #9).

**조정**: 리팩터링 4차는 끝났다(§8.4.5). 문서 세션은 6-5 동안 멈춘다.

### 8.4.7 6-6 코드 정리 (리팩터링 5차 — 시험 코드 포함, 기준 코드·문서 `0b2166a`, 완료 2026-10-13)

**무엇**: 6-3h·6-3i·6-5 뒤의 코드와 **시험 코드**를 정리한다. 시험은 다른 시험이 같은 결함을 잡는 것만 지우고, 단계 이름으로 묶인 시험은 대상 도메인 파일로 옮기고, 파일마다 복사된 시험 도우미를 모은다. 제품 코드는 하위 층부터(L0 → L4) 같은 코드를 한 곳으로 모으고 쓰지 않는 것을 지운다. 동작은 바뀌지 않는다. 6-6g만 의도한 변화(콘솔 광고그룹 상세의 질의 −1)가 있다. 계약·설계는 바뀌지 않는다. 리팩터링 세션이 ponytail-audit(과잉 설계 점검)으로 영역 넷(L0·L1과 scripts, L2~L4, 서빙·판정 시험, 화면·보안 시험)을 훑어 후보를 냈다.

**정한 것** [확정 2026-10-13, 사용자]
- **D-1 위협 모델 인용**: 위협 모델이 인용한 시험을 지울 때는 **인용을 먼저 대체 시험으로 바꾸고(6-6b) 그 뒤에 지운다(6-6c)** — 두 커밋 모두 `test_threat_model_sync`를 통과한다. 이번 수정의 문서는 **리팩터링 세션이 직접 고친다**(문맥·정합성. 문서 세션은 6-6 동안 광고 서버 문서를 손대지 않는다).
- **D-2 마이그레이션 이행 시험**: `tests/test_migrations_basis.py`·`test_migrations_funnel_backfill.py`·`test_migrations_mysql_constraints.py`(9개)를 지운다. 기존 데이터를 옮기거나 검사하는 마이그레이션(`records` 0007·0009, MySQL 제약 전환)을 지키던 시험인데, 그 마이그레이션 이전 상태의 DB가 남아 있지 않다 — 개발 DB는 모두 개인용이고 운영 DB는 배포 때 처음부터 만든다. 마이그레이션 파일은 그대로다(새 DB는 계속 순서대로 적용한다).
- **D-3**: 콘솔 광고그룹 상세의 캠페인 읽기(`get_campaign`, 질의 2번 — 캠페인과 열린 재검토 요청)를 이름만 읽는 `campaign_names`(1번)로 바꾼다. 나머지 질의 줄이기는 보류(아래 "보고만").

**시험을 지우는 기준**: 지울 시험마다 그 시험이 잡는 결함을 제품 코드 변형으로 만들어, **대체 시험이 같은 변형을 잡는지** 돌려 봤다(6-6a — 공유 작업 트리를 건드리지 않게 HEAD 사본에서). 대체 시험이 못 잡으면 지우지 않고 단언을 옮기거나(합치기) 남긴다.

**단계** (한 단계 = 한 커밋, `check.sh`(`DB_NAME=ads_refactor5`))

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-6a 시험 먼저** | 폐기 후보 32개의 변형 61개. 대체 시험이 잡음 52, 지울 시험은 못 잡고 대체 시험만 잡음(대체가 더 강함) 6, 대체가 못 잡음 3 → ① 사용자 테이블 이름을 바꾸는 변형은 `makemigrations --check`와 DB를 쓰는 시험 전체가 깨지므로 그대로 지운다 ② 업로드 가드를 CSRF 뒤로 옮기는 변형은 지금 동작이 같아 대체 시험이 못 잡지만, 설계 §10·위협 모델 T16이 "CSRF보다 앞"을 결정으로 적었으므로 순서 시험(`test_guard_runs_before_the_csrf_middleware`)을 **남긴다** ③ 중계 뒤 outbox 구간의 미전송 수는 대체 시험이 보지 않아 `test_three_hops_agree_after_the_relay`를 지우지 않고 그 단언을 hopcheck 시험으로 **옮긴다**. 이름만 "잠금을 잡지 않는다"던 `test_a_report_for_a_missing_decision_takes_no_lock_and_is_still_stored`가 실제로 잠금 질의가 없음을 보게 고쳤다(옛 본문은 "없는 결정에도 잠금" 변형을 못 잡았다) | `3d48354` |
| **6-6b 문서: 결정·계획·인용** | 이 절·§8 요약·§10, 위협 모델의 인용 15곳(T3·T15·T19·T23·T28·T29·T30·T31·T37·T39)을 대체 시험으로, 이 계획의 옛 시험 표(0-3·0-5·1-1, DB-1 검토 표)에 "6-6에서 대체" 표시, 설계 §2·§8 Step 6 | `4eab7dc` |
| **6-6c 시험 폐기·합치기·옮기기** | 아래 폐기 39개·합치기 11개·옮기기. 시험 1,355 → 1,305 | `c161585` — 옮긴 미전송 0 단언이 6-6a 에서 대체가 못 잡던 변형을 잡음을 다시 확인. 같은 커밋의 문서: 위협 모델 T44 의 경쟁 시험 파일 경로, DRD 0.39(원장 순번 행의 검증 시험) |
| **6-6d 시험 도우미** | 아래 도우미 정리. 시험 수 그대로, 전체 시험 시간을 다시 잰다 | `d9de54b` — 전체 시험 143초 → 120초(MongoDB 미도달 시험 9개 각 3초 → 0.6초). 바꾼 경쟁 시험이 광고주 잠금·매체 행 잠금·입찰 버전 검사를 지우는 변형을 모두 잡음(3/3). 6-5b 흔적: 가입 시험이 IP 당 제한을 피하려고 요청마다 IP 를 바꾸던 것을 지움 |
| **6-6e L0·L1·scripts** | `config/settings/_env.py`의 `env_int`·`env_bool`이 `env_str`의 빈 값·필수 처리를 쓰게(`env_list`와 같게), `foundation/accounts.py` 필드 검증 반복 2벌을 하나로, 호출자 하나뿐인 감싸개(`foundation/http.is_api_path`·`events/ndjson._pointer_lock`·`events.api.event_id_for`), `assets/urls.py` 변환기는 `StringConverter` 상속, scripts의 빈 포트 찾기 3벌·중계 종료 반복 2벌·함수 안 중복 import, 낡은 주석 | `81c15b1` — 빈 정수 환경값을 없는 것으로 보는지 지금 시험이 잡지 못해 설정 시험에 한 줄(변형 3개 모두 잡음). `failure_test.py` 의 상시 명령 띄우기 2벌·복구 판정 감싸개 3개도 정리했고 processor-kill·relay-kill 시나리오(자체 임시 컨테이너)로 확인 |
| **6-6f L2~L4** | 콘솔 광고그룹 폼 뷰 4개의 같은 틀을 하나로, `records/services.py`의 "UUID 해석 → 조회 → 404" 3벌을 하나로, 아무도 import하지 않는 `billing/policies/base.py`의 `ChargePolicy` Protocol 삭제(설계 §6.2: 인터페이스는 `SelectionPolicy`·`AssetStorage`처럼 실제로 갈아끼우는 곳에만), `SlotForm`은 `PolicyValuesForm` 상속, 읽는 곳 없는 `BidView.created_by`, 호출자 하나뿐인 감싸개(`_creative_group`·`serving_api/auth._unauthorized`, 패치하는 시험이 없는 `console/views/ads._now`), `AdCreateForm(units=)`, 낡은 주석 | `613e3d7` — 상세 화면의 "← 캠페인" 링크와 이름 폼의 400 을 지금 시험이 보지 않아 단언 두 줄을 먼저(바꾸기 전 변형 11개: 기존 9, 단언으로 1, 등가 1 — 입찰의 `pointers` 는 마지막 조각 규칙과 같아 뺐다. 바꾼 뒤 변형 7개 모두 잡음), 서빙 질의 수 그대로, 슬롯 폼 HTML 바이트 단위로 같음. **계획과 다르게 남김**: `ChargePolicy` Protocol(설계 §4.7·Step 1-3 이 교체 지점으로 적었다 — 남기기로 한 `SelectionPolicy` 와 같은 처지), `AdCreateForm(units=)`(`console/forms.py` 가 `masters.api` 를 import 하지 않아 줄지 않는다) |
| **6-6g 질의 수 줄이기** (perf, D-3) | 콘솔 광고그룹 상세의 캠페인 이름 읽기. 질의 −1 | `0db492e` — 상세 화면 질의 13 → 12(`AdGroupPage.campaign` → `campaign_name`, 링크는 광고그룹의 `campaign_id`, 소유는 앞의 `get_ad_group` 이 확인). 링크의 주소·이름을 바꾸는 변형 2개 모두 잡음 |
| **6-6h 마무리** | `check.sh`, 150 동시 부하, 서빙 질의 수 probe(11 · 40 · 28 그대로), 문서 전체 정합 점검·완료 기록, DB 정리 | **완료(이 커밋)** — 150 동시 부하 모든 불변식 충족, 서빙 질의 수 결정 11 · 반응 40 · 클릭 28 그대로(HEAD `0db492e`), 이력 행 세 곳에 "6-6c 에서 옮김" 표시, 만든 DB(`ads_refactor5`·`ads_refactor5m`과 그 시험 DB) 삭제 |

**폐기**(39개 — 괄호는 같은 결함을 잡는 대체 시험)
- 화면마다 쓴 역할 차단(`!= 200`)은 접근 스윕(`test_access_sweep`)이 모든 경로·GET·POST에서 302·403·404로 본다: `test_access`의 `test_advertiser_cannot_open_admin_area`·`test_admin_cannot_open_advertiser_area`, `test_ad_create::test_only_advertisers`, `test_campaign_pages::test_admins_and_anonymous_do_not_see_advertiser_pages`, `test_points_page::test_only_the_advertiser`, `test_dashboard::test_only_the_advertiser_sees_it`, `test_operator_masters::test_only_admins_see_the_operator_pages`(관리자가 여는 것은 화면 내용 시험이 본다)
- 다른 시험의 부분집합: `test_access::test_signup_cannot_escalate_role`(`test_signup_ignores_role_field`) · `test_settings::test_prod_starts_with_valid_env`(`test_prod_web_starts_without_an_event_store`) · `test_campaigns_transitions`의 `test_ended_has_no_way_out`·`test_suspended_blocks_every_advertiser_action`(`test_transition_table_allows_only_listed`) · `test_campaigns_ended`의 `test_early_end_blocked_while_suspended`(`test_suspended_blocks_advertiser_status_change_but_allows_other_edits`)·`test_expired_campaign_image_not_servable_and_not_a_new_candidate`(`test_is_asset_servable_by_campaign_state`) · `test_campaigns_services::test_suspended_campaign_image_is_404_over_http`(`test_old_image_stays_servable_after_replacement_until_the_campaign_stops`) · `test_campaign_pages::test_a_review_request_on_an_active_campaign_is_refused_by_the_service`(`test_campaign_status_review_and_end`) · `test_masters_models::test_policy_cannot_be_overwritten_by_existing_pk`(`test_positional_and_keyword_upserts_and_new_instance_saves_cannot_overwrite`) · `test_user_model`의 `test_pk_is_uuid`·`test_table_name_is_explicit`(`tests/boundaries/test_model_conventions.py`) · `test_assets_validation::test_format_decided_by_content_not_extension`(`test_accepts_valid_png_and_jpeg`) · `test_judgment_scope::test_a_new_decision_without_an_impression_keeps_the_current_display`(본문이 같은 `test_a_next_decision_without_an_impression_does_not_end_the_display`) · `test_receipt_ordering::test_the_owners_own_receipts_still_queue_behind_each_other`(`test_a_later_receipt_cannot_commit_ahead_of_an_in_flight_earlier_one`) · `test_records_processing::test_a_rejected_duplicate_does_not_block_a_later_valid_type`(`test_the_second_report_of_the_same_type_is_a_duplicate_but_other_types_are_fine`) · `test_funnel_rules::test_full_funnel_in_order_is_accepted_and_charges_the_billing_unit_only`(`test_a_type_other_than_the_billing_unit_is_accepted_but_not_charged`) · `test_billing_charge::test_concurrent_charges_on_one_wallet_get_distinct_gapless_seqs`(조정·읽기까지 섞는 `test_charges_adjustments_and_reads_on_one_wallet_keep_seq_balance_and_spend_consistent`) · `test_event_hops::test_before_the_relay_mongodb_is_empty_and_outbox_shows_unsent`(`test_before_the_relay_it_is_a_lag_candidate_and_the_command_still_succeeds`) · `test_engine_filters::test_stale_active_campaign_past_end_is_rejected_by_period`(경계까지 보는 `test_each_filter_rejects_with_reason`) · `test_records_decision::test_inactive_slot_of_an_active_media_is_recorded_as_no_ad`(`test_inactive_slot_of_an_active_media_is_201_null_ad_and_recorded`)
- 구현 세부에 묶였거나 지키는 것이 없음: `test_billing_budget::RecomputeIsOneWriteTransactionTests`(모델을 바꿔 끼워 트랜잭션 안인지만 본다 — 잠금 대기까지 보는 `test_recompute_race`의 재계산 대 과금 시험 셋) · `test_event_decision::test_called_outside_a_transaction_both_are_committed_together`(양성 경로뿐 — 같은 클래스의 실패 시험) · `test_engine_policies::test_slot_constant_sanity`(시험 도우미의 상수를 시험)
- 마이그레이션 이행 9개(D-2)

**합치기**(시험 −11, 단언은 남는 시험으로 옮긴다): 잠금 화면 429 문구 → 5회 실패 시험 · 슈퍼유저의 역할 인자 무시 → 슈퍼유저 생성 시험 · SECRET_KEY 시험 3개 → 1개 · `test_session_cookies::test_secure_flags_in_prod_settings` → 6-5d 쿠키 시험이 옛 HTTPS 환경값 없이도 한 번 더 돈다 · 관리자 첫 화면 링크 시험 3개 → 1개 · `test_audit`의 덮어쓰기 시험 → 고유한 두 형태(`save(update_fields=…)`·`update_or_create`)만 `test_append_only_all_models`로 · 판정 근거 재기록 방지 → 상태 재변경 시험 · 조작된 홉의 manifest 단언 → hopcheck의 조작 시험 · 세 홉 일치 시험의 미전송 수 단언 → hopcheck의 중계 뒤 일치 시험

**옮기기**(시험 수 그대로): `tests/test_consolidated_rules.py`(6-4a)를 클래스마다 도메인 파일로(키 → `test_media_keys`, 원장·소진 → `test_billing_*`, 종료 시각·게재 위치 → `test_campaigns_services`, 재검토 → `test_campaigns_review`, 누락 확인 → `test_chunk_boundaries`) · `test_create_ad.py`(서비스) → `test_campaigns_services`(화면 시험 `test_ad_create.py`와 이름이 헷갈린다) · `test_console_root.py` → `test_access` · `test_db_errors.py` + `test_transient_db_errors.py` · `test_ops_event_store.py` → `test_event_relay` · `tests/test_judgment_scope.py` → `test_funnel_rules`(`tests/boundaries/test_judgment_scope.py`와 이름이 겹치고 다른 시험 파일의 기반 클래스를 import한다) · 캠페인 행 잠금 경쟁 4개 파일(`test_quota_races`·`test_ad_group_races`·`test_campaign_expire_race`·`test_review_release_races`) → `test_campaign_races.py`

**도우미 정리**: MongoDB 미도달 설정 블록 6벌 → `tests/mongo_support.unreachable_store()`(시험에서만 서버 선택 대기를 줄인다 — 미도달 시험 9개가 각 3초, 운영 값 `TIMEOUT_MS = 3000`은 그대로) · 경쟁 시험 골격(멈춤 → 둘째 작업 → 막힘 확인 → 재개) 9벌 → `tests/concurrency.py` · 배리어 동시 실행 → `tests/concurrency.py` · 매체 API 준비(버킷 초기화·세계·키·시계·클라이언트)와 결정 POST 5벌 → 공용 mixin · 시각(`at`·`utc`)·`PW`·`impression` → `tests/factories.py`, 경로 순회(`every_route`·`ROUTE_PARAM`) → `tests/helpers.py` — 다른 시험 파일에서 값·함수를 import 하던 결합이 그만큼 줄었다(기반 클래스는 그대로) · 한 줄짜리 중복(`make_second_admin` → `make_admin`, `never` → `support_app.checks.deny_all`)

**남기는 것**(중복처럼 보이지만 다른 결함을 잡는다): 업로드 가드 순서 시험(위 ②) · 서비스 층과 HTTP 층의 결정 시험(HTTP 층이 먼저 거르는 입력, 인증 층이 먼저 내는 403) · `test_logging`과 `test_ops_logging` · `test_account_profile`과 `test_my_account`(세션 키 교체 대 뷰가 요청을 넘기는지) · "동시 두 번" 쌍 3벌(광고 만들기·키 교체·포인트 조정은 입구가 다르다) · `test_step1_scenario`(조합 시험은 이것 하나, §6.7 합격 증거) · `tests/boundaries/test_judgment_scope.py`(소스 검사)와 `tests/test_judgment_scope.py`(동작)

**정리하지 않는 것**: 설계가 정한 교체 지점(`SelectionPolicy`·`AssetStorage` Protocol, `ASSET_STORAGE` 설정, 정책 등록·해제 통로 — 설계 §6.2·§4.7) · `campaigns/transitions.apply`의 `"expire"`(운영은 `expire_due`를 쓰지만 전이 표가 상태 기계의 문서이자 시험 대상이다) · `engine`의 `DEFAULT_POLICY`·`DEFAULT_FILTERS`(`engine`은 Django 설정을 모른다) · `setUpTestData` 전환(`World.api`가 모듈이라 복사되지 않는다)과 TransactionTestCase → TestCase 전환(트랜잭션 의미가 바뀔 위험, 이득 미측정) · `mysql_cluster.py`의 `attach` 합치기(클러스터를 띄워야 확인된다) · `ChargePolicy` Protocol·`AdCreateForm(units=)`(6-6f 행) · 시험 도우미 중 서명이 다른 과금 준비(`funded`·`charge`)·명령마다 다른 실행 감싸개·`load_test.py` 를 일부러 다른 모듈 이름으로 읽는 로더·파일마다 내용이 다른 세계 준비(결정 + 노출 + 처리, 일괄 슬롯) · `load_test.py` 의 Django import 를 모듈 위로(함수 안에서 늦게 import 하는 파일의 관례) · `create_advertiser` 의 try/except 3개(§8.4.5 판단 그대로) · 이전 차수에서 남긴 것(§8.2.4·§8.3.4·§8.4.5 — 근거를 다시 확인했다)

**검증**(리팩터링 세션): 단계마다 `check.sh` 종료 코드 0. 시험 1,355 → 1,305(6-6c), 전체 시험 156초 → 120초. 시험 코드 순감 814줄(시험 파일 127 → 115개), scripts −46줄, 제품 코드 −54줄(20개 파일). 변형 검사: 6-6a 61개(+ 고쳐 쓴 시험 1), 6-6c 1, 6-6d 3, 6-6e 9, 6-6f 18, 6-6g 2 — 대체가 못 잡은 것은 지우지 않거나 단언을 옮기거나 더했다. 150 동시 부하 통과, `failure_test.py` processor-kill·relay-kill 통과, 서빙 질의 수 결정 11 · 반응 40 · 클릭 28 그대로, 콘솔 광고그룹 상세 13 → 12. 메모: 변형 검사는 공유 작업 트리를 건드리지 않게 HEAD 사본에서 돌렸고, `--keepdb` 로 남긴 시험 DB 가 `check.sh` 를 "Type 'yes'" 에서 멈추게 해 변형용 DB 이름을 따로 썼다.

**보고만**(동작 변화라 구현 세션 몫): ① `scripts/failure_test.py`가 dev에 `STATIC_ROOT`를 넘기지 않아 WhiteNoise가 "No directory" 경고를 낸다(6-5e에서 `load_test.py`만 고쳐졌다) ② `events/models.py`의 `default=uuid.uuid7`은 쓰이지 않고 주석("UUIDv5")과 어긋난다(지우려면 마이그레이션) ③ 폼을 다시 그릴 때 서비스 오류의 응답 코드가 400 고정인 곳과 `status_of`(409 가능)인 곳이 섞여 있다 ④ 질의 보류: `create_ad`가 이미 잡은 광고주 잠금을 다시 잡음(−6), 대시보드가 캠페인 ID를 다시 읽음(−2), 결정 응답의 슬롯 이름 재조회(서빙 경로 11 → 10, §8.2.5 D-R1과 같은 이유로 보류). → 구현 세션이 ①~③을 6-7에서 고치고, ④는 보류 그대로다(§8.4.8).

### 8.4.8 6-7 리팩터링 5차 보고 후속 (기준 코드·문서 `5d75026`, 완료 2026-10-13)

**계기**: 6-6이 동작 변화라 고치지 않고 넘긴 네 건(§8.4.7 "보고만")을 구현 세션이 코드에서 확인했다(2026-10-13). 보고와 다른 점이 셋 있었다.
- **①은 정적 폴더만의 문제가 아니다.** `failure_test.py`는 시나리오마다 임시 폴더를 만들고 끝에 지운다. 그런데 이 프로세스의 Django 설정은 첫 시나리오 때 굳는다(DB 이름은 이미 직접 바꾼다). 그래서 둘째 시나리오부터 웹 앱은 지운 첫 폴더를 가리킨다. 환경변수로 `STATIC_ROOT`만 넘기면 둘째부터 "No directory" 경고가 다시 난다. 소재 이미지는 `MEDIA_ROOT`(첫 폴더)를 다시 만들어 그대로 남는다(`$TMPDIR`에 이미지가 든 `ads-failure-*` 폴더가 남아 있음을 확인).
- **②의 기본값에는 이유가 있다.** 쓰이지는 않지만, 모델 규약 시험 `test_every_primary_key_is_a_uuid7_and_nothing_auto_increments`가 모든 PK의 기본값이 `uuid.uuid7`인지 보면서 outbox 예외를 모르기 때문에 붙어 있다. outbox 예외는 설계 §10 "PK 규칙"·DRD R-2가 적은 UUIDv5다. 이 기본값은 위험하다: `event_id`를 빠뜨린 코드에 무작위 ID가 조용히 들어가, 같은 이벤트를 PK로 한 줄만 남기는 중복 차단이 무력화된다.
- **③에서 400이 409를 덮는 곳은 운영 화면 두 곳뿐이다.** 매체 등록(같은 이름의 매체)과 게재 위치 만들기(같은 매체에 같은 이름)로, 둘 다 서비스가 `Conflict`(409)를 던진다. 내 정보·비밀번호 변경의 400 고정은 서비스가 `ValidationError`만 던지므로 맞다. **[6-12b 정정]** 비밀번호 변경은 그 사이 계정 상태가 바뀌면 `Conflict`도 던지고 화면은 그것도 400으로 그린다(§8.4.13 "보고만" R6) — **6-13a에서 409로 고침**. 광고주 화면과 나머지 운영 화면(정책·포인트 조정 등)은 이미 `console.errors.status_of`를 쓴다.

**정한 것** [확정 2026-10-13, 사용자 — 구현 세션 권장안]
- **①** `failure_test.py`는 시나리오마다 빈 정적 폴더를 만들어 넘긴다(`load_test.py`와 같게). DB 이름처럼 이 프로세스의 `STATIC_ROOT`·`MEDIA_ROOT`도 그 시나리오의 임시 폴더로 바꾼다.
- **②** `EventOutbox.event_id`의 기본값을 지운다(마이그레이션 `events` 0003). 기본값은 DB에 들어가지 않으므로 상태만 바뀐다. 모델 규약 시험은 outbox를 예외로 알고, 그 PK에 기본값이 없음을 확인한다.
- **③** 두 화면도 `status_of`를 쓴다. 같은 이름이면 409이고 화면 내용은 그대로다. 폼을 다시 그릴 때의 응답 코드도 오류를 바꾸는 한 곳(설계 §6.6 규칙 2)이 정한다.
- **④는 하지 않는다**: 질의 줄이기 셋은 보류 그대로다.
  - 결정 응답의 슬롯 이름(서빙 11 → 10)은 §8.2.5 D-R1(측정상 병목일 때)과 같은 이유다.
  - `create_ad`의 재잠금(−6)과 대시보드(−2)는 서빙 경로 밖이라 급하지 않다.

**계약·설계**: 계약(C1·C6)은 바뀌지 않는다. 운영 화면은 C6에 없다. 설계에는 두 가지를 적는다.
- 6-7c: §4 PK 규칙과 §10 "PK 규칙"에, outbox 예외를 규약 시험이 지킨다는 것.
- 6-7d: §6.6 규칙 2에 응답 코드.

DRD는 outbox `event_id` 행과 검증 표의 PK 규칙 행(6-7c)만 고친다.

**문서를 고치는 방식**: 사용자 지시로 구현 세션이 문서도 고친다(6-5와 같다). 결정·계획을 먼저 담고(6-7a), 단계가 바꾼 문서는 그 단계의 커밋에, 완료 기록은 마지막 단계(6-7d)에 담는다.

**단계** (한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 단언은 변형 검사, 단계마다 사용자 확인 뒤 착수)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-7a 결정·계획** | 이 절, §8.4.7 "보고만"의 연결, §8 요약·§10, 설계 §2·§8 | 문서만 | **완료 `e9096a7`** |
| **6-7b 장애 시험의 임시 폴더** | `scripts/failure_test.py`(①) | 시나리오 둘을 한 번에 돌렸을 때: "No directory" 경고가 없다, 끝난 뒤 그 실행의 `ads-failure-*` 폴더가 남지 않는다, 시나리오가 통과한다 | **완료 `113abe3`** — 시나리오마다 빈 `static` 폴더를 만들어 환경변수로 넘기고, DB 이름을 바꾸는 자리에서 이 프로세스의 `MEDIA_ROOT`·`STATIC_ROOT`도 그 시나리오 폴더로 바꾼다. `failure_test.py processor-kill relay-kill`(자체 임시 컨테이너)을 한 번에 돌려 두 시나리오 모두 통과했다. "No directory" 경고는 0건이고, 끝난 뒤 `ads-failure-*` 폴더도 0개다. 고치기 전 실행들이 남긴 폴더 21개(10-09~10-13, 대부분 소재 이미지 6개씩)는 사용자 확인 뒤 지웠다. `check.sh` 통과(시험 1,305 그대로). 제품 코드·문서는 바뀌지 않는다 |
| **6-7c outbox PK 기본값** | `events/models.py`, 마이그레이션 `events` 0003, 모델 규약 시험(②), 설계 §4·§10 "PK 규칙", DRD outbox `event_id` 행 | `sqlmigrate`에 SQL이 없다, 마이그레이션이 최신이다, 규약 시험이 outbox에 기본값을 다시 붙이는 변형을 잡는다 | **완료 `068c98f`** — 기본값과 `import uuid`를 지우고, 마이그레이션 `events/0003_outbox_event_id_without_default`(`sqlmigrate`는 no-op)를 더했다. 규약 시험은 outbox만 "기본값 없음"을, 나머지는 `uuid.uuid7`을 확인한다(이름 그대로 — 설계 §4·DRD가 인용). 변형 3개 모두 잡음: outbox에 `uuid7` 기본값을 다시 붙임, 예외 분기를 모든 모델에 적용, 예외 분기를 없앰. 임시 시험(확인 뒤 지움)으로 MySQL에서 `event_id` 없는 `create`와 `bulk_create(update_conflicts=True)`(`events/outbox.py`와 같은 형태)가 모두 IntegrityError이고 남는 행이 없음을 확인했다. 같은 커밋의 문서: 설계 §4 PK 규칙·§10 "PK 규칙", DRD 0.40(outbox `event_id` 행·검증 표). 시험 1,305 그대로 |
| **6-7d 운영 화면의 409** | `console/operator/views.py` 두 뷰, 운영 화면 시험(③), 설계 §6.6 규칙 2, 완료 기록(이 절·§8 요약·§10, 설계 §2·§8) | 같은 이름의 매체·게재 위치는 409로 다시 그리고 입력 오류는 400 그대로다, 400 고정으로 되돌리는 변형을 잡는다, 서빙 질의 수 11 · 40 · 28 그대로 | **완료 `a23873c`** — 두 뷰가 정책 화면처럼 서비스 오류는 `status_of`로, 서비스까지 가지 않는 폼 오류는 400으로 다시 그린다. 시험 먼저: 같은 이름의 매체를 409로 기대하게 바꾸고, 같은 매체에 같은 이름의 게재 위치를 409로 보는 `test_a_name_already_in_the_media_is_a_conflict`를 더했다(바꾸기 전 코드에서 둘 다 400으로 실패함을 확인). 변형 4개 모두 잡음: 매체·게재 위치의 서비스 오류를 400 고정으로 되돌림, 폼 오류의 400을 뺌(매체·게재 위치). 폼 오류 둘은 처음에 못 잡았다 — 매체 이름은 `strip=False`라 빈칸만 보낸 시험은 서비스가 거절하고, 서비스까지 가지 않는 폼 오류를 보는 시험이 없었다(바꾸기 전 코드도 같다). 그래서 빈 이름·빈 하한이 400인 단언을 한 줄씩 더했다. 같은 커밋의 문서: 설계 §6.6 규칙 2, 완료 기록(이 절·§8 요약·§10, 설계 §2·§8). 시험 1,305 → 1,306 |

**검증**(구현 세션): 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`·`bandit` 통과. 시험 1,305 → 1,305(6-7b·6-7c) → 1,306(6-7d). 변형은 6-7c 3개·6-7d 4개를 모두 잡았다. 6-7b는 장애 시험 두 시나리오를 한 번에 돌려 확인했다. 서빙 질의 수는 결정 11 · 반응 40 · 클릭 28 그대로다(HEAD `068c98f` + 6-7d 작업 트리). 메모: 이 셸에는 `python`이 PATH에 없어 첫 `check.sh`가 DB 접속 단계에서 "command not found"로 멈췄고, claude 환경을 PATH 앞에 두고 다시 돌렸다. 6-7c의 첫 변형(기본값 `uuid.uuid4`)은 `import uuid`를 지운 뒤라 import 오류로 "잡힘"이 나와 버리고, import가 필요 없는 형태로 다시 돌렸다.

### 8.4.9 6-8 브라우저 검토 후속 — 작은 수정 (기준 코드·문서 `a23873c`, 완료 2026-10-13)

**계기**: 6-7 뒤 사용자가 검토용 dev 서버(광고주·운영자 두 탭)에서 직접 써 보고 문제점 셋과 질문을 냈다(2026-10-13). 그중 작은 둘을 여기서 고친다. 큰 것은 6-9(구조 재편)·6-10(과금 재설계)으로 나눈다(아래 "다음").

**확인한 것**
- **문제점 2**(광고 모니터링에서 소재를 누르면 다른 창이 뜸): 원인은 소재 칸(`console/templates/operator/_creatives.html`)의 이동 주소 링크다. 운영자가 목적지를 직접 확인하라고 둔 링크인데 `target`이 없어, 운영 화면이 있던 탭이 광고주의 목적지로 넘어간다. 썸네일에는 링크가 없다.
- **문제점 3**(빈 사유 거절): 매체 등록 폼이 아니라 매체 상세의 "게재 위치 만들기" 폼에 있는 입찰 정책 사유다. 같은 검사(`clean_text`, 보이는 문자 1~200자)를 만들기·정책 변경·일괄 변경 셋이 함께 쓴다(DRD 입찰 정책 `reason` "사유 필수").

**정한 것** [확정 2026-10-13, 사용자]
- **② 안 C**: 이동 주소는 새 탭으로 연다(`target="_blank"`, `rel="noopener noreferrer nofollow"`는 그대로). 썸네일을 누르면 원본 이미지(운영자 이미지 경로)를 새 탭으로 연다.
- **③ 안 A**: 게재 위치를 **만들 때만** 사유가 비면 "없음"으로 채운다.
  - 채우는 곳은 서비스(`masters.create_slot`)다. 폼은 그 칸을 선택 입력으로만 바꾼다(설계 §6.6 규칙 1·3).
  - 정책 변경·일괄 변경의 사유는 지금처럼 필수다. 가격을 바꾼 이유는 감사 기록으로 남긴다.
  - DB 열에는 "없음"이 들어가므로 NOT NULL 그대로다.

**계약·설계**: 계약은 바뀌지 않는다(운영 화면은 C6에 없다). 설계 결정도 그대로다. DRD는 입찰 정책 `reason` 행만 고친다(6-8c).

**문서를 고치는 방식**: 사용자 지시로 구현 세션이 문서도 고친다(6-5·6-7과 같다). 결정·계획을 먼저 담고(6-8a), 단계가 바꾼 문서는 그 단계의 커밋에, 완료 기록은 마지막 단계(6-8c)에 담는다.

**단계** (한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 단언은 변형 검사, 단계마다 사용자 확인 뒤 착수)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-8a 결정·계획** | 이 절, §8 요약·§10, 설계 §2·§8, §8.4.8의 6-7d 해시 | 문서만 | **완료 `61880b8`** |
| **6-8b 모니터링 링크** | `console/templates/operator/_creatives.html`, 운영 화면 시험(②) | 이동 주소 링크가 새 탭·`noopener`, 썸네일이 원본 이미지를 새 탭으로 연다, 변형 검사 | **완료 `25c52d9`** — 썸네일을 운영자 이미지 경로 링크(`target="_blank"`, `rel="noopener noreferrer"`)로 감싸고, 이동 주소 링크에 `target="_blank"`를 더했다(`rel`은 그대로). 운영자 이미지 응답은 첨부가 아니라 그대로 보이는 응답이라 새 탭에 이미지가 뜬다. 같은 소재 칸을 재검토 대기 화면도 쓴다. 시험 먼저: 모니터링 시험이 두 링크의 정확한 모양을 보게 바꿨다(바꾸기 전 템플릿에서 실패함을 확인). 변형 3개 모두 잡음: 이동 주소의 새 탭 빼기, 썸네일의 새 탭 빼기, 썸네일 링크가 이동 주소를 가리키게 하기. 같은 커밋의 문서: 이 계획 §8.1.1(Step 3 전제와 원칙)의 이동 주소 링크 규칙에 새 탭 표시. 시험 1,306 그대로 |
| **6-8c 사유 기본값 + 완료 기록** | `masters.create_slot`, 게재 위치 만들기 폼의 사유 칸, 시험(③), DRD 입찰 정책 `reason` 행, 완료 기록(이 절·§8 요약·§10, 설계 §2·§8) | 빈 사유로 만들면 "없음"이 저장된다, 정책 변경·일괄 변경은 빈 사유를 계속 거절한다, 변형 검사 | **완료 `0eb674b`** — `create_slot`이 사유가 없거나(`None`) 공백뿐이면 "없음"으로 채운 뒤 같은 검사(`clean_text`)를 거친다. 보이지 않는 문자만 있는 사유·200자 초과는 계속 400이다. 게재 위치 만들기 폼의 사유 칸은 선택 입력이고 "비우면 ‘없음’으로 남습니다" 안내를 단다. 정책 변경·일괄 변경 폼은 그대로 필수다. 시험 먼저: 서비스 시험 `test_a_slot_may_be_created_without_a_reason_but_a_policy_change_may_not`(빈 문자열·공백·`None` → "없음", 같은 값으로 정책 변경·일괄 변경은 400 — 서비스 수준에서 이것을 보는 시험은 없었다)과 화면 시험 `test_the_reason_may_be_left_blank_when_creating`(바꾸기 전 코드에서 둘 다 실패함을 확인). 만들 때 빈 사유를 거절한다고 단언하던 기존 입력 검사 시험의 두 경우는 200자 초과·보이지 않는 문자로 바꿨다. 변형 5개 모두 잡음: 채우기를 지움, "없음" 대신 빈 문자열, 정책 변경·일괄 변경에도 채우기(2), 폼의 선택 입력을 되돌림. 같은 커밋의 문서: DRD 0.41(입찰 정책 `reason`), 완료 기록. 시험 1,306 → 1,308 |

**검증**(구현 세션): 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`·`bandit` 통과. 시험 1,306 → 1,306(6-8b) → 1,308(6-8c). 변형은 6-8b 3개·6-8c 5개를 모두 잡았다. 서빙 질의 수는 결정 11 · 반응 40 · 클릭 28 그대로다(6-8c 작업 트리). 단계마다 검토용 dev 서버(`ads_review67`)를 다시 띄워 사용자가 두 탭(광고주·운영자)에서 볼 수 있게 했다.

**다음** [확정 2026-10-13, 사용자 — 결정의 기록은 각 수정의 a 단계가 설계 §10에 남긴다]
- **6-9 구조 재편(캠페인 · 광고 · 소재)** — 계획·결과는 §8.4.10(완료 2026-10-13):
  - 캠페인은 따로 만든다.
  - 광고 만들기 = 캠페인 고르기 + 광고(이름·게재 위치·입찰) + 소재(새로 올리기 또는 등록된 소재 재사용). 광고와 소재 연결은 한 트랜잭션이고, Step 3 결정 D3-3을 대체한다.
  - 소재는 광고주 소유 목록이다. 광고에는 소재를 여러 개 연결하고 그중 하나를 선택한다.
  - 삭제는 보관이다. 끝나지 않은 캠페인(일시 중지·중단 포함)의 광고에 연결된 소재는 삭제하지 못하고, 보관하면 개수 제한에서 빠진다.
    - [열림] 이미지 파일 누적은 이후 내부 정책(실제 삭제 또는 압축본만 보관)으로 정한다.
  - 소재 수정은 그 소재를 쓰는 모든 광고에 다음 결정부터 적용된다.
  - 연결·선택·삭제는 소재 행을 잠그고, 잠금 순서는 캠페인 → 광고 → 소재다.
  - 소재 끄기를 없앤다.
  - 화면 용어 "광고그룹" → "광고"(코드·C6 이름은 그대로).
- **6-10 과금 재설계** — 계획은 §8.4.11:
  - 게재 위치마다 노출·클릭·전환 %를 둔다(정수 1~98, 합 100). 과금 = 내림(적용 금액 × %).
  - 하한 최소 100이라 0이 나오지 않는다. 그래서 "0이면 1" 코드는 두지 않는다.
  - %는 입찰 정책 버전에 넣고, 결정 때의 값을 결정에 남긴다.
  - 과금 단위를 없앤다. 광고주는 단위를 고르지 않고, %와 예상 과금을 본다.
  - C2 `ad.decision` 이벤트는 %를 싣고 스키마 버전 2로 올린다(확장 때 파이프라인에 공유).
  - 화면 용어 "게재 위치" → "구성"(코드·C1의 slot은 그대로).

### 8.4.10 6-9 구조 재편 — 캠페인 · 광고 · 소재 (기준 코드·문서 `0eb674b`, 완료 2026-10-13)

**계기**: 브라우저 검토(§8.4.9) 때 사용자가 두 가지를 문제로 들었다.
- "광고그룹"이라는 이름이 어색하다.
- 광고를 만들려면 캠페인·광고그룹·소재를 한 번에 모두 써야 한다.

사용자의 해석은 이렇다.
- 캠페인은 이름·기간·성과로 광고들을 묶는 그룹이다.
- 광고그룹이 실제 광고다.
- 소재는 광고에 필요한 리소스다.

소재는 업로드 상한이 있으니 다시 쓸 수 있어야 한다. 나중에 광고 하나에서 소재 여러 개를 바꿔 가며 띄울 수 있게 구조도 미리 맞춘다. 소재 끄기는 V1(광고당 소재 1개)에서 광고 끄기와 효과가 같아서 없앤다.

**지금 구조**(확인한 것)
- 서비스(`create_campaign`·`create_ad_group`·`create_creative`)와 C6 엔드포인트는 이미 따로 있다. 화면만 한 폼(Step 3 결정 D3-3, 원자적 `create_ad`)으로 묶여 있다.
- 소재는 광고그룹에 붙어 있다(`Creative.ad_group`, V1은 1개, `MAX_CREATIVES_PER_AD_GROUP = 1`).
- 과거 결정은 소재 행에 기대지 않는다. `creative_id`와 그 시점의 제목·이동 주소·이미지 이름을 스냅샷으로 저장한다.
  - 예외는 이미지 공개 판정이다(`is_asset_servable`: 그 이미지를 가진 소재 → 광고그룹 → 캠페인이 살아 있는가).
- 광고주 상한: 캠페인 20 · 광고그룹 100 · 소재 100 · 이미지 보유 총량 100MB(`MAX_UPLOAD_BYTES_PER_ADVERTISER`).
  - 이미지 보유 총량은 지금까지 가진 파일을 세고(같은 파일은 한 번), 줄지 않는다(설계 §10 "이미지 보유 관계").
  - 삭제가 없어서 한 번 만든 소재는 계속 개수에 센다.

**정한 것** [확정 2026-10-13, 사용자]

| # | 결정 |
|---|---|
| S1 | **캠페인은 따로 만든다**(이름·기간·일예산). 광고 없는 캠페인도 둘 수 있다. 상한 20은 그대로다 |
| S2 | **광고 만들기** = 캠페인 고르기 + 광고(이름·게재 위치·입찰) + 소재(**① 새로 올리기** 또는 **② 등록된 소재 고르기**). **광고와 소재 연결은 한 트랜잭션**이고, 요청 키로 두 번 보내도 하나만 만든다. D3-3(캠페인까지 한 번에 만드는 한 페이지 폼)을 대체한다 |
| S2' | 광고 만들기로 들어가는 곳은 둘이다. ⓐ 위쪽 메뉴: 캠페인을 고르는 칸이 있고, 캠페인이 없으면 "캠페인을 먼저 만드세요"와 링크. ⓑ 캠페인 상세의 "이 캠페인에 광고 만들기": 그 캠페인이 미리 골라져 있다 |
| S3 (N1·N2) | **소재 = 광고주 소유 목록**이다. 같은 광고주의 어느 광고에서나 다시 쓴다. **광고에는 소재를 여러 개 연결하고 그중 하나를 선택**한다. 광고에는 언제나 선택된 소재가 하나 있다(만들 때 하나로 시작). 소재는 광고 상세에서 올려 바로 연결할 수도, 소재 목록에서 올릴 수도 있다 |
| S4 (N3) | 화면의 **"삭제" = 보관**이다. 목록에서 숨기고, 새로 연결·선택하지 못하게 하고, 행은 남긴다("삭제 없음" 원칙의 소재 쪽 해석. 감사 기록·과거 결정이 참조한다) |
| S5 (N4) | **끝나지 않은 캠페인(일시 중지·중단 포함)의 광고에 연결된 소재는 삭제할 수 없다.** 선택 여부와 무관하다. 그 광고로 이미 나간 결정이 화면에 남아 있을 수 있기 때문이다 |
| S6 (N5) | **보관한 소재는 개수 상한(100)에서 빠진다.** 이미지 보유 총량(100MB)은 그대로다 — 보관해도 줄지 않아 저장 공간은 광고주당 100MB에서 멈춘다(기존 규칙 그대로). [열림] 쌓인 파일을 줄이는 내부 정책(실제 삭제 또는 압축본만 보관)은 이후 정한다 |
| S7 (N6) | 소재 수정(제목·이동 주소·이미지)은 **그 소재를 쓰는 모든 광고에 다음 결정부터** 적용된다. 과거 결정은 스냅샷이라 그대로다. "종료된 캠페인의 소재는 수정 불가" 규칙은 없어진다. 보관한 소재는 수정할 수 없다 |
| S8 (N7) | **잠금**: 전체 순서는 **광고주(상한 잠금 행 — 6-16g 부터 사용자 행) → 캠페인 → 광고그룹 → 소재**다.<br>· 연결·선택: 캠페인 → 광고그룹 → 소재<br>· 소재 수정: 소재만<br>· 이미지 교체: 광고주 → 소재<br>· 보관: **소재만 잠그고**, 연결된 광고의 캠페인 상태는 잠그지 않고 읽는다. 끝난 캠페인은 되돌릴 수 없어 늦게 읽어도 안전하다<br>· 연결과 보관이 겹치면 소재 행 잠금으로 줄을 서서, 보관된 소재에는 연결하지 못하고 연결된 소재는 보관하지 못한다 |
| S9 | **소재 끄기를 없앤다.** 광고를 멈추는 것은 광고 ON/OFF 하나다. 나중에 소재가 여러 개가 되어도 끄기 대신 "선택"으로 고른다 |
| S10 | **이미지 공개 판정**: 그 이미지를 가진 소재가 **연결된 적 있는** 광고 중 하나라도, 캠페인이 `ACTIVE`·`PAUSED`이고 끝나지 않았으며 광고주가 활성이면 공개한다. 선택을 바꿔도 이전 결정의 이미지가 깨지지 않는다 |
| S11 | **남의 소재는 연결할 수 없다**(소유 검사, 남의 것·보관된 것은 404) |
| S12 | 화면 용어 **"광고그룹" → "광고"**. 코드(`AdGroup`)·C6 이름은 그대로 두고, 설계 §10에 용어 행을 둔다(6-9e) |
| [계획 기본값] | 광고에서 소재 **연결을 끊는 기능은 두지 않는다**. 다른 소재를 "선택"하면 된다(연결 기록이 S5·S10의 근거).<br>**광고당 연결 수 상한은 없다**(`MAX_CREATIVES_PER_AD_GROUP` 삭제, 광고주당 소재 상한이 묶는다).<br>**보관을 되돌리는 기능은 두지 않는다** |

**계약·문서**
- C1(매체)·C2(이벤트)는 바뀌지 않는다. 결정의 `creative_id`·스냅샷이 그대로다.
- C6(콘솔 API 초안)은 6-9c에서 서비스와 같은 커밋으로 고친다.
  - 소재가 광고 아래(`/ad-groups/{id}/creatives`)에서 광고주 아래(`/creatives`)로 옮겨 간다.
  - 광고-소재 연결·선택이 생기고, 소재 "삭제"(보관)가 생기고, 광고 만들기 본문이 바뀐다.
- DRD:
  - 6-9b: 소재 `enabled` 삭제.
  - 6-9c: 소재 표(소유자·보관), 새 연결 표, 상한.
- 위협 모델(6-9c·6-9f): T43(남의 소재 연결, 보관과 연결의 경쟁), 이미지 공개 판정, 저장 공간(S6).
- 설계 §10의 이 결정들은 이 커밋에 "[구현 예정]"으로 남기고, 구현 뒤 해시를 단다(§8.4.1 2).

**문서를 고치는 방식**: 사용자 지시로 구현 세션이 문서도 고친다(6-5·6-7·6-8과 같다). 결정·계획을 먼저 담고(6-9a), 단계가 바꾼 계약·DRD·위협 모델은 그 단계의 커밋에, 완료 기록은 마지막 단계(6-9f)에 담는다.

**단계** (한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 시험은 변형 검사, 단계마다 사용자 확인 뒤 착수, 끝나면 검토용 dev 서버를 다시 띄운다)

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-9a 결정·계획** | 이 절, §8.1.4 D3-3 표시, §8.4.9 "다음"의 연결, §8 요약·§10, 설계 §2·§4(C6 요약의 소재·삭제)·§4.6·§8·§10(새 결정 행 + 바뀌는 행 표시) | 문서만 | **완료 `4669baf`** |
| **6-9b 소재 끄기 제거** | `Creative.enabled`와 마이그레이션, 소재 수정 서비스의 `enabled`, 후보 조회 조건, 광고주 화면의 끄기 버튼·경로, 운영 화면의 "(꺼짐)", C6 소재 `enabled`, DRD 소재 표, 시험 | 끄기 경로·필드가 없다, 후보 조회와 광고 ON/OFF는 그대로, 마이그레이션 최신 | **완료 `576f3cd`** — `Creative.enabled` 삭제(마이그레이션 `campaigns/0006_creative_without_enabled`, `DROP COLUMN`), `CreativeView.enabled`, 소재 수정의 바꿀 수 있는 필드(제목·이동 주소만 — `enabled`를 보내면 모르는 필드로 400), 후보 조회의 소재 조건(광고그룹 켜짐·캠페인 집행 중·광고주 활성은 그대로), 광고주 화면의 소재 켜짐 표시·끄기 버튼과 경로 `creative_enabled`, 운영 화면의 "(꺼짐)", 관리자 목록 칸. 시험 먼저: 소재 수정 시험이 `{"enabled": False}`를 모르는 필드로 거절하게 바꿨다(바꾸기 전 코드에서 실패함을 확인). 소재 끄기를 쓰던 시험 다섯 곳을 정리했다 — 화면 메시지 시험·소재 화면 시험은 이름에서 "소재 끄기"를 뺐다(`test_ad_group_switch`·`test_image_replacement_keeps_the_old_file`), 후보 제외 시험에서 소재 꺼짐 두 줄, `enabled` 값 계약 시험은 광고그룹만, 격리 시험(위협 모델 인용, 이름 그대로)은 끄기 경로 대신 제목이 그대로인지 본다. 변형: 바꿀 수 있는 필드에 `enabled`를 되돌리면 잡음. 같은 커밋의 문서: C6(규약의 삭제 없음, 소재 스키마·수정 본문의 `enabled`, 수정 요약), DRD 0.42(R-6·구조도·소재 표·팀 DRD 대응표). 시험 1,308 그대로 |
| **6-9c 소재 목록·연결(서비스)** | 소재에 소유자·보관, 광고-소재 연결 표(선택 하나), 마이그레이션(기존 소재 → 소유자 = 캠페인 주인, 그 광고에 연결·선택 — 개발 DB용). 서비스: 소재 만들기·수정·보관·목록(쓰는 광고 포함), 연결, 선택, 광고 만들기(기존 캠페인에 광고 + 새/기존 소재). 후보 조회는 선택된 소재, 이미지 공개 판정(S10), 잠금(S8), 상한(S6). C6·DRD·위협 모델. **지금의 한 폼 광고 만들기는 6-9d까지 그대로 동작하게 둔다** | 남의 소재 연결 404, 끝나지 않은 캠페인(일시 중지·중단 포함)에 연결된 소재 보관 거절, 끝난 뒤에는 보관 가능, 보관하면 개수에서 빠지고 용량은 그대로, 선택을 바꿔도 이전 결정 이미지 200, 연결·보관 경쟁 시험(잠금을 빼는 변형 검출), 과거 결정 스냅샷 불변 | **완료 `724a276`** — 모델: 소재에 `owner`·`archived_at`(광고그룹 FK 삭제), 새 `AdGroupCreative`(추가 전용, UNIQUE(광고그룹, 소재)), 광고그룹에 선택 `creative`·`request_key`(UNIQUE). 마이그레이션 `campaigns/0007_creative_library`(소유자 = 캠페인 주인, 붙어 있던 광고그룹에 연결·선택으로 옮김). 서비스: `create_creative(user, ad_group_id 또는 None, …)`(주면 연결하고 선택된 것이 없으면 선택 — 기존 호출 그대로), `link_creative`, 선택은 `update_ad_group`의 `creative_id`(연결된 것만), `archive_creative`, `list_owned_creatives`(연결된 광고그룹·끝났는지·선택 여부), `create_ad_for_campaign`(새 소재 또는 `creative_id`, 요청 키는 광고그룹 행), 소재 수정·이미지 교체는 캠페인을 잠그지 않고 종료로 막지 않음. 후보 조회는 광고그룹에서 시작해 선택된 소재를 같은 질의로(질의 한 번 그대로), 이미지 공개 판정은 연결 기준(한 `filter()` — 연결끼리 조건이 섞이지 않게), 운영 모니터링은 연결된 소재 전부와 연결 시각, 상한은 보관하지 않은 소재·보관 포함 이미지. `MAX_CREATIVES_PER_AD_GROUP` 삭제. 지금의 한 폼 광고 만들기(`create_ad`)는 연결·선택으로 그대로 동작하고, 소재 수정·이미지 교체 폼은 돌아갈 광고그룹을 숨김 칸(`ad_group_id`, 남의 것 404)으로 받는다. 시험: 새 `tests/test_creative_library.py`(13개 — 재사용·선택·남의/보관한 소재 404·보관 조건(진행·일시 중지·중단·기간 지남)·개수와 용량·수정이 모든 광고그룹에·선택을 바꿔도 이전 이미지 공개·섞인 연결·기존 캠페인에 광고 만들기·실패 시 남지 않음·연결↔보관 경쟁 2), 추가 전용 전수 시험에 연결 표, 바뀐 규칙에 맞춘 기존 시험(광고그룹당 1개 → 여러 개 연결, 종료 가드는 소재 수정 대신 연결·선택, 보유량 집계 관계). 변형 14개 모두 잡음(보관 확인·사용 중 검사·선택 여부와 무관·일시 중지/중단·기간 지남·연결된 것만 선택·소유 검사·개수에서 보관 빼기·용량에 보관 포함·소재 행 잠금·종료 가드·처음 연결만 선택·새/재사용 중 하나·이미지 판정의 한 filter). 서빙 질의 수 11 · 40 · 28 그대로. 같은 커밋의 문서: C6(규약·핵심 규칙·광고그룹 `creative_id`·소재 스키마·새 경로 4개·`CreativeUse`·`OwnedCreative`), DRD 0.43(O2·O4·새 O9·O7·O8·R-6·구조도), 위협 모델(T43 ⑮·업로드 총량 행 — 바뀐 시험 이름), 설계 §4.5 종료 규칙·§4 C6 요약, 이 계획 Step 1 시험 표. 시험 1,308 → 1,321 |
| **6-9d 화면** | 캠페인 목록의 "캠페인 만들기", 광고 만들기(캠페인 고르기·없으면 안내, 소재 새로/재사용), 캠페인 상세의 "이 캠페인에 광고 만들기", 광고 상세(연결 소재·선택·올려서 연결·등록된 소재 연결), 새 메뉴 **소재 목록**(올리기·수정·삭제·쓰는 광고), 운영 모니터링·재검토 대기(광고별 선택 소재). 옛 한 폼 경로 제거 | JS 없는 흐름 시험(캠페인 → 광고 → 소재 재사용 → 선택 → 삭제 거절·허용), 접근 전수 시험에 새 경로, 화면 점검 | **완료 `4503452`** — 서비스: 6-9c 의 `create_ad_for_campaign` 을 `create_ad` 로(캠페인까지 한 번에 만들던 옛 `create_ad` 와 그 요청 키 경로는 지움 — 요청 키는 광고그룹 행), `create_campaign(request_key=)`·`campaign_created_by_key`(캠페인 만들기 폼의 중복 제출 — `Campaign.request_key` 의 뜻이 바뀜, 광고주 잠금 안에서 다시 봄), 운영 모니터링·재검토 대기에 광고그룹이 선택한 소재 ID. 화면: 캠페인 목록의 "캠페인 만들기"(새 화면)·"광고 만들기", 캠페인 상세의 "이 캠페인에 광고 만들기"(`?campaign=` 로 미리 고름, 끝난 캠페인은 없음), 광고 만들기(① 캠페인 — 끝나지 않은 내 캠페인만, 없으면 "캠페인을 먼저 만드세요" ② 과금 단위 ③ 광고 ④ 소재 — 새로 올리기 또는 등록된 소재 ⑤ 집행 → 광고 상세로), 광고 상세의 소재(나가는 중 표시·"이 소재로 바꾸기"·등록된 소재 연결·올려서 연결), 새 메뉴 **소재**(목록: 쓰는 광고·끝났는지·나가는 중, 삭제는 쓰는 광고가 모두 끝났을 때만, 올리기 / 상세: 수정·이미지 교체·삭제, 삭제한 소재는 읽기만), 운영 화면 소재 칸의 "(나가는 중)". 소재 수정·이미지 교체 뷰는 `views/creatives.py` 로 옮겨, 숨김 칸 `ad_group_id` 가 있으면 그 광고 상세(남의 것은 고치기 전에 404), 없으면 소재 상세로 돌아온다. 새로 만든 화면은 "광고" 용어를 바로 쓰고, 기존 화면의 "광고그룹"은 6-9e 에서 바꾼다. 시험: 광고·캠페인 만들기 화면 시험을 새 흐름으로 다시 씀(위협 모델이 인용한 이름 그대로 — 시작 시각 경계 시험은 캠페인 만들기 화면으로, 상한 시험은 광고그룹 상한으로), 새 시험(캠페인 없을 때 안내·링크의 캠페인 미리 고름·남의 캠페인·소재 위조 400·등록된 소재 재사용·캠페인 만들기 5개·같은 캠페인 폼의 겹친 재전송), 새 `tests/test_creative_pages.py` 5개, 운영 모니터링의 나가는 중 표시, 소재 폼의 돌아갈 곳 위조와 남의 광고 연결·선택 404, JS 없는 흐름(캠페인 만들기 → 광고 만들기 → 소재 목록에 올려 연결·선택), 화면 점검 목록에 새 화면 셋, 서비스 시험 `CreateAdTests`·요청 키 입력 계약(캠페인 만들기 입구 추가)·경쟁 시험(다른 키는 캠페인 만들기로, 같은 키는 광고 만들기로). 변형 11개 모두 잡음(처음에 하나 — 돌아갈 광고의 소유 확인 — 를 못 잡아 맞는 수정 + 남의 광고로 시험을 강화). 같은 커밋의 문서: 위협 모델 T43(⑦·⑫·시험 인용), DRD 0.44(요청 키의 뜻·불변식·멱등 키 표·구조도). 시험 1,321 → 1,336 |
| **6-9e 화면 용어** | "광고그룹" → "광고"(광고주·운영 화면, 메시지), 설계 §10 용어 행 | 화면 문구만 바뀐다, 남은 "광고그룹"이 없음을 화면 점검으로 확인 | **완료 `35767b7`** — 바꾼 것: 캠페인 상세의 "광고그룹" 칸(제목·표 머리·빈 목록), 광고 상세의 이름표, 이름 폼의 칸 이름("광고 이름"), 켜기·끄기 메시지("광고를 켰습니다/껐습니다"), 화면에 보이는 서비스 오류 문구(이름 검사 "광고 이름은(는)…"·"광고 개수 상한"·"이 광고에 연결된 소재가 아닙니다"·"끝나지 않은 캠페인의 광고에 연결된 소재는…"·단위 불일치 제목). 6-9d 에서 새로 만든 화면은 이미 "광고"였다. 코드 이름(`AdGroup`·`ad_group_id`·경로 `/advertiser/ad-groups/…`)·C6·문서·주석·내부 오류(모델의 `ValueError`)는 그대로다. 시험: 문구를 단언하던 시험 4개(메시지·이름표·상한·삭제 거절)를 새 문구로, 새 시험 `test_screens_say_ad_not_ad_group`(6-12c에서 `test_screens_use_the_screen_terms`로 합침)(화면 점검의 광고주·운영 화면 전부에 "광고그룹"이 없다 — 관리자 사이트 모델 화면은 범위 밖, 되돌리는 변형을 잡음). 같은 커밋의 문서: 설계 §10 "화면 용어: 광고"(화면에 보이는 서비스 오류 문구도 포함). 시험 1,336 → 1,337 |
| **6-9f 측정·완료** | 서빙 질의 수(후보 조회가 연결 표를 거쳐 바뀔 수 있다 — 바뀌면 이유와 기준선을 기록), 150 동시 부하, 장애 시험 두 시나리오, 완료 기록(이 절·§8 요약·§10, 설계 §2·§8·§10 해시) | 모든 불변식 충족 | **완료(이 커밋)** — HEAD `35767b7` 에서 서빙 질의 수 결정 11 · 반응 40 · 클릭 28 그대로(후보 조회는 광고그룹에서 시작해 선택된 소재를 같은 질의로 붙여 연결 표를 거치지 않는다), 150 동시 부하 모든 불변식 충족, `failure_test.py` processor-kill·relay-kill 통과. 완료 기록: 이 절·§8 요약·§10, 설계 §2·§4.6·§8·§10("구현 예정"·"6-9 예정" 표시를 해시로) |

**검증**(구현 세션): 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`·`bandit` 통과. 시험 1,308 → 1,308(6-9b) → 1,321(6-9c) → 1,336(6-9d) → 1,337(6-9e). 변형은 6-9b 1개·6-9c 14개·6-9d 11개·6-9e 1개를 모두 잡았다. 6-9f: 150 동시 부하의 단계별 요청은 모두 최종 성공했고, 일괄 슬롯 시청자(J)의 첫 시도 503 3건은 MySQL `1040 Too many connections`로 재시도에서 302를 받았다(§9 "MySQL 연결 한도"의 알려진 현상). 장애 시험 두 시나리오는 구간 대조 `match` 12로 통과했다. 단계마다 검토용 dev 서버(`ads_review67`)를 다시 띄워 사용자가 두 탭(광고주·운영자)에서 볼 수 있게 했다.

**다음**: 6-10 과금 재설계(§8.4.11).

### 8.4.11 6-10 과금 재설계 — 구성별 반응 비율 (기준 코드·문서 `49e0ef3`, 완료 2026-10-13)

**계기**: 브라우저 검토(§8.4.9) 때 사용자가 두 가지를 들었다.
- 과금을 반응 유형(노출·클릭·전환)별 비율로 나누고 싶다. 지금은 게재 위치마다 과금 단위가 하나라 한 유형에만 낼 수 있다.
- 운영 화면의 "게재 위치 이름" 표기가 어색하다.

**지금 구조**(확인한 것)
- 게재 위치(`Slot`)는 과금 단위(`pricing_unit`: 노출·클릭·전환) 하나를 갖고, 이 단위는 바꿀 수 없다.
- 광고그룹도 단위를 하나 갖는다. 고른 게재 위치는 모두 그 단위여야 하고(`unit_mismatch`), 단위는 바꿀 수 없다(`unit_immutable`).
- 후보 조립은 게재 위치와 단위가 다른 광고그룹을 한 번 더 거른다(`records/assemble.py`).
- 결정은 적용 금액(`applied_amount`, 입찰을 하한·상한에 맞춘 값)과 광고그룹의 단위를 스냅샷으로 남긴다.
- 과금 정책 `by-unit/v1`은 반응 유형이 그 단위와 같을 때만 적용 금액 전부를 과금한다(`billing/policies/by_unit.py`).
  - 같은 판정 단위의 같은 유형은 한 번만 인정된다. 그래서 결정 하나(일괄 슬롯은 결정·사람 하나)의 과금은 최대 적용 금액 하나다.
- 입찰 정책(`BidPolicy`)은 게재 위치별 추가 전용 버전(하한·기준가·상한)이다. 결정은 판정에 쓴 버전 행을 가리킨다. 하한의 최소는 지금 1이다.
- C2 `ad.decision`은 `selected.pricing_unit`을 싣는다.
  - 봉투의 `schema_version`은 네 종류 이벤트가 함께 쓰는 상수 하나다(`events/schemas.py`, 지금 1).
  - 구간 대조는 원천 행으로 기대 문서를 다시 만들어 outbox·MongoDB와 비교한다(`records/hops.py`). 백필도 원천 행으로 이벤트를 만든다.
- 광고그룹 성과의 소진액은 "그 광고그룹 단위의 인정된 반응"에 대한 원장 과금으로 센다(`records/report.py`).
- 과금 단위를 참조하는 곳: 시험 밖 39개 파일, 시험 19개 파일.
  - 시험의 기본 게재 위치는 하한 10·기준가 20·상한 50, 입찰 30이다(`tests/factories.py`). 부하 시험 시드도 같다.
- 지금 DB:
  - `ads_impl`에 광고가 있는 결정 3건, 검토 DB(`ads_review67`)에는 결정이 없다.
  - 두 DB의 정책 하한은 10이다.
  - 운영 DB는 아직 없다(배포 때 새로 만든다).
  - MongoDB에는 이벤트가 없다(`ads_events`에 빈 확인용 컬렉션뿐).
  - 모두 지우고 새로 만든다(아래 K1).

**정한 것** [확정 2026-10-13, 사용자]

| # | 결정 |
|---|---|
| B1 (P1·P2·P3) | **구성(게재 위치)마다 노출·클릭·전환 비율(%)** 을 둔다. 각각 **정수 1~98이고 합은 100**이다. 0%는 없다. 결정 하나(일괄 구성은 결정·사람 하나)에서 나갈 수 있는 과금은 최대 적용 금액이다 |
| B2 (P4) | 반응 하나의 과금액 = **내림(적용 금액 × 그 유형의 % ÷ 100)**.<br>하한 최소 100(B3)과 % ≥ 1이 있어 0이 나오지 않는다(100 × 1 ÷ 100 = 1). **"0이면 1" 코드는 두지 않는다.** 정책이 0을 돌려주면 지금처럼 "과금 없음"이다 |
| B3 | **하한 최소 100**. 구성 만들기·정책 변경·일괄 변경이 같은 검사를 쓴다 |
| B4 (P5) | 비율은 **입찰 정책 버전**에 하한·기준가·상한과 함께 넣는다. 비율을 바꾸면 새 버전이다.<br>**결정 때의 비율을 결정에 남기고**, 과금은 그 값으로 한다. 정책을 바꿔도 이미 나간 결정의 과금은 그대로다 |
| B5 (P6) | 다음은 바뀌지 않는다.<br>· 하한·상한으로 적용 금액을 정한다(하한 미만은 후보 제외, 상한 초과는 상한).<br>· 노출 자격은 지갑 잔액과 오늘 남은 예산이 적용 금액 이상인 것이다.<br>· 선택은 최고가다(6-14에서 상한 근접 가중 추첨으로 바뀜, §8.4.15) |
| B6 | **과금 단위를 없앤다.** 없어지는 것: 구성·광고그룹의 단위, "같은 단위끼리만 후보", `unit_mismatch`·`unit_immutable`.<br>광고는 아무 구성이나 함께 고를 수 있다. 과금 정책(설계 §4.7의 교체 지점 `ChargePolicy`)은 `by-unit/v1`에서 비율 정책으로 바꾼다 |
| B7 (P7) | 광고주는 단위를 고르지 않는다. 구성 목록과 미리보기에 **"노출 X% · 클릭 Y% · 전환 Z%"와 유형별 예상 과금**을 보여 준다. 예상 과금은 실제 과금과 같은 함수로 계산한다 |
| B8 (P8) | **C2**: `ad.decision`의 `selected.pricing_unit`을 비율로 바꾸고, 이 이벤트의 **스키마 버전을 2로** 올린다. 파이프라인은 아직 붙지 않았고, 확장 때 공유한다 |
| B9 | **C1**은 설명 문구만 바뀐다("금액은 결정의 과금 단위" → "결정에 남긴 구성 비율"). 필드는 그대로이고 버전은 **1.4.0**이다.<br>**C6**은 단위 필드·오류를 빼고 비율과 예상 과금을 더한다 |
| B10 | 화면 용어 **"게재 위치" → "구성"**("게재 위치 이름" → "구성 이름" 포함). 코드·C1·C6의 `slot`은 그대로 두고, 설계 §10에 용어 행을 둔다 |
| ~~[계획 기본값] 기존 구성의 비율~~ (K1로 해당 없음) | 옛 단위가 노출이면 98/1/1, 클릭이면 1/98/1, 전환이면 1/1/98(노출/클릭/전환 순).<br>하한이 100 미만인 기존 정책은 그대로 두고, 새로 저장하는 버전부터 검사한다(운영 DB는 배포 때 새로 만든다) |

**계획을 쓰며 나온 것** [확정 2026-10-13, 사용자 — 6-10a에서 계획 기본값으로 낸 K1~K6에 답함]

| # | 결정 | 영향 |
|---|---|---|
| K1 옛 데이터 | **이전하지 않는다.** 로컬 개발 환경이라 DB를 유지할 필요가 없고, 운영 중이 아니라 옛 데이터를 검토할 일도 없다.<br>6-10b를 시작할 때 **모든 DB를 지운다**: MySQL `ads_impl`·`ads_review67`·`ads_server`, MongoDB `ads_events`(빈 확인용 컬렉션뿐), 남은 시험 DB(`ads_events_test_…`, 비어 있음). 그 뒤 바뀐 마이그레이션으로 새로 만든다 | 옛 정책 버전·옛 결정·옛 원장 줄·옛 이벤트를 위한 코드를 두지 않는다. 호환 읽기, 스키마 1 다시 만들기, 이전용 정책 버전 모두 없다.<br>새 마이그레이션은 데이터 이전 없이 빈 DB를 전제로 한다. 데이터가 있는 DB는 지우고 다시 만든다.<br>위 "기존 구성의 비율" 기본값은 해당 없다 |
| K2 스키마 버전은 이벤트 종류별 | 봉투의 `schema_version`을 종류별로 둔다. `ad.decision`은 2, 접수·판정·과금은 1 그대로다. 지금의 상수 하나를 종류별 값으로 바꾼다 | 모양이 그대로인 세 종류는 버전도 그대로다 |
| K3 비율의 모양 | 열 이름은 `impression_share`·`click_share`·`conversion_share`(입찰 정책·결정)다.<br>C2는 `selected.charge_shares = {"IMPRESSION": 98, "CLICK": 1, "CONVERSION": 1}`이다. 키가 반응 `type` 값과 같아 소비자가 바로 찾는다 | 결정의 `pricing_unit` 열과 C2의 `selected.pricing_unit`은 없어진다 |
| K4 DB 제약 | 옛 버전이 없으므로(K1) 모두 DB 제약으로도 지킨다.<br>**입찰 정책**: 비율 셋은 NOT NULL이고, 각각 1~98, 합 100이다. **하한 ≥ 100**.<br>**결정**: 광고 없음이면 비율 셋이 비어 있고, 광고가 있으면 셋 모두 1~98, 합 100이다.<br>서비스 세 곳(만들기·정책 변경·일괄 변경)도 같은 검사로 읽기 쉬운 400을 낸다 | 하한 ≥ 100 제약은 시험 금액과 함께 6-10c에서 넣는다 |
| K5 과금 정책 | 새 정책 이름은 `share/v1`이고 원장 `charge_policy`에 남는다. **`by-unit/v1`은 코드에서 지운다.** 옛 원장 줄은 DB와 함께 지워진다(K1) | |
| K6 광고그룹 성과의 소진액 | 단위 대신 모든 유형의 인정된 반응에 대한 원장 과금을 센다 | |

**계약·문서**
- **C1** 1.4.0: 설명 문구 두 곳(반응 판정 요약, 반응 `type` 설명). 6-10c.
- **C2**: `ad.decision` 스키마 2(K2·K3). 6-10c.
- **C6**: 6-10d.
  - 게재 위치·광고그룹의 `pricing_unit`, 게재 위치 목록의 `pricing_unit` 거르기, 오류 `unit_mismatch`·`unit_immutable`을 뺀다.
  - 게재 위치(정책)의 비율과 미리보기의 유형별 예상 과금을 더한다.
- **DRD**:
  - 6-10b: M3 입찰 정책의 비율.
  - 6-10c: R1 결정의 비율(단위 열 삭제), B2 원장 `charge_policy`, §5.3 과금 규칙, §5.6 `ad.decision.v2`, §9 팀 DRD 대응(`charge_unit_code` → 비율, [열림]).
  - 6-10d: M2·O2의 `pricing_unit` 삭제, §4.4 무결성 표.
- **위협 모델**:
  - T28(입찰 정책의 DB 제약에 비율) — 6-10b.
  - T31·T37(과금액 규칙, 인용 시험 `test_charge_policy_by_unit`·`test_a_valid_report_in_the_billing_unit_is_accepted_and_charged_the_recorded_amount`) — 6-10c.
  - T28 인용 시험 `test_slot_pricing_unit_immutable` — 6-10d.
  - 인용 시험의 이름·내용을 바꾸면 같은 커밋에서 인용도 고친다.
- 설계 §10의 이 결정들은 이 커밋에 "구현 예정"으로 남기고, 구현 뒤 해시를 단다(§8.4.1 2).

**문서를 고치는 방식**: 사용자 지시로 구현 세션이 문서도 고친다(6-5·6-7·6-8·6-9와 같다). 결정·계획을 먼저 담고(6-10a), 단계가 바꾼 계약·DRD·위협 모델은 그 단계의 커밋에, 완료 기록은 마지막 단계(6-10f)에 담는다.

**단계** (한 단계 = 한 커밋, 단계마다 `check.sh`(`DB_NAME=ads_impl`), 새 시험은 변형 검사, 단계마다 사용자 확인 뒤 착수, 끝나면 검토용 dev 서버를 다시 띄운다)

처음 계획(6-8a 전에 채팅으로 낸 전체 계획)과 다른 점: 과금 전환(6-10c)과 단위 제거(6-10d)를 나눴고, 하한 최소 100을 6-10b에서 6-10c로 옮겼다. 시험 금액(하한 10·입찰 30 기준)을 과금 전환 때 한 번만 고치기 위해서다. 6-10c 동안 단위는 남아 있지만, 후보 짝짓기와 화면에만 쓰이고 과금에는 쓰이지 않는다.

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-10a 결정·계획** | 이 절, §8.4.9 "다음"의 연결, §8 요약·§10, 설계 §2·§4(구조도)·§4.1·§4.2·§4.3·§4.4·§4.6·§4.7·§8·§10(새 결정 행 + 바뀌는 행 표시) | 문서만 | **완료 `3d6e017`·`ccb65d6`**(뒤의 것은 K1~K6 사용자 결정 반영) |
| **6-10b 구성 정책에 비율** | `masters`:<br>· 입찰 정책에 비율 열 셋과 DB 제약(K4)<br>· 서비스 세 곳(만들기·정책 변경·일괄 변경)의 비율 검사(1~98·합 100)<br>· 마이그레이션(데이터 이전 없음, K1)<br>· 착수 때 모든 DB를 지우고(K1), 끝나면 새로 만든다. 검토용 DB·계정도 다시 만든다<br>· `PolicyView`의 비율, 감사 기록<br>운영 화면: 구성 만들기·정책 변경·일괄 변경 폼, 정책 이력·매체 상세의 비율 표시.<br>시험 공장·부하·장애 시험 시드는 비율을 넣는다(금액은 그대로).<br>DRD M3, 위협 모델 T28. **과금은 아직 단위로 한다**(비율은 저장·표시만) | 경계값 시험: 0·99·합 99·합 101 거절, 1/1/98 통과, 세 곳 모두. DB 제약이 서비스를 우회한 저장도 막는다(비율 NOT NULL 포함). 변형 검사 | **완료 `1be3658`** — 착수 때 모든 DB를 지웠다(K1: MySQL `ads_impl`·`ads_review67`·`ads_server`는 빈 DB로 새로 만들고, MongoDB `ads_events`와 빈 시험 DB는 삭제). 모델: 입찰 정책에 `impression_share`·`click_share`·`conversion_share`(NOT NULL)와 DB 제약 둘(`masters_policy_share_range` 각각 1~98, `masters_policy_shares_sum_100`). 마이그레이션 `masters/0005_bid_policy_shares`는 빈 DB 전제다 — 옛 정책 행이 있으면 비율 제약에서 멈추는 것을 임시 DB로 확인했다. 서비스: `create_slot`·`add_policy_version`·`add_policy_version_bulk`가 세 비율을 필수 키워드 인자로 받아 같은 검사를 한다(칸마다 "1 이상 98 이하의 정수(%)", 합은 `/shares` "합은 100이어야 합니다(지금 N)"). 감사 기록에 비율과 이전 비율, `PolicyView`에 비율. 운영 화면: 구성 만들기·정책 변경(현재 비율로 시작)·일괄 변경 폼에 비율 세 칸, 매체 상세·정책 화면(현재·이력)·일괄 변경 목록에 "노출 X% · 클릭 Y% · 전환 Z%"(서식 필터 `shares`). "새로 불러오기" 링크는 버전 충돌(409)일 때만 보인다(비율 합 오류에 나오지 않게). 시험: 새 시험 `test_charge_shares_are_checked_the_same_way_in_all_three_places`(세 곳 × 거절 8가지·통과 4가지, 거절하면 아무것도 남지 않음), DB 제약 시험에 비율 위반 넷과 양 끝 통과, 운영 화면 시험(폼 시작값·저장·칸 옆 오류·합 오류에 새로 불러오기 없음·목록 표시), 감사 기록의 비율. 기존 호출 56곳에 시험 기본 비율(`tests.factories.SHARES` = 98/1/1, 부하 시험 `LOAD_SHARES`). 변형 17개 모두 잡음(처음에 표시 세 곳 — 일괄 변경 목록·정책 화면 머리·만들기 감사 기록 — 을 못 잡아 단언을 더했다). 같은 커밋의 문서: DRD 0.45(M3·ERD·무결성 표), 위협 모델 T28. 시험 1,337 → 1,338. 과금은 아직 단위로 한다 |
| **6-10c 과금 전환** | · 결정에 비율 열과 DB 제약(K4), 결정의 `pricing_unit` 열 삭제, 후보(`Candidate`의 정책 스냅샷)·결정이 비율을 싣는다<br>· `share/v1` 과금 정책, `by-unit/v1` 삭제(K5)<br>· 하한 최소 100(세 곳 + DB 제약, K4)<br>· 광고그룹 성과의 소진액(K6)<br>· C2: 종류별 스키마 버전, `ad.decision` 2(K2·K3)<br>· C1 1.4.0 문구<br>· 시험 금액을 하한 100 기준으로(공장: 하한 100·기준가 200·상한 500·입찰 300), 부하·장애 시험의 시드와 과금 불변식(비율로 계산한 기대 과금)<br>· DRD, 위협 모델 T31·T37 | · 노출·클릭·전환이 각각 내림 금액으로 과금되고, 결정 하나의 합은 적용 금액 이하다<br>· 정책을 바꿔도 이전 결정은 남긴 비율로 과금된다<br>· 구간 대조·백필이 새 모양(스키마 2)과 일치한다<br>· 한 번만 과금(멱등)이 그대로다<br>· 하한 99 거절·100 통과(세 곳과 DB 제약)<br>· 서빙 질의 수(바뀌면 이유와 기준선)<br>· 20 동시 부하 불변식<br>· 변형 검사 | **완료 `335e81b`** — 결정: `impression_share`·`click_share`·`conversion_share`(광고 없음이면 NULL)와 DB 제약 셋(선택 열 묶음에 비율 포함·열마다 1~98·합 100), `pricing_unit` 열 삭제(마이그레이션 `records/0012_decision_charge_shares`, 빈 DB 전제). 결정은 판정에 쓴 정책 버전의 비율을 남긴다 — `records`가 정책 스냅샷에서 옮긴다. 엔진은 비율을 쓰지 않아 `Candidate`에는 넣지 않았고(필요한 선택 알고리즘이 생기면 그때 더한다), 쓸모가 없어진 `Candidate.pricing_unit`은 6-10d 대신 여기서 지웠다. 과금: `share/v1`(내림(적용 금액 × 결정의 그 유형 비율 ÷ 100)), `by-unit/v1` 삭제, `charge_for_reaction(…, shares, …)`, 정책 반환값 검사를 "0 이상 적용 금액 이하"로 좁혔다. 하한 최소 100: 서비스 세 곳 + DB 제약 `masters_policy_floor_min`(마이그레이션 `masters/0006_bid_policy_floor_min`). 광고별 소진액은 모든 유형(K6). C2: 종류별 `SCHEMA_VERSIONS`(`ad.decision` 2, 나머지 1), `selected.charge_shares`. C1 1.4.0(설명 문구와 "v1.4 변경"). 시험: 공장 기본값을 하한 100·기준가 200·상한 500·입찰 300·일예산 50,000으로, 구성 단위 쪽 98%(`shares_for`), 원장 동작만 보는 시험은 `WHOLE`(100%). 시험 속 입찰·금액 단언을 새 기준으로 고쳤다(약 40개 파일). 새 시험 `test_the_floor_is_at_least_100_in_all_three_places`·`test_charge_shares_follow_the_policy_rule_in_db`·`test_schema_version_is_per_event_kind`(6-12c에서 `test_writes_one_row_with_the_envelope`로 합침). 이름·내용을 바꾼 시험 `test_charge_policy_by_share`(위협 모델 T31 인용)·`test_a_valid_report_is_accepted_and_charged_by_the_recorded_share`(T37 인용)·`test_every_type_is_charged_by_its_share`. 광고 범위 소진액 시험에 클릭·전환을 더했고, 부하 불변식은 과금 기대값을 비율로 따로 계산한다(직접 넣은 인정 반응도 과금). 부하 시드: 구성 100/200/500, 입찰 300·400, 광고주 지갑 +450,000(금액을 10배 올린 만큼). 변형 24개 모두 잡음(처음에 둘 — 결정 제약의 클릭 비율 하한, 광고 없는 결정의 노출 비율 — 을 못 잡아 열마다 경우를 더했다). 서빙 질의 수: 결정 11 · 반응 40 그대로, 클릭 28 → 37 — 클릭도 이제 1% 과금되어 과금 한 건의 질의(원장·지갑·소진액·과금 이벤트)가 더해졌다. 같은 측정을 클릭은 과금하지 않는 정책으로 하면 28이다(새 기준선 11 · 40 · 37). 부하 시드를 바꿔 장애 시험 두 시나리오도 미리 돌렸다(통과, 구간 대조 `match` 12). 같은 커밋의 문서: C1 1.4.0·계약 요약, DRD 0.46(R1·M3·B2·P3·§5.6·멱등 표·무결성 표·§8·§9·ERD), 위협 모델(T31·T37 인용, 결정 뒤 변경 행), 이 계획 Step 1 시험 표의 바뀐 이름. 시험 1,338 → 1,341 |
| **6-10d 단위 제거 + 광고주 화면** | · `Slot`·`AdGroup`의 `pricing_unit`과 마이그레이션(데이터 이전 없음), 불변 검사, `unit_mismatch`·`unit_immutable`, 후보 조립의 단위 거르기(`Candidate`의 단위는 6-10c에서 지웠다)<br>· 광고 만들기의 ② 과금 단위 단계·단위로 거르는 JS, 광고 상세·캠페인 상세의 단위 표시, 운영 구성 만들기 폼의 단위<br>· 구성 목록·미리보기에 비율과 유형별 예상 과금(B7, `billing`의 같은 함수)<br>· C6, DRD M2·O2·§4.4, 위협 모델 T28 인용 | · 아무 구성이나 함께 고를 수 있다<br>· 단위 경로·필드가 없다<br>· JS 없는 흐름 시험<br>· 미리보기의 예상 과금 = 실제 과금(같은 입찰·정책으로 반응을 보내 비교)<br>· 접근 전수 시험·화면 점검<br>· 변형 검사 | **완료 `d557905`** — 모델: `Slot`·`AdGroup`의 `pricing_unit` 열과 불변 검사 삭제(마이그레이션 `masters/0007_without_pricing_unit`·`campaigns/0008_without_pricing_unit`, 빈 DB 전제), `PricingUnit` 삭제. 서비스: `create_slot`·`create_ad_group`의 단위 인자, `unit_mismatch`·`unit_immutable`(이제 `update_ad_group`에 `pricing_unit`을 보내면 모르는 필드로 400), 후보 조립의 단위 거르기 삭제 — 광고는 아무 켜진 구성이나 함께 고른다. 예상 과금: `billing.expected_charges(shares, applied)`가 실제 과금과 같은 정책 함수로 반응 유형별 금액을 낸다. `PolicyView.charge_shares`. campaigns와 billing은 같은 층이라 서로 부르지 않으므로 화면(`console.views.ads.effect_row`)이 위치별 결과에 예상 과금을 붙인다. 광고주 화면: 광고 만들기의 "② 과금 단위" 단계·'단위 보기' 버튼·단위로 거르는 JS·CSS 삭제(① 캠페인 ② 광고 ③ 소재 ④ 집행), 구성 목록·광고 상세의 위치에 "노출 X% · 클릭 Y% · 전환 Z%", 미리보기·광고 상세의 위치별 결과에 "예상 과금(반응마다)", 캠페인 상세의 단위 칸 삭제. 저장은 '집행'(`action=create`)만 한다 — 사라진 '단위 보기' 버튼이 남은 옛 화면이나 모르는 값은 다시 그리기만 한다. 운영 화면: 구성 만들기 폼·매체 상세·일괄 변경·정책 화면의 단위 칸 삭제. C6: 단위 필드·거르기·오류 삭제, `ReactionType`(원장 참조의 반응 유형)·`ChargeShare`·`SlotPolicy` 비율·`SlotEffect.expected_charges`. 시험: 단위 인자를 지운 호출 약 70곳, 단위 규칙 시험을 새 규칙으로 — `test_slot_audience_immutable`(T28 인용)·`test_an_ad_may_combine_any_slots`·`test_pricing_unit_is_no_longer_a_field`(6-12c에서 `test_update_ad_group_replaces_slots_atomically`로 합침)·`test_page_groups_slots_by_media_and_every_slot_is_selectable_with_its_shares`, 새 시험 `test_the_preview_charges_are_what_the_ad_is_actually_charged`(미리보기 "노출 2 · 클릭 245 · 전환 2" = 그 광고가 실제로 받은 과금)·`test_only_the_create_button_saves`, 지운 시험 셋(단위 고르기 화면·광고그룹 단위 불변·단위가 다른 후보). JS 없는 흐름은 단위 단계 없이 미리보기 → 집행, 시험 도우미의 꺼진 칸 검사는 작은 HTML로. 변형 9개 모두 잡음. 서빙 질의 수 11 · 40 · 37 그대로. 같은 커밋의 문서: C6, DRD 0.47(M2·O2·ERD·무결성 표·§9), 위협 모델 T28 인용, 이 계획 Step 1 시험 표의 바뀐 이름. 시험 1,341 → 1,340 |
| **6-10e 화면 용어** | "게재 위치" → "구성"(운영·광고주 화면, 화면에 보이는 서비스 오류 문구 포함), 설계 §10 용어 행 | 화면 문구만 바뀐다. 남은 "게재 위치"가 없음을 화면 점검으로 확인 | **완료 `d5a4b46`** — 바꾼 것: 광고주·운영 화면 템플릿의 "게재 위치"(표 머리·칸 이름·버튼·안내·빈 목록, 조사도 맞춤: 위치가 → 구성이 등), 단독 "위치"("꺼진 위치"·"위치별 결과 미리보기"·"그 위치에는"·결과 이름 "꺼진 구성 — 노출 안 됨"·"알 수 없는 구성"), 폼 칸 이름("구성"·"구성 이름"), 화면 메시지·알림 문구, 화면에 보이는 서비스 오류 문구(구성 이름 검사 `clean_text` 이름표·같은 이름 충돌·구성 고르기 검사 넷). 그대로 둔 것: 코드 이름(`Slot`·`slot_id`)·C1·C6·문서·주석, 매체용 C1 응답 문구(`records.decide`의 "게재 위치를 찾을 수 없습니다"), 404로 바뀌어 화면에 나오지 않는 `NotFound` 문구, Django admin 모델 화면. 시험 먼저: 새 시험 `test_screens_say_composition_not_placement`(6-12c에서 `test_screens_use_the_screen_terms`로 합침)(화면 점검의 광고주·운영 화면 전부에 "게재 위치"가 없다)와 문구를 단언하던 시험(같은 이름 충돌·구성 고르기·꺼진 구성)을 바꾼 뒤 옛 문구에서 실패함을 확인. 구성 이름 검사 문구 단언을 더했다. 변형 5개 모두 잡음. 같은 커밋의 문서: 설계 §10 "화면 용어: 구성"(단독 "위치"와 서비스 오류 문구 포함). 시험 1,340 → 1,341 |
| **6-10f 측정·완료** | 서빙 질의 수, 150 동시 부하, 장애 시험 두 시나리오, 부하 시험 문서(`load-test.md`)의 시드, 완료 기록(이 절·§8 요약·§10, 설계 §2·§8·§10 해시) | 모든 불변식 충족, 기준선 기록 | **완료(이 커밋)** — HEAD `d5a4b46`에서 서빙 질의 수 결정 11 · 반응 40 · 클릭 37(6-10c에서 정한 새 기준선 그대로), 150 동시 부하 모든 불변식 충족(검사 52개 — 저장 행 결정 1,415 · 반응 2,526 · 과금 1,372, 6-9 때 과금 762에서 는 것은 클릭·전환도 과금되기 때문), `failure_test.py` processor-kill·relay-kill 통과(구간 대조 `match` 12). 부하 시험 문서 `load-test.md`에 "§11 Step 6-10 과금 재설계 뒤 재확인"(바꾼 시드·검사, 결과)을 더하고 검사기 설명의 과금 기대값을 고쳤다. 완료 기록: 이 절·§8 요약·§10, 설계 §2·§3(C6 요약)·§4 구조도·§4.1·§4.2·§4.3·§4.4·§4.6·§4.7·§8·§10("구현 예정"·"6-10에서 바뀜, 구현 예정" 표시를 해시로). 앞 단계 표의 상태 칸 앞에 잘못 들어간 `||`(6-10c·6-10d·6-10e 행)도 바로잡았다. 정합 점검 중 찾은 6-9 때의 빠뜨림: DRD ERD의 관계 줄이 "광고그룹 → 소재"로 남아 있어 소재 목록·연결 표·선택으로 고쳤다(DRD 0.48) |

**검증**(구현 세션): 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`·`bandit` 통과. 시험 1,337 → 1,338(6-10b) → 1,341(6-10c) → 1,340(6-10d) → 1,341(6-10e). 변형은 6-10b 17개·6-10c 24개·6-10d 9개·6-10e 5개를 모두 잡았다(처음 놓친 것은 시험을 보강해 잡았다 — 6-10b 표시 셋, 6-10c 열마다의 비율 둘). 서빙 질의 수는 6-10c부터 결정 11 · 반응 40 · 클릭 37이다(클릭도 1% 과금되어 과금 한 건의 질의가 더해짐 — 클릭을 과금하지 않는 정책으로 재면 28). 6-10c(부하 시드를 바꾼 단계)와 6-10f에서 150 동시 부하·장애 시험 두 시나리오를 돌려 모두 통과했다. K1에 따라 6-10b 착수 때 모든 개발 DB(MySQL 셋·MongoDB 둘)를 지우고 새로 만들었고, 6-10c·6-10d 마이그레이션은 세 개발 DB에 그대로 적용됐다(옛 데이터 없음). 단계마다 검토용 dev 서버(`ads_review67`)를 다시 띄웠다(6-10b에서 DB와 계정·예시 광고를 새로 만듦).

**알아 둘 점**
- **시험 수정량은 6-10c가 가장 크다.** 금액이 들어간 단언(입찰 30·과금 30 등)을 하한 100 기준으로 다시 쓰고, 과금 단언은 비율로 계산한 값으로 바꾼다.
- **서빙 질의 수**: 6-10c 전 결정 11 · 반응 40 · 클릭 28 → 6-10c 뒤 **11 · 40 · 37**. 결정 행에 열만 늘어 결정·반응은 그대로이고, 클릭은 이제 과금되어 과금 한 건의 질의가 더해졌다(6-10c 행). 6-10f에서 다시 재도 같았다.
- **열린 항목**: 확장 때 파이프라인에 C2 `ad.decision` 스키마 2 공유, 팀 DRD의 `charge_unit_code` 대응(DRD §9).

### 8.4.12 6-11 광고 상세의 이미지 칸 — 고르기만·올리기만 (기준 코드·문서 `9822393`, 완료 2026-10-13)

**계기**: 사용자가 검토용 dev 서버의 광고 상세를 보고 요청했다(2026-10-13). "소재" 칸은 연결된 소재마다 제목·주소 수정과 이미지 교체 폼이 붙어 있어 "추가하는 형태"로 보이고, "소재 더하기"는 올리기와 등록된 소재 연결이 섞여 있다.

**정한 것** [사용자 요청 2026-10-13 — "우선" 이 화면만]
- "소재" → **"이미지"**: 내 이미지(보관하지 않은 소재 전부) 중 하나를 **고르기만** 한다. 아직 이 광고에 연결되지 않은 이미지를 고르면 같은 트랜잭션에서 연결하고 선택한다(`link_creative(…, select=True)`). 지금 나가는 이미지는 "나가는 중"으로 보이고 버튼이 없다.
- "소재 더하기" → **"이미지 업로드"**: **올리기만** 한다. 내 목록에만 올리고 이 광고에 연결·선택하지 않는다. 올린 이미지는 위 "이미지"에서 고른다.
- 제목·이동 주소 수정과 이미지 교체는 **소재 상세에서만** 한다. 광고 상세의 수정 폼, 별도의 "등록된 소재 연결" 폼과 경로(`ad_group_creative_link`), 소재 폼이 광고 상세로 돌아가던 숨김 칸 `ad_group_id`를 없앴다.
- 다른 화면(메뉴 "소재", 소재 목록·상세, 광고 만들기 ③)의 "소재" 용어는 그대로다. 계약(C6의 연결 `PUT`·선택 `PATCH creative_id`)도 그대로다.

| 단계 | 할 일 | 완료 증거 | 상태 |
|---|---|---|---|
| **6-11 광고 상세의 이미지 칸** | 서비스 `link_creative(select=)`, 광고 상세 조립(`images`)·뷰·템플릿, 경로 하나 삭제, 소재 수정·교체 뷰는 소재 상세로만 돌아감, 시험, 설계 §10 "소재 목록"·§2·§8, 위협 모델 T43, 이 절·§8 요약·§10 | 이미지 칸은 고르기만·업로드 칸은 올리기만, 연결 안 된 이미지를 고르면 연결과 선택이 함께(끝난 캠페인이면 둘 다 안 함), 남의 광고·남의 이미지 404, 남의 광고 화면으로는 올라가지 않음 | **완료 `5fe343c`** — 새 시험 `test_the_image_section_only_selects_and_the_upload_section_only_uploads`(화면 구조, 고르면 연결·선택, 올리기는 연결·선택 없음)·`test_choosing_an_unlinked_creative_links_and_selects_it_in_one_go`(서비스, 끝난 캠페인이면 연결도 남지 않음). 광고 상세를 거쳐 소재를 고치던 시험은 소재 상세를 거치게(인용한 이름 그대로), 격리 시험은 남의 광고 화면으로의 올리기·남의 이미지 고르기, JS 없는 흐름은 소재 목록에 올린 이미지를 광고 상세에서 바로 고른다. 지운 시험: 광고 상세에서 소재마다 이미지 교체 폼이 따로인지(이제 그 폼이 광고 상세에 없다). 변형 6개 중 5개를 잡았고, 놓친 하나(보관한 이미지의 버튼 조건)는 결과가 같은 등가 변형이라 조건을 지웠다(보관한 이미지는 선택된 것일 때만 목록에 있다). 같은 커밋의 문서: 설계 §10 "소재 목록"(6-11)·§2·§8, 위협 모델 T43(⑦·⑫·⑮, 인용 시험 둘). 시험 1,341 → 1,342 |

**검증**: `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0. 서빙 경로는 건드리지 않았다(결정·반응·클릭 질의 그대로).

**보완(외부 검토 R10, 2026-10-13)**: 소재 상세의 수정·이미지 교체에서 폼이 거르는 분기(빈 제목·변경 시각 없음·파일 없음)를 지나는 시험이 없었다 — 그 분기에 예외를 넣어도 시험이 모두 통과했다. 기존 시험의 공백 제목(`" "`)은 폼이 공백을 지우지 않아(`strip=False`) 서비스가 거르는 분기로 갔다. 새 시험 `test_inputs_the_forms_reject_redraw_the_detail_page_and_change_nothing`: 셋 모두 400, 제출한 폼을 입력값 그대로 다시 그림, 소재는 바뀌지 않음. 변형 8개(두 분기마다 예외·분기 삭제·200·새 폼으로 다시 그리기) 모두 잡음. 시험 1,342 → 1,343. 메모: 숨김 칸 `updated_at` 의 오류는 화면에 보이지 않고 다시 그린 폼에서도 비어 있다(조작한 요청에서만 생김, 캠페인 수정·광고 이름 폼도 같음) — 고치지 않았다.

### 8.4.13 6-12 코드 정리 (리팩터링 6차 — 시험 코드 포함, 기준 코드·문서 `e621248`, 완료 2026-10-13)

**무엇**: 6-7~6-11(캠페인·광고·소재 구조 재편, 구성별 반응 비율 과금, 화면 용어, 광고 상세의 이미지 칸) 뒤의 제품 코드와 **시험 코드**를 정리한다. 기능을 더하거나 빼지 않고 동작도 바꾸지 않는다 — 응답 코드, 렌더된 화면의 문구·구조, DB 쓰기, 잠금 대상과 순서, 질의 수, 감사 기록, 이벤트가 그대로다. 계약·설계 결정은 바뀌지 않는다. 리팩터링 세션이 ponytail-audit(과잉 설계 점검)으로 영역 넷(L0·L1과 scripts, L2, L3·L4, 시험)을 훑어 후보를 냈다(HEAD `5fe343c`, 시험 1,342).

**정한 것** [2026-10-13 — 사용자가 진행을 리팩터링 세션에 맡겼고, 리팩터링 세션의 권장안대로 한다]
- **D-1 폼 제출 틀**: "폼 검증 → 서비스 호출 → 거절이면 폼에 오류(`form_errors`)와 응답 코드(`status_of`) → 다시 그리기"가 콘솔·운영 뷰 14곳에 되풀이된다. 6-6f는 광고그룹 화면만 묶었고, 6-9 뒤 소재·캠페인·광고 만들기 화면에 같은 틀이 다시 생겼다. 12곳이 `console/errors.submit` 하나를 쓴다. 가입(`ValidationError`만 잡는다)과 내 정보·비밀번호(응답 코드가 400 고정 — 아래 "보고만" R6)는 그대로 둔다.
- **D-2 구성별 결과 표**: 광고 만들기의 미리보기와 광고 상세에 있는 같은 표 두 벌을 조각 하나(include)로. 렌더 HTML은 공백만 달라진다(문구·구조·열은 같다) — 바꾸기 전후 HTML을 공백을 정규화해 비교한다.
- **D-3**: 위협 모델·DRD가 인용한 동시 제출 화면 시험(`test_the_same_form_sent_twice_at_once_creates_once`)은 남긴다. 잠금 안의 키 재확인은 서비스 경쟁 시험만 잡지만, 화면 입구의 보안 인용 시험이고 아끼는 것(0.7초)이 작다.
- **D-4 문서**: 이번에도 리팩터링 세션이 고친다(6-6과 같다) — 이 절·§8 요약·§10, 위협 모델 인용(시험을 지우기 **전에** 대체 시험으로, 6-12b), 이 계획의 낡은 표에 "6-N에서 바뀜" 표시, 설계 §2·§8.

**시험을 지우는 기준**: 6-6과 같다. 지울 시험이 잡는 결함을 제품 코드 변형으로 만들어 **대체 시험이 같은 변형을 잡는지** HEAD 사본에서 돌린다(6-12c 착수 때). 못 잡으면 지우지 않고 단언을 옮기거나 남긴다. 제품 코드를 바꾸는 단계(6-12d~6-12f)는 바꿀 곳을 지키는 시험이 있는지 변형으로 먼저 보고, 없으면 단언을 먼저 더한다.

**단계** (한 단계 = 한 커밋, `check.sh`(`DB_NAME=ads_refactor6`))

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-12a 시험 먼저** | 리팩터링(D-1)이 지날 분기 중 시험이 없던 곳: 소재 수정·이미지 교체의 폼 검증 실패 분기(아래 "보고만" R10) | `e621248`(구현 세션, §8.4.12 보완) — 시험 1,342 → 1,343 |
| **6-12b 문서: 결정·계획·인용** | 이 절·§8 요약·§10, 위협 모델 T35의 인용(`test_audience_cannot_be_changed_after_creation` → 본문이 같은 `test_slot_audience_immutable`), Step 1 표(§5·§6.8.1)의 소재·과금 단위 행에 "6-9·6-10에서 바뀜" 표시, §8.4.8 ③의 정정, 6-9f·6-10f·6-11 해시, 설계 §2·§8 Step 6 | `78effec` |
| **6-12c 시험 정리** | 아래 "시험" | `1b0146b` — 폐기 3: 지울 시험이 잡는 변형 9개를 HEAD 사본에서 돌려 남는 시험이 8개를 잡았다(나머지 하나 — 광고그룹 만들기의 종료 확인 삭제 — 는 지울 시험도 못 잡고 남는 시험은 잡는다). 합치기: 화면 용어 둘 → `test_screens_use_the_screen_terms`(화면별 "과금 단위" 단언 둘도 금지어로), `test_pricing_unit_is_no_longer_a_field` → `test_update_ad_group_replaces_slots_atomically`의 잘못된 입력 반복(빈 변경 `{}`도 더함), `AdGroupCreatedSlotsTests` → `test_an_ad_may_combine_any_slots`(구성 정렬 단언), `test_schema_version_is_per_event_kind` → `test_writes_one_row_with_the_envelope`, `test_payload_shapes`의 비율·`pricing_unit` 단언 둘(결정 이벤트 전체 비교가 본다) — 합친 시험이 변형 9개(화면에 옛 용어, 모르는 필드·빈 변경 검사 삭제, 정렬 삭제, 스키마 버전, 결정 이벤트의 키, 일괄 도우미가 개인 구성을 만듦)를 모두 잡음. 옮기기: 소재 상세 시험 7개 → `test_creative_pages.CreativeDetailTests`(이름 그대로), 광고 상세에 남은 이미지 칸 시험은 `ImageSectionTests`. 도우미: `World.shared_ad()`(일괄 구성 + 광고 + 소재, 6곳). 낡은 것: 없어진 설정을 덮어쓰는 `override_settings` 둘, 단위 시절 이름·설명(`shares_for`·`World(unit=)`·`FunnelMixin.UNIT`, 기록 시험의 `UNIT` 상수 둘은 값으로, 쓰이지 않는 `new_slot(unit=)`), `by-unit/v1` 데이터, 옛 금액을 적은 docstring 셋, 뜻 없는 `?unit=` 화면 점검 주소, Step 1 시나리오의 쓰이지 않는 단위 칸과 위 합친 시험과 겹치는 "섞임" 광고그룹, 쓰이지 않는 import 다섯. **하지 않은 것**: 광고 만들기 서비스 시험 옮기기(`test_campaigns_services.CreateAdTests`가 서비스 파일의 제자리이고 소재 목록 쪽 둘은 재사용·요청 키 시험) · 캠페인 만들기 화면 시험 옮기기(`test_ad_create` 의 docstring 이 두 흐름을 함께 다룬다고 밝힌다) · 광고 만들기 시험의 새 소재 부분(이름이 "새로 또는 재사용"이라 이름까지 바꿔야 해 아끼는 것이 없다) · 남의 소재 404 람다 둘(격리 목록이 한곳에서 완결되는 쪽이 낫다) · 광고그룹 + 소재 준비 6곳(입찰·이미지·캠페인이 곳마다 달라 도우미 인자만 는다). 시험 1,343 → 1,336 |
| **6-12d L0·L1·scripts** | 아래 "L0·L1·scripts" | `0177dbc` — 바꾸기 전 변형 8개 중 6개는 지금 시험이 잡았고, HTML 오류 화면의 제목과 문구를 바꿔치는 둘을 못 잡아 화면 점검 시험(`test_post_only_and_error_screens_are_checked_too`)에 단언 두 줄을 먼저 더했다. 바꾼 뒤 같은 변형 8개 모두 잡음(소유자 거르기, 오류 화면의 코드·제목·문구, 구성 성격 검사, 구간 대조 집계, 부하 검사기의 중복 인정·그날 과금 합). `owned_queryset`을 지우며 그 시험(`test_owned_queryset_contains_only_own_objects`)도 지웠다 — `owned_or_404` 시험 셋이 소유 거르기를 본다. `slot.media = media`를 지운 전후 `create_slot` 질의 6번 그대로. `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, "No directory" 0, 남은 임시 폴더·컨테이너 0). 시험 1,336 → 1,335 |
| **6-12e L2** | 아래 "L2" | `45ddf24` — 바꾸기 전 변형 8개 모두 지금 시험이 잡음(잠긴 광고그룹의 종료 확인 4곳, 켜기 값의 형 검사, 소재 개수 상한의 경계·보관한 소재 제외, 지갑 행 잠금). 바꾼 뒤 변형 5개 모두 잡음 — 종료 확인은 이제 `_locked_group` 한 곳이라 그 한 줄을 지우는 변형 하나가 네 동작을 함께 본다. `create_creative` 의 소재 개수 검사는 그 자리의 주석으로(호출자 하나뿐인 `_check_creative_count`). 시험 1,335 그대로 |
| **6-12f L3·L4** | 아래 "L3·L4"(D-1·D-2). 바뀐 화면의 렌더 HTML을 바꾸기 전후로 비교 | `800797b` — `console/errors.submit(form, call, **kw)` → `(결과, status)`: 폼이 거르면 400, 서비스가 거절하면 폼에 오류를 붙이고 `status_of`. 광고 상세의 `_submit`(폼 4개), 소재 목록·수정·이미지 교체, 캠페인 만들기·수정, 광고 만들기, 운영의 매체 등록·구성 만들기·정책 변경·일괄 변경·포인트 조정이 이것을 쓴다. GET·POST를 함께 받는 운영 화면 셋은 `form.is_bound`일 때만 제출로 본다 — 빈 POST가 지금처럼 200이고, `400 if status == 200 and form.errors else status` 식이 없어졌다. "바뀐 것이 없습니다"가 있는 소재 수정·캠페인 수정은 그 분기를 그대로 두고 서비스 호출만 `submit`. 상세 감싸개 뷰 4개를 지우고 내부 함수가 그 이름으로(제출 뷰가 `status`·다시 그릴 폼을 넘긴다), 소재 상세는 `(소재 ID, 폼)` 튜플 대신 폼. 구성별 결과 표는 `console/_effects.html` 하나(광고 상세는 `bounds=True`로 하한 ~ 상한 칸) — 행은 광고 만들기의 한 줄 모양이라 그 화면의 단언(칸 사이 공백 없음)이 그대로 맞고, 광고 상세의 행은 공백만 달라진다. 일괄 변경 칸 7줄 → 반복(출력 같음), `campaigns._back` → 그 자리, 광고 만들기 context `chosen` → 템플릿의 `form.slot_ids.value`, 죽은 CSS 규칙 하나, `records._record_click`의 읽지 않는 반환값, 낡은 docstring 둘. **확인**: 바꾸기 전후로 같은 순서의 요청 84개(바뀐 뷰 12곳의 GET, 폼 오류, 서비스 오류 400·409, 빈 POST, "바뀐 것이 없습니다", 완료 뒤 이동한 화면, 켜기·끄기의 돌아갈 곳 — 위조한 값 포함)를 HEAD 사본과 바꾼 사본에서 보내 비교: 상태·이동·질의 수는 84개 모두 같고, HTML은 무작위 값(UUID·CSRF·요청 키·CSP nonce·시각)을 맞추면 결과 표가 있는 16개만 공백이 다르고 공백까지 맞추면 0개 차이. 바꾸기 전 기준선은 두 번 찍어 같음을 먼저 확인했다. 변형 6개 중 5개를 잡음(폼 오류 200, 서비스 거절 400 고정, 폼에 오류를 붙이지 않음, 이미지 칸 인자 버림, 켜기·끄기의 돌아갈 곳). 놓친 하나 — 운영 매체 화면의 빈 POST 를 제출로 보는 변형(200 → 400) — 는 지금 시험이 그 응답을 고정하지 않아서다. 바꾸지 않았음은 위 화면 비교가 보였고, 그 동작 자체가 "보고만" R7이라 시험으로 고정하지 않았다. 시험 1,335 그대로 |
| **6-12g 마무리** | `check.sh`, 150 동시 부하, `failure_test.py` processor-kill·relay-kill, 서빙 질의 수(결정 11 · 반응 40 · 클릭 37), 문서 정합 점검·완료 기록, DB 정리 | **완료(이 커밋)** — HEAD `800797b` 에서 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,601 · 과금 1,372, MySQL 1040 은 §9 의 알려진 현상으로 재시도에서 통과), `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, 남은 임시 폴더·컨테이너 0), 서빙 질의 수 결정 11 · 반응 40 · 클릭 37 그대로. 설계 §2·§8 Step 6 의 6-12 완료 |

**시험**(6-12c, 시험 1,343 → 약 1,336)
- 폐기: `test_slot_audience::test_audience_cannot_be_changed_after_creation`(본문이 `test_masters_models::test_slot_audience_immutable`과 같다 — 6-10d에서 단위 시험을 고치다 둘이 됐다) · `test_creative_pages::test_an_edit_from_the_detail_page_returns_there`(소재 상세 수정 시험 둘) · `test_creative_library::test_a_failed_ad_leaves_no_ad_group`(광고 만들기 서비스 시험 셋과 종료 가드)
- 합치기: 화면 용어 시험 둘(`test_screens_say_ad_not_ad_group`·`test_screens_say_composition_not_placement`) → 금지어를 도는 하나(화면별 "과금 단위" 단언 둘도) · `test_pricing_unit_is_no_longer_a_field` → 광고그룹 수정의 잘못된 입력 반복(모르는 필드 검사를 지키는 유일한 시험이라 옮긴다) · `AdGroupCreatedSlotsTests` → `test_an_ad_may_combine_any_slots` · `test_schema_version_is_per_event_kind` → outbox 봉투 시험 · `test_payload_shapes`의 비율·`pricing_unit` 단언(결정 이벤트 전체 비교와 겹친다) · 광고 만들기 시험의 새 소재 부분집합 · 남의 소재 404 람다 둘
- 옮기기(이름 그대로): `test_ad_group_pages`에 남은 소재 상세 시험 → `test_creative_pages` · 두 파일에 흩어진 광고 만들기 서비스 시험 → 한곳 · 캠페인 만들기 화면 시험 → `test_campaign_pages`
- 도우미: 일괄 구성 + 광고 + 소재, 광고그룹 + 소재 준비(각 6곳) → `tests/factories`
- 낡은 것: 없어진 설정 `MAX_CREATIVES_PER_AD_GROUP`을 덮어쓰는 `override_settings` 둘, 과금 단위 시절의 도우미 이름·설명(`shares_for`·`unit=`·`UNIT`), 없어진 정책 이름 `by-unit/v1` 데이터, 옛 금액을 적은 docstring, 같은 화면을 뜻 없는 매개변수로 한 번 더 그리는 화면 점검 주소

**L0·L1·scripts**(6-12d): `foundation/access.owned_queryset`(제품 코드 호출 없음)을 `owned_or_404` 안으로, 틀린 docstring("모든 조회가 이것을 지난다")도 · 호출자 하나뿐인 `masters._validate_audience`·`foundation/http._html_error` · `create_slot`의 `slot.media = media`(만들 때 이미 채워진다) · `load_test.run()`의 단계 반복을 반복문으로, 손으로 센 집계를 `collections.Counter`로(`verify_hops` 포함) · `failure_test`의 DB 고르기·`lag` 정리 · 낡은 주석(`masters/models.py`, `load_test`의 옛 금액)

**L2**(6-12e): `campaigns._locked_group`이 바로 뒤의 `tr.assert_open`까지 한다(호출 4곳 모두 같다, 잠금 순서 그대로) · 호출자 하나뿐인 `_flag`(6-9b 뒤)·`_check_creative_count` · billing의 지갑 404 변환 두 벌 → 하나 · 낡은 docstring(`charged_amounts`의 "과금 단위가 아닌 유형", `create_creative`의 "올려서 연결", `_part`의 이유, `campaigns/models.py`의 엉뚱한 줄에 붙은 이력 주석)

**L3·L4**(6-12f): `console/errors.submit`(D-1) · ID만 넘기는 상세 감싸개 뷰 4개(`ad_group_detail`·`creative_detail`·`media_detail`·`advertiser_detail`) · 구성별 결과 표 include(D-2) · `policy_bulk.html`의 칸 반복 · 호출자 하나뿐인 `console/views/campaigns._back` · 어떤 화면에도 `disabled`가 없어 죽은 CSS 규칙 하나(옛 단위 단계) · 소재 상세의 `(소재 ID, 폼)` 튜플 → 폼, 광고 만들기 context `chosen` · `records._record_click`의 읽지 않는 반환값 · 낡은 docstring(`CreativeUploadForm`, `records.charge_shares`)

**검증**(리팩터링 세션): 단계마다 `check.sh`(`DB_NAME=ads_refactor6`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, `pip-audit`·`bandit` 통과. 시험 1,343 → 1,336(6-12c) → 1,335(6-12d), 전체 시험 127초 그대로. 시험 코드 순감 57줄(파일 수 그대로), scripts −28줄, 제품 코드(템플릿·CSS 포함) −126줄(23개 파일, 조각 템플릿 하나 늘어남). 변형 검사(HEAD 사본에서, 공유 작업 트리를 건드리지 않게): 6-12c 폐기 9·합치기 9, 6-12d 바꾸기 전 8(오류 화면 단언 둘을 먼저 더함)·뒤 8, 6-12e 전 8·뒤 5, 6-12f 6(놓친 하나는 위 6-12f 행). 6-12f 는 바꾸기 전후 화면 84개의 상태·이동·질의 수·HTML 을 비교했다. 150 동시 부하, `failure_test.py` 두 시나리오, 서빙 질의 수는 6-12g 행. 메모: 변형 사본에서 `DB_NAME` 없이 한 번 돌려 공유 기본 이름의 시험 DB(`test_ads_server`)가 `--keepdb` 로 남았다 — 지우는 명령이 이 세션에서 막혀 사용자에게 알렸다(남아 있으면 기본 DB 이름으로 `check.sh` 를 돌릴 때 "Type 'yes'"에서 멈춘다).

**정리하지 않는 것**: 두 상시 명령의 `stamped()`(6-3b 결정, §8.4.5) · `foundation/http._has_unpaired_surrogate`를 `json.dumps(…).encode()`로(신뢰 경계에서 영리한 대체이고, 서빙 경로에서 본문을 한 번 더 직렬화한다) · `assets.ValidatedImage`의 `content_type`·`width`·`height`(시험만 읽지만, 지우면 계약 시험의 기대값을 제품 코드의 값으로 바꿔야 해 시험이 약해진다) · `PASSWORD_MIN_LENGTH`·`PASSWORD_MAX_LENGTH`(문서가 인용) · `engine/types` 검증 반복 합치기(어느 오류가 먼저 나는지가 바뀐다) · `events/api` 기록 함수의 한 줄화(잘못 부를 때의 예외 종류가 바뀐다) · 렌더 HTML에만 있는 class(`creative-new`·`creative-existing` — 지우면 HTML이 바뀐다) · 값 객체의 쓰이지 않는 기본값(줄이 줄지 않는다) · 이전 차수에서 남긴 것(§8.2.4·§8.3.4·§8.4.5·§8.4.7 — `ChargePolicy` Protocol 포함: 6-10c에서 구현이 `share/v1`로 바뀌었을 뿐 교체 지점이라는 근거는 그대로다)

**보고만**(동작 변화라 구현 세션 몫 — 리팩터링 세션이 6-12 후보를 찾다 발견, 2026-10-13. R10은 6-12a에서 시험을 더했다)
- 화면·서비스
  - R1 광고 만들기: 등록된 소재가 없는 광고주가 "등록된 소재 쓰기"로 집행하면 400인데, 오류가 붙는 `creative_id` 칸을 그리지 않아 화면에 오류가 보이지 않는다(`ad_create.html`의 `has_creatives` 분기, `AdCreateForm.clean`). — **6-13a에서 고침**(§8.4.14).
  - R2 광고 만들기: 구성 칸 오류가 있으면 `id="id_slot_ids_error"`가 둘이 된다(템플릿의 바깥 `div`와 Django 6.1 오류 목록의 `ul`). — **6-13a에서 고침**(§8.4.14).
  - R3 `creative.linked` 감사 기록의 `selected`는 요청 플래그다 — 선택된 소재가 없어 연결과 함께 자동 선택돼도 `false`가 남는다. — **6-13b에서 고침**(§8.4.14).
  - R4 그 자동 선택(`campaigns._link`)은 광고그룹의 `updated_at`을 올리지 않아, 화면이 본 시각 대조(`_assert_seen`)가 이 변경을 보지 못한다. 명시적 선택은 올린다. — **6-13b에서 고침**(§8.4.14).
  - R5 `campaigns._created_by_key`는 `create_ad`가 받은 `now`를 쓰지 않고 지금 시각으로 중복 응답의 캠페인 상태를 만든다(`ad_created_by_key`에는 `now` 인자도 없다). — **6-13b에서 고침**(§8.4.14).
  - R6 비밀번호 변경 서비스는 그 사이 계정 상태가 바뀌면 `Conflict`(409)도 던지는데 화면은 400으로 그린다(시험이 400을 고정한다). §8.4.8 ③의 "계정 화면은 `ValidationError`만"은 틀렸다(정정 표시함). — **6-13a에서 고침**(§8.4.14).
  - R7 빈 POST의 응답 코드가 화면마다 다르다: 운영의 매체·정책·일괄 변경은 200(언바운드 폼), 소재 목록·캠페인 상세는 400. — **6-13 결정: 그대로**(사용자 2026-10-14). 브라우저 폼은 늘 CSRF 토큰을 실어 POST 가 비지 않는다 — 토큰만 실은 POST 는 다섯 화면 모두 400(임시 시험으로 확인), 200 은 CSRF 검사를 건너뛰는 시험 클라이언트의 완전히 빈 POST 에서만 난다.
  - R8 광고 상세의 "이 이미지로 바꾸기" 버튼이 이미지마다 같은 이름이다(구별되는 접근 이름 없음). 광고 만들기·광고 상세에서는 주 메뉴에 `aria-current`가 없다. — **6-13c에서 고침**(§8.4.14, 광고 화면의 현재 메뉴는 "캠페인" — 사용자 2026-10-14).
  - R9 `create_ad`는 역할 검사보다 입력 검사·요청 키 조회를 먼저 해, 광고주가 아닌 사용자가 403 대신 400·409를 받을 수 있다. — **6-13b에서 고침**(§8.4.14).
- 시험의 빈 곳
  - R10 소재 수정·이미지 교체의 폼 검증 실패 분기 — **6-12a `e621248`에서 더함**.
  - R11 광고 개수 상한을 **다른 캠페인**으로 동시에 넘기는 경쟁 시험이 없다(같은 캠페인이면 캠페인 행 잠금이 광고주 잠금을 가린다). — **6-13d에서 더함**.
  - R12 이름과 단언이 어긋나는 시험: 매체별 묶음·입찰 이력을 이름에 쓰고 단언하지 않는 화면 시험 둘, 지금은 캠페인을 만드는 `test_two_new_ads_with_different_keys_do_not_pass_the_campaign_limit`(위협 모델 인용), 마지막 단언이 늘 참인 `test_other_advertisers_unaffected`. — **6-13d에서 고침**.
  - R13 JS 없는 흐름의 입찰 `"40"`은 하한 100보다 낮아 하한 미만 경로만 지난다(의도 확인) · 소재 삭제 성공·이미지 고르기 실패 메시지를 보는 시험이 없다 · 비공개 함수 호출 수를 세는 단언 둘. — **6-13d에서 고침**.
- 질의(보류 묶음 — §8.4.7 ④에 더함)
  - R14 `create_ad`의 광고주 재잠금은 이제 새 소재 −4·재사용 −2이고, 재사용 경로는 연결 결과 뷰의 질의 2개를 버린다.
  - R15 `list_owned_creatives`의 사용처 집계를 광고 상세·광고 만들기가 버리고, 소재 상세는 소재 하나를 찾으려고 목록 전체를 읽는다. 소재·구성 화면의 오류 경로는 같은 것을 두 번 읽는다.
- 문서·설계
  - R16 Step 1 표의 과금 단위·소재 행 — **6-12b에서 "바뀜" 표시**.
  - R17 소재 선택 경로가 둘(`update_ad_group(creative_id)`·`link_creative(select=True)`)이고, 화면 호출자가 없는 C6 대응 함수(`list_creatives`·`list_ad_groups`)가 있다 — 정리는 C6 결정. — **6-13 결정**(사용자 2026-10-14): 선택 경로는 연결 하나로(**6-13e에서 고침**), C6 대응 함수는 그대로(설계 §6.6 콘솔 분리 대비).
  - R18 판정에 쓰이지 않는 `Candidate.base`·`bid_created_at` · 하한 ≥ 100 제약에 포함되는 `floor > 0` 제약(마이그레이션 필요) · 모델은 "기본값 없음"인데 `create_slot(audience=INDIVIDUAL)` 기본값. — **6-13f에서 고침**(사용자 결정 2026-10-14: 셋 모두 정리).
- scripts
  - R19 `failure_test`의 `wait_ready`가 `docker exec`를 시간 제한 없이 부른다(R5 규칙) · 정리 루프의 `wait(timeout=30)`에 kill 대체가 없어 걸리면 남은 점검을 건너뛴다 · `mongo_temp_rs`의 primary 대기 두 벌의 제한이 다르다. — **6-13g에서 고침**.

### 8.4.14 6-13 검토 지점 보완 (R1~R19의 동작 변화 — 기준 코드·문서 `9e262e4`, 완료 2026-10-14)

**계기**: 리팩터링 6차(§8.4.13)가 찾은 "보고만" R1~R19 중 동작이 바뀌는 것은 구현 세션 몫이다. 사용자가 넘겼다(2026-10-14) — 화면에서 사용자가 직접 겪는 것(R1·R2·R6)부터. 결정이 필요한 곳은 그 단계에서 사용자에게 묻는다.

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-13a 화면 오류 표시·응답 코드(R1·R2·R6)** | · R1 광고 만들기: 등록된 소재가 없는데 "등록된 소재 쓰기"로 집행하면 늘 그려지는 "소재" 칸(`creative_source`)에 "등록된 소재가 없습니다. ‘새로 올리기’를 고르세요." — 폼이 `has_creatives` 를 갖고 화면도 그것을 본다(뷰의 같은 값 삭제)<br>· R2 구성 칸 오류를 감싸던 `div`(같은 id)를 빼고 Django 오류 목록 하나만<br>· R6 내 정보·비밀번호 변경도 `console/errors.submit` — 계정 상태 충돌은 409(현재 비밀번호 틀림·규칙 위반은 400 그대로, 잠금 429 그대로). C6 `/me/password` 에 409, 설계 §6.6 원칙 2의 6-13a | **완료 `efe83c4`** — 시험 먼저: 새 `test_choosing_a_registered_creative_without_any_shows_why`, `test_errors_are_shown_next_to_the_fields_and_nothing_is_left_behind` 는 오류 id 가 **한 번**만 있는지, 비밀번호 경쟁 시험 셋(위협 모델 T43 인용, 이름 그대로)은 409 — 지금 코드에서 다섯이 실패함을 확인. 변형 9개 모두 잡음(소재 없음 분기·오류 칸·`has_creatives` 값·템플릿 조건, 감싸개 되돌림·오류 목록 삭제, 비밀번호·내 정보의 응답 코드 고정, 완료 분기 뒤집기). 시험 1,335 → 1,336 |
| **6-13b 서비스 동작(R3·R4·R5·R9)** | · R4 연결과 함께 선택(선택된 소재가 없을 때)도 광고그룹의 `updated_at` 을 올린다 — 명시적 선택과 같은 `_link(…, select)` 한 곳에서, 선택이 바뀔 때만(이미 나가는 소재를 다시 골라도 그대로)<br>· R3 `creative.linked` 감사의 `selected` 는 요청 플래그가 아니라 결과(이 연결 뒤 그 소재가 광고에 나가는지)<br>· R5 같은 요청 키의 다시 보냄은 받은 `now` 기준의 캠페인으로 답한다(`ad_created_by_key(…, now=None)` — `campaign_created_by_key` 와 같은 모양)<br>· R9 `create_ad` 는 역할 검사를 맨 먼저(광고주가 아니면 입력·요청 키와 상관없이 403)<br>· C6 소재 올려 연결·연결의 설명에 `updated_at` | **완료 `5f03306`** — 시험 먼저(`test_creative_library`): 새 `test_a_link_that_also_selects_is_recorded_and_moves_the_seen_time`(명시적·아닌 연결, 새 소재를 올려 연결하는 길, 옛 탭의 이름 바꾸기 409, 감사의 `selected`, 바뀌지 않는 연결은 시각 그대로)·`test_a_repeated_key_answers_with_the_campaign_as_of_the_given_time`(실제 시계로는 끝난 캠페인)·`test_only_an_advertiser_may_create_an_ad_whatever_the_input` — 지금 코드에서 셋 모두 실패함을 확인. 변형 8개 중 6개를 처음에 잡았고, 놓친 둘(반환값의 변경 시각, 이미 나가는 소재를 다시 고를 때 시각을 올림)은 단언을 더해 잡음. 시험 1,336 → 1,339 |
| **6-13c 접근성(R8)** | · 광고 상세의 "이 이미지로 바꾸기" 버튼마다 접근 이름 `이 이미지로 바꾸기: {제목}`(보이는 글을 앞에 — 광고주 화면의 다른 반복 버튼 "삭제"·"끄기/켜기"처럼 제목으로 구별)<br>· 광고 만들기·광고 상세(경로 이름 `ad_create`·`ad_group_*`, 400 으로 다시 그린 화면 포함)는 주 메뉴의 "캠페인"이 현재 위치 [사용자 2026-10-14 — 광고는 캠페인에 속한다] | **완료 `df2442b`** — 시험 먼저: 새 `test_every_advertiser_screen_marks_its_menu`(화면 점검의 광고주 화면 전부 — 현재 위치가 하나이고 그 화면의 메뉴), 이미지 칸 시험에 버튼 이름 — 지금 코드에서 둘 다 실패함을 확인. 변형 4개 모두 잡음. 메모: 운영 화면의 반복 버튼(중단·해제·반려·활성으로·폐기)도 같은 이름이 되풀이된다 — R8 범위(광고주 화면) 밖이라 그대로. 시험 1,339 → 1,340 |
| **6-13d 시험 보강(R11·R12·R13) + R7 결정** | 제품 코드는 그대로.<br>· R11 서로 다른 캠페인에 광고를 겹쳐 만드는 경쟁 시험(광고 상한)<br>· R12 이름과 단언을 맞춤: 광고 만들기의 매체별 묶음, 광고 상세의 입찰 변경 이력(최신부터), 캠페인을 만드는 경쟁 시험의 이름 `…_two_new_campaigns_…`(위협 모델 T2·DRD 인용 함께), 늘 참이던 `test_other_advertisers_unaffected` 의 마지막 단언 → 다른 광고주의 캠페인이 끝나지 않고 고쳐짐<br>· R13 JS 없는 흐름의 새 입찰 40 → 350(3-3 당시 하한 위의 보통 입찰이었는데 6-10c 에서 하한이 100 이 되며 하한 미만 경로가 됐다), 소재 삭제 성공 메시지·이미지 고르기 실패(끝난 캠페인) 메시지, 비공개 함수 `_creative_view` 호출 수 → 소재 연결을 읽은 질의에 실린 캠페인(그 쪽·대기 중인 캠페인뿐)<br>· R7 그대로(위 "보고만" R7) | **완료 `cf6fd98`** — 새 시험 `test_two_new_ads_in_different_campaigns_do_not_pass_the_ad_limit`·`test_a_refused_choice_says_why_and_keeps_the_image`, 이름 바꾼 시험 하나, 단언을 더하거나 바꾼 시험 여섯. 변형 7개 모두 잡음(광고그룹 만들기의 광고주 잠금, 모니터링·재검토 대기가 모든 캠페인의 소재를 읽음 둘, 매체 머리, 이력 순서, 실패 메시지, 삭제 성공 메시지). 같은 커밋의 문서: 위협 모델 T2·DRD 0.49 인용. 시험 1,340 → 1,342 |
| **6-13e 소재 선택 경로 하나(R17)** | [사용자 결정 2026-10-14 — R17 ① C6도 하나로, ② C6 대응 함수 `list_creatives`·`list_ad_groups` 는 그대로] 광고그룹 수정의 `creative_id`(연결된 소재 중에서만 고르던 6-9c 의 길)를 없애고, 고르기는 `link_creative(…, select=True)` 하나(C6 `PUT …/creatives/{creative_id}?select=true` — 아직 연결되지 않았으면 함께 연결, 본 시각은 대조하지 않음). C6·설계 §4 표·§10 "소재 목록"·DRD 0.50 | **완료 `493c144`** — 시험 먼저: `test_only_a_linked_creative_can_be_selected` → `test_a_creative_is_selected_only_through_the_link`(광고그룹 수정은 `creative_id` 를 모르는 필드로 400, 연결만으로는 선택이 그대로, `select=True` 로 선택 — 위협 모델 T43 인용 함께), 수정으로 고르던 시험 넷은 `select=True` 로. 변형(필드 되살리기) 잡음. 시험 수 그대로 1,342 |
| **6-13f 엔진 후보·정책 제약·구성 성격(R18)** | [사용자 결정 2026-10-14 — 셋 모두 정리]<br>· 엔진 `Candidate` 의 `base`·`bid_created_at` 삭제(판정에 쓰지 않았다 — 검사는 하한 ≤ 상한), 그것을 채우던 후보 사실(`CandidateFacts.bid_created_at`, 질의의 하위 질의 하나)도<br>· 정책 `CHECK` 의 `0 < 하한` 을 `하한 ≥ 100`(6-10c)에 합침 — 마이그레이션 `masters/0008`(빈 DB 전제, 6-10 K1)<br>· `create_slot` 의 `audience` 는 기본값 없는 키워드 인자(모델과 같다 — 운영 폼은 늘 넘긴다), 시험·부하 스크립트의 호출 17곳이 값을 넘긴다<br>· 설계 §4.3 후보 표, DRD 0.51, 위협 모델 T28 | **완료 `77db030`** — 시험 먼저: `test_default_is_individual` → `test_the_creator_always_chooses_the_audience`(성격 없이 만들면 `TypeError`), 엔진 시험 도우미·형 검사(하한 > 상한) — 지금 코드에서 실패함을 확인. 변형 둘(엔진의 하한 ≤ 상한 검사, 기본값 되살리기) 잡음. 시험 수 그대로 1,342 |
| **6-13g 스크립트(R19) + 마무리 측정** | · `failure_test` 의 MySQL 준비 대기(`docker exec … mysqladmin ping`)도 스크립트의 `docker()`(시간 제한 180초, R5)로<br>· 정리 루프는 `load_test.stop_processes`(SIGTERM, 30초 뒤 SIGKILL) — 걸린 프로세스가 남은 점검을 건너뛰게 하지 않는다<br>· `mongo_temp_rs` 의 primary 대기 두 벌(처음 띄울 때 60회, 재시작 뒤 120초)을 `wait_primary`(120초) 하나로<br>· 측정: 서빙 질의 수, 150 동시 부하, 장애 시험 | **완료(이 커밋)** — `failure_test.py` processor-kill·relay-kill·mongo-restart 통과(구간 대조 match 12 — mongo-restart 는 바꾼 재시작 대기를 지난다, "No directory" 0, 남은 임시 폴더·컨테이너 0). HEAD `77db030` 에서 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,604 · 과금 1,372, MySQL 1040 은 §9 의 알려진 현상으로 재시도에서 통과). 서빙 질의 수 결정 11 · 반응 40 · 클릭 37 그대로(6-13f 의 후보 질의 변경 뒤 측정) |

**검증**: 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0. 시험 1,335 → 1,336(6-13a) → 1,339(6-13b) → 1,340(6-13c) → 1,342(6-13d), 6-13e·6-13f 그대로. 변형은 6-13a 9·6-13b 8·6-13c 4·6-13d 7·6-13e 1·6-13f 2 모두 잡았다(6-13b 는 처음에 놓친 둘을 단언을 더해 잡음). 결정 요청(사용자 2026-10-14): R7 그대로, R8 현재 메뉴 "캠페인", R17 선택 경로 하나·C6 대응 함수는 그대로, R18 셋 모두 정리. R14·R15 는 §8.4.7 ④ 보류 묶음 그대로.

### 8.4.15 6-14 선출 정책 교체 — 최고가 → 상한 근접 가중 추첨 (기준 코드·문서 `63058aa`, 완료 2026-10-14)

**계기**: 사용자가 운영 전에 선출 로직을 확인했다(2026-10-14). 지금은 최고가(`highest-bid/v1` — 1위 독점, 동점만 무작위)인데, 사용자가 지시했던 방향은 "구성에 하한 이상으로 활성인 광고의 수로 100을 나누고, 상한에 가까울수록 확률이 높고 하한에 가까울수록 낮지만 0은 아니게" 확률로 송출할 광고를 정하는 것이다. 2026-10-07 결정은 "V1·V2는 최고가로 두고 로직만 나중에 갈아끼운다(공식은 열림)"였다(설계 §10 "노출 방식").

**정한 것** [사용자 2026-10-14 — 공식 후보 셋 중 ②, 나머지는 모두 권장안]
- 정책 `weighted-by-bid/v1`: 자격 필터를 통과한 후보마다 가중치 = (상한 − 하한) + k × (적용 금액 − 하한), **k = 2**(상한 광고 3 : 하한 광고 1). 가중치 합 안의 난수 하나로 뽑는다. 정수 계산, 후보는 광고그룹 ID 순.
- **하한 = 상한이면 균등**(가중치 모두 1).
- k 는 정책 파일의 **상수**, 바꾸면 버전을 올린다(`…/v2`).
- **옛 정책 삭제**: `highest_bid.py`(최대값·동점 묶기·동점 추첨, `trace` 의 `tied`·`max_applied_amount`), 최고가·동점 시험. **교체 구조는 남긴다**(`SelectionPolicy`·등록·설정·결정의 `selection_policy` — 등록된 정책은 하나).
- `trace` 는 **요약**: 정책 이름·후보 수·k·가중치 합·뽑힌 가중치·난수·뽑힌 광고그룹.
- 그대로: 자격 필터(상태·기간·하한·예산·잔액), 적용 금액 규칙, 과금(적용 금액 × 반응 비율), 결정 구조, 화면, 계약(C2 의 `selection_policy` 는 값만 바뀐다).

**미리 본 영향**(6-14a 전, 선택 함수만 잠시 새 방식으로 바꿔 전체 시험을 돌리고 되돌림): 1,342개 중 실패는 엔진의 최고가·동점 시험 둘뿐 — 결정·과금·부하 불변식·화면 시험은 누가 뽑히는지에 기대지 않는다. 정책 이름 문자열을 단언하는 시험 몇 개를 함께 고친다.

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-14a 결정·계획** | 설계 §4.3·§10 "노출 방식"·"동점"·§2·§8 Step 6, 이 절·§8 요약·§10, DRD 0.52, Step 1 표(이 계획 §6.3 엔진의 파일·할 일·시험)에 "6-14에서 바뀜, 구현 예정" | **완료 `d254675`** |
| **6-14b 시험 먼저 + 교체** | 새 정책 시험(판정표·균등·하한 > 0·재현·입력 순서·빈도·후보 없음·`subject_id` 무관), 결정 기록 시험(이름·`trace`) — 지금 코드에서 실패함을 확인한 뒤 `engine/policies/weighted_by_bid.py`, 등록·기본 이름·설정 한 줄, `highest_bid.py` 와 그 시험 삭제. 변형 검사 | **완료 `967b19c`** — 시험 먼저: `HighestBidTests`(최고가·동점 일곱) → `WeightedByBidTests` 여덟(가중치가 상한 쪽으로 1 : 2 : 3, 하한 광고도 뽑힘 · 하한 = 상한이면 균등과 반반 빈도 · `trace` 요약의 키와 뽑힌 확률 · 6,000회 빈도가 1/6 · 1/3 · 1/2 · 하한 미만 제외 · 후보 없음 · 시드 재현과 입력 순서 무관 · `subject_id` 무관), 등록 시험의 기본 정책 단언, 결정 기록 시험(정책 이름, 정책 v2 의 가중치 900), 동점 문구의 시나리오 시험 둘(이름 `test_two_advertisers_at_the_same_amount_both_get_picked_reproducibly`) — 지금 코드에서 여덟이 실패함을 확인. 교체: `engine/policies/weighted_by_bid.py`(누적 가중치 + `bisect`), 등록·기본 이름·설정 한 줄, `highest_bid.py` 삭제. 변형 9개 중 8개를 처음에 잡았고, 놓친 하나(난수 범위를 하나 넓혀 첫 후보에 쏠림 — 가중치 합이 작을 때만 드러난다)는 균등 시험에 빈도를 더해 잡음. **뽑히는 광고에 기대는 시험 찾기**: 선택을 "늘 가장 낮은 금액"으로 잠시 바꿔 전체 시험을 돌리고 되돌렸다 — 정책 자체의 시험과 시드를 고정한 시나리오 시험 말고는 `test_bid_and_applied_amounts_are_reported_separately` 하나가 시드 없이 "입찰 800 이 300 을 이긴다"에 기대고 있었다(6-14a 전에 미리 돌렸을 때는 우연히 통과) → 후보가 그 광고 하나가 되게(World 의 광고는 소재 없이). 시험 1,342 → 1,343 |
| **6-14c 측정·완료** | `check.sh`, 서빙 질의 수(11 · 40 · 37 유지 예상), 150 동시 부하, `failure_test.py` processor-kill·relay-kill, 문서 정합 점검, "구현 예정" → 해시 | **완료 `90e1a28`** — HEAD `967b19c` 에서 서빙 질의 수 결정 11 · 반응 40 · 클릭 37 그대로, 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,583 · 과금 1,372), `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, 남은 임시 폴더·컨테이너 0). 문서 정합 점검: 옛 선출 방식(최고가·동점)을 현재형으로 적은 곳 — 설계 §10 "구성별 반응 비율 과금" ⑤에 바뀜 표시, "구현 예정" 표시를 `967b19c` 로. 문서가 인용한 시험 이름 전수 대조(아래 검증) |
| **6-14d 시험 기준 시각 고정** | 이벤트 홉 시험의 내보내기 기준 시각을 고정한다. 시험 데이터는 2026-10-07 고정인데 내보내기는 실제 지금으로 보존 기준(지금 − `EVENTS_OUTBOX_RETENTION_DAYS` 7일)을 잡아, 2026-10-14 00:00 UTC 부터 10-07 창이 대조 제외가 되어 `test_event_hopcheck`·`test_event_hops` 의 시험 9개가 실패했다(4차 체크포인트 검증 중 발견, `dev` 도 같음) | **완료(이 커밋)** — 두 시험의 내보내기 도우미가 `--as-of` 를 따로 받지 않으면 2026-10-10 12:00 UTC(다른 보존 시험과 같은 기준)를 쓴다. 제품 코드는 그대로(운영은 실제 지금이 맞다). 두 파일 65개 통과, 시험 수 그대로 |

**검증**: 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0. 시험 1,342 → 1,343(6-14b). 변형 9개 모두 잡음(하나는 균등 시험에 빈도를 더해). 6-14d 는 시험 수 그대로.

### 8.4.16 6-15 프론트·백 서버 분리 (기준 코드·문서 `90e1a28`, 완료 2026-10-14)

**계기**: 운영 환경(인프라 저장소 `mlo-infra-pr` 의 방화벽)은 프론트 서버만 인터넷(80·443)에 열고, 백 서버는 프론트·Spark·Bastion 에서만, MySQL·MongoDB 는 백 서버에서만 받는다. DB 를 쓰는 광고 서버 Django 는 백 서버에 있어야 하고 사람이 보는 화면은 프론트 서버를 거쳐야 한다. 사용자 지시(2026-10-14): 팀 메타버스(#49)와 같은 앱 분리(B안), 관리 사이트도 공개, 운영 화면도 프론트가 그림, 프론트 앱은 `apps/ads_frontend`. 매체 API 는 공개하지 않고 게임 백엔드가 백 서버로 직접 — 서버 간 통신 경로는 사용자가 인프라에 요청한다.

**정한 것**: 설계 §6.6 "6-15 분리"(나누는 선·프론트가 그리는 화면·통과·URL·화면 데이터·점검표·시험).

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-15a 결정·계획** | 설계 §6.6 "6-15 분리"·규칙 5, §10 "배포 구성"·"정적 파일 서빙"에 바뀜 표시, §2·§8 Step 6, 이 절·§8 요약·§10 | **완료 `22b2d8c`** |
| **6-15b 프론트 골격** | `apps/ads_frontend`(DB 없는 Django): 경로 표(데이터 파일 하나)로 같은 경로·이름, 전달(메서드·경로·본문·`Cookie`·`Content-Type`·CSRF 헤더·`Origin`·`Referer`·`Host`, `X-Forwarded-For` 에 상대 주소를 덧붙임, 시간 제한), 통과(백엔드 응답 그대로 — 홉 헤더 제외), 화면 데이터면 그리기(다음 단계에서 채움), 보안 헤더, 건강 확인, 본문 크기 상한. 프론트 시험 | **완료 `6c9c694`** — `apps/ads_frontend`: `config/settings.py`(환경값 — 운영은 비밀값 50자 이상 필수, `BACKEND_URL` 은 경로 없는 http(s), `ADMIN_URL_PATH` 는 백엔드와 같게, 본문 상한 = 업로드 상한 + 64KiB, 보안 헤더·CSP 는 백엔드와 같은 값, 끄는 배포 점검 넷과 사유), `ui/routes.py`(경로 표 — 콘솔 28·운영 20·관리 사이트 3), `ui/transport.py`(넘기는 헤더 목록, `Host` 그대로, `X-Forwarded-For` 덧붙임, 홉 헤더 제외 통과, `Set-Cookie` 여럿), `ui/views.py`(전달·413·502·매체 API 404·건강 확인), 관리 사이트 정적 파일은 프론트가 서빙. 시험 10개(가짜 백엔드를 실제 HTTP 로: 그대로 전달·덧붙인 주소·정해 둔 헤더만, 업로드 본문 바이트 그대로, 응답·쿠키 여럿·백엔드 CSP 를 덮지 않고 빠진 보안 헤더만 채움, 바이너리·조건부 요청, 매체 API 비공개, 본문 상한, 백엔드 없음 502, 건강 확인, 이름 경로, 관리 사이트 정적 파일). `check.sh` 에 프론트 `check --deploy`·시험·Bandit |
| **6-15c 화면 데이터 — 모든 우리 화면(6-15d 를 합침)** | 백엔드 화면 데이터 모듈(직렬화: 값 객체와 속성·UUID·시각·폼·쪽 나누기·메시지·사용자·CSRF), 광고주 콘솔·로그인·가입·잠금·오류 화면·운영 화면을 화면 데이터로, 템플릿·정적 파일·서식 필터를 프론트로. 백엔드 시험은 프론트 렌더러로 그려 보는 시험 클라이언트로. 분리 전후 화면 비교 | **완료 `f1a1595`** — **6-15d 를 합쳤다**: 운영 화면이 광고주 콘솔의 조각(`_ledger`·`_pager`)을 써서 따로 옮기면 한 단계 동안 같은 템플릿·필터가 두 벌이 된다. 백엔드: `foundation/presentation.py`(`present` — 계층 0 이라 오류 화면·잠금도 쓰고 콘솔은 `foundation.api` 로; 정한 모양 밖은 TypeError, 비밀번호·파일 값 없음, 오류 화면은 CSRF 토큰 없음), 콘솔 뷰 14곳·운영 뷰(관리 사이트 공통 문맥에서 모델 클래스·최근 동작을 뺌)·로그인(`LoginView.render_to_response`)·오류 화면·CSRF 실패·잠금(`AXES_LOCKOUT_CALLABLE`). 프론트로 옮김: 템플릿 29개(광고주 17·운영 11·오류 1), 정적 파일 4개, 서식 필터·그래프 태그(이름표는 `ui/labels.py` 데이터), KST 필터 사본(백엔드 Django admin 이 원본을 쓴다). 백엔드에 남음: 관리자 첫 화면(Django admin) 템플릿과 그 태그 `admin_status`(반응 처리 현황·숫자). 프론트 `ui/rendering.py`(화면 전용 엔진 — 우리 템플릿 + Django admin 템플릿, `RequestContext`, 값 되돌리기, 그리기 전용 폼 — 같은 위젯·속성·입력 종류·값·오류, 쪽 나누기, 메시지), 관리 템플릿의 한국어(`LOCALE_PATHS`). 시험: `tests/presentation.py`(화면 데이터를 실제 프론트 렌더러로 그림)를 `tests/__init__.py` 가 모든 시험의 클라이언트로 — 기존 화면 시험 1,343개가 HTML 단언 그대로 통과, 옮긴 파일을 직접 보던 시험 셋(필터·쪽 나누기, 정적 파일, 디자인 대비)은 프론트 쪽을 보게, 새 `test_frontend_sync`(경로 표·이름표·KST 대조, 정한 모양 밖 값·비밀번호·파일·오류 화면 쿠키) 6개, 프론트 시험 3개(화면 데이터 그리기·쿠키와 CSP, 관리 템플릿 한국어, 413 화면), 위협 모델 대조 시험이 프론트 시험도 본다, 위협 모델 T46·T6. **분리 전후 화면 비교**: 바꾸기 전(HEAD `6c9c694`)과 뒤의 화면 41개(광고주 11·운영 8·익명 2·폼 오류 다시 그리기 14·404·다른 역할·CSRF 실패·로그인 잠금)의 상태·이동·HTML 이 모두 같다(실행마다 바뀌는 UUID·토큰·시각만 정규화). 처음 비교에서 찾은 셋을 고쳤다: 입력 종류(`datetime-local`)를 싣지 않음, 폼 속성 `has_creatives` 를 싣지 않음(`PRESENTED`), 선택 상자·라디오에 입력 종류를 실음. 변형 9개 모두 잡음(경로·관리 경로·이름표·KST·정한 모양·비밀번호 값·오류 화면 쿠키·번역 경로). 시험 1,343 → 1,349, 프론트 10 → 13 |
| ~~6-15d 화면 데이터 — 운영 화면~~ | 6-15c 에 합쳤다(위) | — |
| **6-15e 배포·실행** | 설정(프론트 환경값, 운영 `TRUSTED_PROXY_COUNT=2` 안내, 백엔드 바인딩), 두 서버를 함께 띄우는 실행 방법, `check.sh` 에 프론트 시험, README | **완료 `1a9a891`** — `scripts/run_split.py`(팀의 run-split.py 와 같은 방식: 백엔드 마이그레이션 → 백엔드 127.0.0.1:8000 + 프론트 127.0.0.1:8001, 관리 사이트 경로·업로드 상한은 백엔드 `.env` 에서 받아 프론트에 넘김, 쓰는 포트면 멈춤, Ctrl+C 로 둘 다), 백엔드 README(프론트·백 분리, 실행, 운영 배포의 두 서버 — 프론트 서버 nginx + 프론트 Django, 백 서버 내부망 바인딩·방화벽, `TRUSTED_PROXY_COUNT=2`, 공개 주소·내부 주소의 `ALLOWED_HOSTS`, nginx 업로드 크기), `.env.example`(공개 주소는 프론트, 프록시 2단), 프론트 README(그리는 것·통과·데이터로 갖는 것·실행·운영). **브라우저 점검**(검토 서버 — 프론트 8067·백엔드 8066 을 `run_split.py` 로, 열려 있던 탭의 로그인 그대로): 광고 상세·운영 매체 화면(관리 모양·한국어·사이드바)·관리자 첫 화면(통과)이 그려지고 정적 파일은 프론트, 매체 API 는 프론트에서 404·백엔드에서 200. **찾아 고친 결함**: 입찰 제출이 CSRF 403 — 렌더러의 `RequestContext` 가 늘 붙이는 CSRF 문맥 처리기가 프론트 요청으로 새 토큰을 만들어 백엔드의 토큰을 덮었다(시험은 백엔드 요청으로 그리고 CSRF 검사를 건너뛰어 놓쳤다) → 일반 `Context` 에 요청만 붙임. 다시 막기: 시험 클라이언트가 **프론트처럼 따로 만든 요청**(같은 메서드·경로·질의·이름 경로, 세션·CSRF 상태 없음)으로 그린다, 새 `test_the_token_in_a_drawn_form_passes_the_backends_csrf_check`(CSRF 검사를 켜고 그린 화면의 토큰으로 로그인·입찰 제출), 프론트 시험에 백엔드 토큰 그대로·관리 템플릿의 nonce = 이 응답의 CSP. 이 바꿈으로 화면 비교가 관리 템플릿의 nonce 누락을 찾아(시험용 요청에 CSP 미들웨어가 없음) 백엔드 요청의 nonce 를 옮김 — 화면 41개 다시 모두 같음. 수정 뒤 입찰 제출이 프론트를 거쳐 통과(완료 메시지·새 입찰 350·예상 과금·이력). 로그인은 검토 계정의 비밀번호를 읽는 명령이 자격 증명 보호에 막혀 브라우저로는 확인하지 않았다 — 위 시험이 같은 경로(CSRF 를 켠 로그인)를 본다. 변형 셋(RequestContext 로 되돌림 — 프론트·백엔드 시험 모두, nonce 없음) 잡음. 시험 1,349 → 1,350, 프론트 13 |
| **6-15f 측정·완료** | `check.sh`, 서빙 질의 수, 150 동시 부하, 프론트를 거친 브라우저 점검, 문서 정합 점검·완료 기록 | **완료(이 커밋)** — HEAD `1a9a891` 에서 서빙 질의 수 결정 11 · 반응 40 · 클릭 37 그대로(서빙 경로는 백엔드 그대로), 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,386 · 과금 1,372), `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, 남은 임시 폴더·컨테이너 0). 정합 점검: 새 경계 시험 `test_the_frontend_does_not_import_backend_code`(프론트의 파이썬 파일이 백엔드 패키지를 가져오지 않음 — 일부러 넣은 import 둘을 잡음), 설계 §6.6 "6-15 분리"·§10 "배포 구성"·"정적 파일 서빙"의 "구현 예정" → 해시, 문서가 인용한 시험 이름이 모두 있음(프론트 시험 포함). 시험 1,350 → 1,351 |

**검증**: 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0 — 6-15b 부터 프론트의 `check --deploy`(경고 0)·시험·Bandit 도. 백엔드 시험 1,343 → 1,349(6-15c) → 1,350(6-15e) → 1,351(6-15f), 프론트 시험 10(6-15b) → 13. 분리 전후 화면 41개의 상태·이동·HTML 이 같다(6-15c·6-15e 에서 다시 확인). **남은 것**: 게임 백엔드 → 광고 백엔드의 서버 간 통신 경로(사용자가 인프라에 요청), 프론트·백엔드의 WSGI 서버와 시간 제한(6-5 의 정하지 않은 것과 같음), 다음 체크포인트는 `90e1a28` 뒤부터라 `apps/ads_frontend` 경로를 코드 브랜치에 함께 쌓는다.

### 8.4.17 6-16 결함·DRD 축소·검토 지점 — 리팩터링 7차 점검 후속 (기준 코드·문서 `0e6fa94`, 완료 2026-10-14)

**계기**: 리팩터링 세션이 7차 점검(기준 `977cd5a`)에서 넘긴 요청이다.
- 결함 넷(E1~E4)은 스크래치 사본에서 임시 시험으로 재현했다고 한다.
- DRD 표 축소 후보, 동작 변화·시험 빈 곳 여덟(R20~R27)도 함께 넘겼다.
- 사용자 지시(2026-10-14): 구현 세션이 수용 여부를 판단·계획하고 문서까지 맡는다. DRD 가 과하게 복잡하니 줄일 지점을 다시 검토해 이번 작업에 넣는다.
- 끝나면 리팩터링 세션이 새 HEAD 로 7차(6-17)를 한다.

**확인한 것**(구현 세션, `0e6fa94`):
- **E1:** 실제 시계(`django.utils.timezone.now`)를 앞당겨 전체 시험을 돌렸다. 0일 대조군은 1,351개가 통과했다.
  - +4일(10-18): 1개 실패 — `test_old_image_stays_servable_after_replacement_until_the_campaign_stops`.
  - +25일: 1개 더 — `test_full_flow_through_services_only`.
  - +6년(2032): 7개 더. 캠페인 만들기 폼 시험 넷(`CampaignCreatePageTests`, 고정 날짜 기본값 `fields()` 하나를 같이 씀), 캠페인 수정 둘(`EditTests`), JS 없는 흐름 하나다.
  - 운영 로그 시험 둘(`StampedCommandLinesTests`)도 실패했지만 결함이 아니다. 로그는 돌린 시계로 찍히는데 시험은 실제 시계와 비교해서 생긴 점검 방식의 차이다.
  - 요청서가 짚은 곳보다 넓다(2030 이후 넷이 같은 기본값을 쓴다).
- **E2·E3·E4:** 코드에서 그대로 확인했다.
  - E3 처럼 소재 ID 로 묶는 곳은 그 한 곳(`records/assemble.py`)뿐이다.
  - E4 의 오류 템플릿(`foundation/error.html`)은 제목·문구만 쓴다.
- **R20~R27:** 모두 사실이다.
- **DRD:** 표는 35개다(프로젝트 24 — 권한 M2M 2 포함, 프레임워크 11). 쓰이지 않는 열은 없다.
  - B3·권한 M2M·O8 은 줄일 수 있다. 나머지는 리팩터링 세션 판단과 같다(줄일 수 없음).
  - 문서가 복잡한 큰 원인은 표가 아니라 서술이다. 1,320줄에 `[구현 …]` 표시 118개, 단계 번호 202곳이 있고, "그 전에는…" 같은 변경 이력이 현재 구조 설명과 섞여 있다.
- **O8 을 사용자 행으로 바꿔도 교착이 없다.** 사용자 행을 잠그는 곳(프로필·비밀번호 변경, 비활성화, 관리 사이트 POST 의 요청자·대상)은 모두 그 뒤에 캠페인·소재 행을 잡지 않는다.
  - 그래서 만들기의 **사용자 → 캠페인 → 광고그룹 → 소재** 순서와 엇갈리지 않는다.
  - 로그인의 `last_login` 갱신은 진행 중인 만들기를 잠깐 기다릴 수 있다.

**정한 것**(사용자 2026-10-14):
1. **표 −4.**
   - B3 `billing_campaign_spend` 는 원장에서 계산한다.
   - O8 `campaigns_advertiser_quota` 는 사용자 행 잠금으로 바꾼다.
   - 권한 M2M 둘(`foundation_user_groups`·`foundation_user_user_permissions`)은 사용자 모델에서 Django 권한 믹스인을 빼서 없앤다. 권한은 활성 슈퍼유저만 참이다(지금과 같은 결과).
   - O8 은 리팩터링 세션이 권하지 않았지만(문서화된 잠금 순서 분리 결정을 뒤집음) 사용자가 함께 줄이기로 했다. 설계 §10 "캠페인 행 잠금 규약"을 바꾼다.
2. **DRD 는 현재 구조만 적는다.** 어긋남 ①~⑨를 고치고, `[구현 …]` 표시·단계 번호·변경 이력·지운 A2 표 단면을 본문에서 뺀다. 이력은 §11 문서 이력과 이 계획서가 갖는다.
3. **R23:** 프론트로 옮긴 서식 필터에도 "콘솔에 규칙 없음" 검사를 건다.
4. **시계 점검은 스크립트로 남긴다.** `check.sh` 에는 넣지 않고 측정 단계에서 돌린다.

수용: E1~E4·R20~R27 모두. R27 의 문서는 구현 세션이 고친다.

**마이그레이션**: 세 표를 지우고 원장에 (캠페인, 시각) 색인을 더한다. 지우는 표는 파생값(B3)·값 없는 잠금 행(O8)·늘 빈 표(M2M)라 **데이터 이전이 필요 없다** — 6-10 과 달리 빈 DB 전제가 아니다.

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-16a 결정·계획** | 이 절·§8 요약·§10, 설계 §2·§8·§10(바뀜 표시와 새 결정 "DRD 표 축소"), DRD §4.2 표시·0.53, 위협 모델 T31 ⑧·T44 ① 표시 | **완료 `ce3be44`** |
| **6-16b E1 시계 의존 시험 [급함 — 2026-10-17 12:00 UTC 전]** | 실제 시계에 기대는 시험 9개를 고친다. 이미지 시험은 `World(ends_in=None)`(T33 인용 이름 그대로), Step 1 시나리오는 캠페인 종료를 실제 시계와 상관없게, 캠페인 폼 시험의 날짜 기본값은 실제 시계 기준으로. `scripts/clock_shift_test.py`(시계를 N일 앞당겨 백엔드 시험)로 +4일·+40일·+6년에서 실패 0 | **완료(이 커밋)** — 고치기 전 시계를 앞당기면 +4일 3개·+25일 4개·+6년 11개 실패(그중 둘은 점검 방식 탓). ① 이미지 시험 `World(ends_in=None)`(T33 인용 이름 그대로 — `/assets/` 는 실제 시계로 판정) ② Step 1 시나리오의 캠페인을 무기한으로 ③ 캠페인 만들기·수정·JS 없는 흐름의 종료일 2030-12-31 → 2099-12-31("먼 미래"를 뜻하는 값이라 고정 날짜를 늦춤 — 시험 안의 미래 연도는 이 일곱 곳뿐) ④ 운영 로그 시험은 명령과 같은 앱 시계(`timezone.now`)로 비교(파이썬 시계와 비교해 시계 점검에서만 어긋났다). 새 `scripts/clock_shift_test.py`(`django.utils.timezone.now` 만 앞당겨 전체 시험, `check.sh` 에는 넣지 않음)와 README 안내. 고친 뒤 +4일·+40일·+6년 모두 1,351개 통과, 시험 수 그대로. 커밋 `aa12d31` |
| **6-16c E2 미리보기 500** | 시험 먼저(미리보기 입찰 0 → 200, 오류가 입찰 칸) → `form_errors` import 복구, 기본 규칙과 같은 `pointers` 인자 삭제 | **완료(이 커밋)** — 새 시험 `test_a_preview_with_a_bid_the_service_rejects_is_a_field_error_not_a_500`(입찰 0·−5·2^53 의 미리보기가 200 이고 오류는 입찰 칸, 적용 결과 표 없음)이 지금 코드에서 `NameError` 로 실패함을 확인한 뒤 고침. `pointers={"/bid_amount": "bid_amount"}` 는 기본 규칙(위치의 마지막 조각이 폼 칸이면 그 칸)과 같아 뺐다 — 같은 시험이 입찰 칸 오류를 본다. 시험 1,351 → 1,352. 커밋 `29b1347` |
| **6-16d E3 결정의 `bid_id`** | 시험 먼저(같은 소재를 고른 광고그룹 둘이 한 구성에 있어도 결정의 `bid_id`·`ad.decision` 이 뽑힌 광고그룹의 입찰) → 후보 사실을 광고그룹 ID 로 묶기. 질의 수 그대로 | **완료(이 커밋)** — 새 시험 `test_two_ad_groups_with_the_same_creative_each_record_their_own_bid_row`(같은 소재를 고른 광고그룹 둘, 시드 40개 — 결정의 `bid_id` 와 `ad.decision` 의 `selected.bid_id` 가 뽑힌 광고그룹의 현재 입찰 행, 두 광고그룹 모두 뽑힘)이 지금 코드에서 첫 시드부터 실패함을 확인한 뒤 `records/assemble.py` 가 후보 사실을 광고그룹 ID 로 묶고 `records/services.py` 가 뽑힌 광고그룹으로 꺼낸다(같은 사전, 질의 수 그대로 — `assemble` 의 두 번째 값을 소재로 꺼내던 `test_records_assemble` 도 광고그룹으로). 이미 쌓인 결정·이벤트(개발 DB·검토 DB `ads_review67`)에는 틀린 `bid_id` 가 있을 수 있다 — 개발 DB 는 버려도 된다(6-10 K1), 검토 DB 는 검토가 끝나면 지운다. 시험 1,352 → 1,353. 커밋 `fb9e984` |
| **6-16e E4 오류 화면** | 시험 먼저(오류 화면 뒤에도 메시지가 다음 화면에 남음, 404 에 `Vary: Cookie`·`Set-Cookie` 없음) → 오류 화면은 사용자·메시지를 싣지 않는다 | **완료(이 커밋)** — 새 시험 `test_an_error_screen_leaves_the_session_and_its_messages_alone`(안내 메시지를 남긴 뒤 `/nowhere/`·`/advertiser/nowhere/` 404 → 쿠키 없음, 로그인 확인이 없는 경로는 `Vary: Cookie` 없음, 다음 화면에 메시지 그대로)이 지금 코드에서 실패함을 확인한 뒤, `present` 의 `csrf=False` 를 `session=False`(세션을 건드리지 않는 화면 — 사용자·메시지·CSRF 토큰을 싣지 않음)로 바꿨다. 쓰는 곳은 오류 화면 하나(`error_response`). `/advertiser/` 아래의 404 는 역할 확인 미들웨어가 로그인 여부를 보느라 세션을 읽어 `Vary: Cookie` 가 남는다 — 응답이 쿠키에 따라 달라 맞는 값이다(분리 전과 같음). 설계 §6.6 화면 데이터·위협 모델 T46 ④. 시험 1,353 → 1,354. 커밋 `9fc4734` |
| **6-16f B3 → 원장 계산** | 시험 먼저(기존 소진액 시험을 원장 계산 기준으로 — 예산 일·경계·과금 직후 반영) → `spend_today`·`spend_by_day`·`spend_by_campaign` 을 원장 집계로, 원장 (캠페인, 시각) 색인. `CampaignSpend`·`_add_spend`·`recompute_spend` 명령·`check_ledger` 의 소진액 대조·관리 화면을 지우고, 재계산 경쟁 시험을 정리한다(위협 모델 인용은 먼저 대체). 반응·클릭 질의 수를 다시 재고, 150 동시 부하로 결정 지연과 상한(규모가 크면 파생값으로 되돌림)을 적는다. 설계 §10 "예산 일 경계 구현"·"소진액 재계산 규약"·T31 ⑧ | **완료(이 커밋)** — `billing`: 오늘·일별·캠페인별 소진액을 원장의 과금 줄(받은 것만)을 예산 일로 묶어 한 질의로, 예산 일 SQL 식 `budget_day_expression` 을 `billing/budget_day.py` 한 곳에(퍼널 집계 `records/report.py` 의 같은 식을 옮김), 과금 때의 소진액 갱신·`recompute_spend`(서비스·명령)·`check_ledger` 의 소진액 대조·관리 화면·모델을 지움. 마이그레이션 `billing/0005_spend_from_ledger`(표 삭제, 원장 덮는 색인 (캠페인·종류·시각·금액)). 시험: 재계산 경쟁 시험 9개와 소진액 어긋남 시험을 지우고(위협 모델 인용은 새 시험으로), 남은 정합성 스냅샷 시험 6개는 지갑 대조로 같은 경쟁을 재현하게 `test_ledger_check.py` 로, 새 `test_spend_is_the_ledger_sum_of_each_budget_day`·`test_changing_the_budget_day_offset_needs_no_recompute`. 변형 넷 중 셋 잡음(스냅샷 빼기·하루 끝 빼기·경계 오프셋 빼기 — 놓친 하나는 과금 종류 조건 빼기로, 원장의 캠페인 ID 는 과금 줄에만 있어 결과가 같은 등가 변형). **측정**: 서빙 질의 수 결정 11 · 반응 **36** · 클릭 **36**(전 11 · 40 · 37 — 같은 측정 파일로 바뀌기 전 커밋에서 11 · 40 · 37 을 먼저 확인), 150 동시 부하 검사 52개 통과(소진액 = 원장 검사는 뺌). 결정의 서버 안쪽 비용(단계 G)이 같은 시각 비교로 9.9ms → 16.2ms 로 늘어 원장 색인을 덮는 색인으로 바꿔 12.9ms. 오늘 소진액 조회는 과금 줄 수에 비례(1천 2.8ms · 1만 30ms · 5만 146ms, `Using index`) — **사용자 결정(2026-10-14): 원장 계산을 유지하고, 캠페인 하나의 하루 과금이 1만 줄(결정당 +30ms)을 넘으면 파생값으로 되돌린다**(설계 §10 "DRD 표 축소" ①, 부하 시험 문서 §12). 문서: 설계 §10("예산 일 경계 구현"·"소진액 재계산 규약"·"DRD 표 축소" ①·퍼널 집계·경계 변경 표), 위협 모델 T31 ⑧, 부하 시험 문서 §12·최종 불변식, README(운영 명령 표·장애 시험), DRD B3 표시. 관리 화면 전수 시험의 화면 수 18 → 17. 시험 1,354 → 1,344(재계산 경쟁 9·소진액 어긋남 검사 1 삭제). 커밋 `f4a6800` |
| **6-16g O8 → 사용자 행** | 시험 먼저(상한 경쟁 시험 그대로, 만들기 중 로그인·비밀번호 변경이 교착 없이 끝남) → `foundation.api` 에 광고주 행 잠금, 만들기·이미지 교체가 그것을 먼저 잠금, `AdvertiserQuota` 삭제. 만들기 질의 −1. 설계 §10 "캠페인 행 잠금 규약" | **완료(이 커밋)** — 새 시험 `test_an_account_change_during_a_creation_waits_on_the_advertiser_row_and_both_finish`(캠페인 만들기가 상한을 센 뒤 멈춘 사이 같은 광고주의 프로필 변경 → 사용자 행 잠금에서 기다렸다가 둘 다 오류 없이 끝남)가 지금 코드에서 실패함(기다리지 않음)을 확인한 뒤 `foundation.accounts.lock_user`(사용자 행 `FOR UPDATE`, `foundation.api` 로 공개)를 만들기·이미지 교체 다섯 곳이 가장 먼저 부르고, `AdvertiserQuota` 모델·`_lock_quota` 삭제(마이그레이션 `campaigns/0009_drop_advertiser_quota`). 상한 경쟁 시험 다섯은 그대로 통과. 변형 둘 모두 잡음(잠금 빼기 → 시험 4개 이상, 캠페인 만들기의 잠금 호출 빼기 → 3개). 만들기·이미지 교체마다 질의 −1(잠금 행을 찾던 SELECT — 광고주가 처음 만들 때는 그 행을 만들던 INSERT·저장점도 빠짐). 문서: 설계 §10 "캠페인 행 잠금 규약"·"DRD 표 축소" ②, 위협 모델 T2, 이 계획서 S8, DRD O8 표시. 시험 1,344 → 1,345. 커밋 `7ea74d6` |
| **6-16h 권한 M2M 제거 + R20** | 사용자 모델에서 권한 믹스인을 빼고 `is_superuser`·`has_perm`·`has_module_perms`(활성 슈퍼유저만 참)를 직접 둔다. 관리 화면의 그룹·권한 칸을 정리하고, 쓰기가 열려 있던 그룹 관리 화면의 등록을 푼다(R20). 시험: 관리자만 모델 화면, 그룹 화면 404, 마이그레이션 | **완료(이 커밋)** — 새 시험 `test_the_django_group_admin_is_not_there`(관리자로 그룹 목록·추가 404, 그룹 0개)·`test_permissions_are_the_active_superuser_only`(활성 슈퍼유저만 모델 권한 참, 비활성·광고주는 거짓, 사용자 모델에 그룹·권한 없음)가 지금 코드에서 실패함(그룹 화면 200, 권한 M2M 있음)을 확인한 뒤 사용자 모델에서 `PermissionsMixin` 을 빼고 `is_superuser`·`has_perm`·`has_module_perms`(활성 슈퍼유저만 참 — 전과 같은 결과)를 직접 두고, 관리 사이트에서 Django 그룹 등록을 풀었다. 사용자 관리 화면은 이미 그룹·권한 칸을 쓰지 않았다. 마이그레이션 `foundation/0004_drop_django_permissions`(그룹·사용자 권한 M2M 두 표 삭제 — 늘 비어 있었다). `auth_group`·`auth_permission` 은 Django 인증 앱의 표라 남는다(관리 사이트가 인증 앱을 요구). 위협 모델 T44 ①. 시험 1,345 → 1,347. 커밋 `5f5f2fb` |
| **6-16i 시험 빈 곳·스크립트(R21~R26)** | R21 프론트 시험 설정이 관리 사이트 경로·업로드 상한을 고정 · R22 프론트와 백엔드의 보안 헤더 값 대조 시험 · R23 인라인 금지 검사(T9)에 프론트 템플릿 29개, 규칙 없음 검사에 프론트 서식 필터 · R24 부하 시험의 종료 대기에 강제 종료 대체 · R25 MongoDB 기동 대기를 시간 기준으로, 갈아 끼운 프로세스의 옛 로그 파일 닫기 · R26 상한 시험의 응답 코드 고정 | **완료(이 커밋)** — **R21** 프론트 시험 설정이 관리 사이트 경로(`dev-admin/`)·본문 상한을 고정(재현: `ADMIN_URL_PATH=ops-x/` 로 13개 중 2개 실패 → 고친 뒤 13개 통과). **R22** 새 `test_the_frontend_sends_the_same_security_headers_as_the_backend`(새 프로세스에서 프론트 설정을 읽어 CSP·nosniff·X-Frame-Options·리퍼러·COOP 를 백엔드 설정과 대조, `run_python` 에 작업 폴더 인자). **R23** 인라인 금지 검사(T9)가 프론트 템플릿 29개도 훑고, 새 `test_the_frontend_has_no_rules_either`(콘솔 규칙 없음 검사를 프론트 파일에 — 옮긴 서식 필터 포함), 규칙 원본 한 곳 검사(T32)도 프론트 파일을 본다. **R24** 부하 시험의 종료 대기 세 곳이 `stop_process`(SIGTERM → 30초 → SIGKILL, 종료 코드를 돌려줌 — 강제 종료 뒤 회수까지)를 쓴다. **R25** MongoDB 기동 대기를 60초 기한으로(전에는 60번 × 시도마다 docker 시간 제한 120초), 장애 시험이 갈아 끼운 상시 프로세스의 옛 로그 파일을 닫는다. **R26** 광고 상한 시험을 409 로 고정. 변형 넷 모두 잡음(프론트 헤더 값·프론트 템플릿 인라인 스타일·프론트 필터의 `django.db`·프론트의 상한 계산). 위협 모델 T9·T32·T46. 시험 1,347 → 1,349. 커밋 `e5a8159` |
| **6-16j DRD 정리 + R27** | DRD: 표 −4 반영, 어긋남 ①~⑨, 현재 구조만(이력은 §11), P2 반응을 열 표로. R27: 설계 §10 "반응 처리 현황 노출"의 태그 위치·"정적 파일 서빙"의 시험 설명, 이 계획서의 `update_ad_group(creative_id)` 없어짐 표시, `check.sh` 주석, 백엔드 README 의 분리 전 서술, 프론트 `.env.example` 의 `ASSET_MAX_BYTES` | **완료(이 커밋)** — **DRD 0.54**: 본문을 지금 구조만 적도록 다시 씀(`[구현 …]` 표시·단계 번호·변경 이력·지운 A2 단면·§4.8 PK 적용 기록·해결된 D-1~D-6·D-8 상세를 빼고 §11 문서 이력에 — 본문의 구현 표시 111 → 0, 단계 번호 158 → 0(남은 것은 설계서 절 이름), 커밋 해시 23 → 0. 본문 길이는 거의 같다(1,264 → 1,263줄, 76,641 → 72,391자) — 뺀 이력만큼 빠져 있던 내용(반응·outbox ERD, P2 열 표, 프레임워크 표, 수명주기 행)을 채웠다). 표 −4 반영(B3·O8·권한 M2M — 프로젝트 표 24 → 20), 어긋남 ①~⑨(① 목록에 O9 ② ERD 에 반응·outbox ③ P2 를 열 표로 ④ 프레임워크 표 11개와 쓰는지 — 쓰지 않는 5개 ⑤ O3 의 과금 단위 말 ⑥ O4 `image_bytes` 는 현재 이미지 크기 ⑦ 추가 전용 목록에 O7·O9·M5 ⑧ 결정 순서도의 "(계획)"·"(P1)" ⑨ 수명주기에 매체 키·광고그룹-슬롯·연결·이미지 보유·세션·로그인 잠금 기록), §2 를 프론트·백 분리에 맞춤, 반응 상태도·C3 공개 조건(O9·광고주 활성)·§5.5 소재 사건. ⑦ 의 시험: 추가 전용 전수 시험에 O7·M5 를 더하고 `test_every_append_only_model_is_covered_here`(모든 `AppendOnlyModel` 하위 모델 = 시험 목록, 변형으로 확인)로 바꿈. **R27**: 설계 §10 "반응 처리 현황 노출"의 태그 위치(`admin_status.py`)·"정적 파일 서빙"과 §9 의 `test_static_serving` 설명(6-15c 뒤 관리자 것만), 이 계획서의 `update_ad_group(creative_id)` 에 6-13e 없어짐 표시, `check.sh` 주석(DB 실패 때 멈춤), 백엔드 README 정적 파일(콘솔 것은 프론트), 프론트 `.env.example` 의 `ASSET_MAX_BYTES`. DRD 가 인용한 시험 이름 39개 모두 있음. 커밋 `440e7a9` |
| **6-16k 측정·완료** | `check.sh`, 서빙 질의 수, 150 동시 부하, `failure_test.py` processor-kill·relay-kill, 시계 점검(+4일·+40일·+6년), 문서 정합 점검·완료 기록 | **완료 `82b0dcf`** — HEAD `440e7a9` 에서 서빙 질의 수 결정 11 · 반응 **36** · 클릭 **36**(6-16f 에서 40 · 37 → 36 · 36, 그 뒤 그대로), 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,554 · 과금 1,372, 결정의 서버 안쪽 비용 11.9ms), `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, 남은 임시 폴더·컨테이너 0), 시계 점검 +4일·+40일·+6년 모두 1,349개 통과. 정합 점검: 설계서·위협 모델·부하 시험 문서·DRD 가 인용한 시험 이름 559개가 모두 있음, 지운 표·명령(`CampaignSpend`·`recompute_spend`·`AdvertiserQuota`)을 현재형으로 적은 곳 없음(남은 것은 모두 6-16 바뀜 표시가 붙은 지난 기록) — **이 점검은 틀렸다**: 이름을 검색해 같은 줄의 표시만 봐서, 이름 없이 쓴 서술(설계 §4.7 두 곳·`charge_for_reaction` 설명)과 표시 없는 이 계획서 §6.5 다섯 곳을 놓쳤다(6-16l 에서 고침). 설계 §2·§8 Step 6·§10 "DRD 표 축소"·부하 시험 문서 §12, 이 절·§8 요약·§10 |
| **6-16l 실제 검토 후속** | 검토 서버(HEAD `82b0dcf`, 백엔드·프론트 분리 실행)에서 광고 6개(광고주 셋, 하한 미만·상한 초과 포함)로 확률 선출·예산 소진·클릭 과금을 직접 확인하고 찾은 둘을 고친다: ① 낡은 소진액 서술 ② 고른 소재 표시 "나가는 중" | **완료 `f63ecff`** — 확인: 확률 구성(하한 100 · 상한 500) 결정 3,000건이 가중치 30·25·20·15·10% 와 맞음(χ² 6.94, 자유도 4, 0.05 임계값 9.49), 균등 구성(300 · 300) 3,000건이 셋 1/3 씩(χ² 0.49), 하한 미만 광고 0건, 결정의 `bid_id` 가 뽑힌 광고그룹의 입찰 행이 아닌 것 0건. 예산 600 캠페인에 노출 1건(392) → 남은 208 이 두 구성의 적용 금액보다 작아 `budget_exhausted` 로 빠지고 나머지가 가중치대로 다시 나뉨(χ² 2.38 · 0.67). 소진 전에 한 결정의 노출은 그대로 과금돼 1,078/600(일예산은 소프트 한도, 설계 §4.4) — 광고주 화면은 남은 예산 0 과 알림. 클릭 주소는 프론트를 거쳐 302, 같은 클릭 두 번째는 합쳐짐. ① `charge_for_reaction` 설명의 "③ 그날 소진액", 설계 §4.7 두 곳(파생값·재계산 명령, 과금 트랜잭션의 ③), 이 계획서 §6.5 다섯 곳에 6-16f 바뀜 표시, 위 6-16k 정합 점검 기록 정정, 시험 이름 `test_charge_updates_campaign_spend_but_not_for_shortfall` → `test_campaign_spend_counts_what_was_charged_not_the_shortfall` ② 소재 목록·소재 상세·광고 상세·운영 모니터링의 "나가는 중" → "선택됨"(광고가 고른 소재라는 뜻이라 꺼진 광고·하한 미만·예산 소진에도 붙었다. 실제로 나가는지는 광고 상세의 "노출 가능 n곳"·알림이 보여 준다). 시험 먼저: 표시 시험 3개를 "선택됨"으로 바꿔 지금 템플릿에서 실패를 확인한 뒤 바꿈. 시험 수 그대로 |

**순서**: E1 이 급하므로 맨 앞이다(2026-10-17 12:00 UTC = KST 21:00 부터 `check.sh` 실패).
- 그다음은 결함 → 표 축소 → 시험 빈 곳 → DRD 정리 → 측정 순서다.
- DRD 정리는 표 축소를 반영해야 해서 뒤에 둔다.
- 결정이 더 필요하면 그 단계에서 묻는다.

**바뀐 기준선**:
- 서빙 질의 수: 결정 11 · 반응 36 · 클릭 36(전 11 · 40 · 37). 결정은 오늘 소진액을 원장에서 1질의로 합산한다(그날 과금 줄 수에 비례 — 상한 하루 1만 줄, 설계 §10 "DRD 표 축소" ①).
- 만들기·이미지 교체 질의 −1(6-16g).
- 프로젝트 표 24 → 20, 시험 1,351 → 1,349(새로 쓴 시험 11개, 지운 시험 13개 — 재계산 경쟁 9·소진액 어긋남 검사 1·같은 자리를 새 시험으로 바꿔 쓴 3).

**검증**: 단계마다 `check.sh`(`DB_NAME=ads_impl`) 종료 코드 0. 시험 먼저 단계(6-16c·d·e·g·h, 6-16b 는 시계 점검)는 지금 코드에서 실패를 먼저 확인했고, 변형 검사는 6-16f 셋/넷(놓친 하나는 등가)·6-16g 둘·6-16i 넷·6-16j 하나를 모두 잡았다.

**남은 것**: 리팩터링 세션이 새 HEAD 로 7차(6-17)를 한다. 검토 DB(`ads_review67`)에는 6-16d 전에 쌓인 틀린 `bid_id` 결정이 있을 수 있다 — 검토가 끝나면 지운다. 운영하면서 할 것(§8.4.4)과 6-5 의 정하지 않은 것(§8.4.6), 서버 간 통신 경로(6-15)는 그대로.

### 8.4.18 6-17 코드 정리 (리팩터링 7차 — 시험 코드 포함, 기준 코드·문서 `f63ecff`, 완료 2026-10-14)

**무엇**: 6-13~6-16(검토 지점 보완, 선출 정책 교체, 프론트·백 분리, 결함·DRD 축소) 뒤의 제품 코드와 **시험 코드**를 정리한다. 기능을 더하거나 빼지 않고 동작도 바꾸지 않는다 — 응답 코드, 그린 화면의 HTML, DB 쓰기, 잠금 대상과 순서, 질의 수, 감사 기록, 이벤트가 그대로다. 계약·설계 결정은 바뀌지 않는다.
- 후보는 리팩터링 세션이 7차 점검(기준 `977cd5a`, ponytail-audit — 프론트·백 분리, L3·L4, L0~L2와 scripts, 시험)에서 찾은 것이다. 그중 6-16 이 처리하지 않은 것을 새 HEAD `f63ecff` 에서 다시 확인했고, 6-16 이 바꾼 곳을 더 훑었다.
- 6-16 이 처리해 빠진 후보: 인라인 금지 검사의 프론트 템플릿(6-16i R23), 미리보기의 `pointers=` 인자(6-16c), 재계산 경쟁 시험의 도우미 `interleaved_check`(6-16f 에서 파일째 없어짐).

**정한 것** [2026-10-14 — 사용자: 결함·DRD 축소·동작 변화는 구현 세션이 먼저(6-16), 리팩터링은 그 뒤 새 HEAD 로. 진행은 리팩터링 세션에 맡김]
- 문서는 이번에도 리팩터링 세션이 고친다(6-12 D-4 와 같다): 이 절·§8 요약·§10, 시험을 지우거나 합치기 **전에** 인용 대체, 이 계획의 낡은 표에 "6-N에서 바뀜" 표시, 설계 §2·§8 Step 6.
- 백엔드가 오류 화면 데이터에 싣는 `status` 는 뺀다. 프론트 오류 템플릿(`foundation/error.html`)은 제목·문구만 읽는다. 응답의 HTTP 상태는 그대로이고, 백엔드의 화면 데이터는 프론트만 받는다(설계 §6.6).

**시험을 지우는 기준**: 6-6·6-12 와 같다.
- 지울 시험이 잡는 결함을 제품 코드 변형으로 만든다. **남는 시험이 같은 변형을 잡는지** HEAD 사본에서 돌린다. 못 잡으면 지우지 않고 단언을 옮기거나 남긴다.
- 제품 코드를 바꾸는 단계(6-17d·6-17e)는 바꿀 곳을 지키는 시험이 있는지 변형으로 먼저 본다. 없으면 단언을 먼저 더한다(6-17b).

**단계** (한 단계 = 한 커밋, `check.sh`(`DB_NAME=ads_refactor7`))

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-17a 문서: 결정·계획** | 이 절·§8 요약·§10, 6-16l 해시, 설계 §2·§8 Step 6 | `3d807a2` |
| **6-17b 시험 먼저** | 아래 "시험 먼저" | **완료 `129277f`** — 같은 변형 넷을 HEAD 사본(지금 시험)과 강화한 사본에 넣었다. 넷 모두 지금 시험은 놓치고 강화한 시험은 잡았다: 프론트 쪽 나누기의 다음 쪽 번호, 화면 데이터가 사용자 이름을 싣지 않음(운영·화면 점검·JS 없는 흐름 등 시험 모듈 8개가 모두 통과하던 것), 창이 시작하면 닫힌다고 봄, 후보 사실이 입찰 없는 광고그룹을 거르지 않음. 새 시험 `test_the_operator_header_names_the_signed_in_admin`, 나머지 셋은 이름 그대로. 시험 1,349 → 1,350 |
| **6-17c 시험 정리** | 아래 "시험" | **완료 `a503ba1`** — 폐기 3·합치기 3 전에 변형으로 확인(옛 시험은 임시 파일로 옮겨 남는 시험과 따로 돌림). 지울 시험이 잡는 변형 7개를 남는 시험이 모두 잡았다: 하한 미만을 하한으로 후보, 첫 후보만 남김, 넘긴 난수 무시, 결정 이벤트의 입찰·적용 금액 뒤바꿈 둘(기록·스키마), 이미지 응답이 세션을 읽음·`Vary: Cookie`. 지울 시험은 못 잡고 남는 시험만 잡은 것 둘 — 광고 만들기의 역할 검사 빼기(다른 검사가 먼저 403), 이미지 응답이 쿠키를 심음(옛 시험은 `headers` 만 봤다). 프론트 413: 상한 경계·화면 문구 변형을 합친 하나가 모두 잡음(위협 모델 T46 이 인용한 옛 시험은 문구를 못 잡았다). 인용: T46·T41 이 인용한 이름에 합쳤고, 이 계획 §5 의 `test_no_set_cookie_header` 에 합침 표시. 시험 1,350 → 1,345, 프론트 13 → 12, 시험 코드 −74줄 |
| **6-17d L0~L2·scripts** | 아래 "L0~L2·scripts" | **완료 `9dcbb5e`** — 소진액·지갑 소진 질의 넷의 SQL 이 바꾸기 전후로 같다(같은 인자로 캡처해 비교). 바꾼 뒤 변형 7개 모두 지금 시험이 잡음: 오늘 소진액이 이틀·어제부터, 소진액 부호, 캠페인으로 거르지 않음, 일별 묶음을 캠페인으로, 지갑 소진이 지갑으로 거르지 않음, 광고 요청 키 형식 검사 빼기. 스크립트는 `check.sh` 의 20 동시 부하와 6-17f 의 150 동시 부하·장애 시험으로 본다. 제품 코드 −5줄(소진액 docstring 이 하나로 모임), 시험 1,345 그대로 |
| **6-17e L3·L4·프론트** | 아래 "L3·L4·프론트". 바뀐 화면의 HTML 을 바꾸기 전후로 비교 | **완료 `e28743f`** — 바꾸기 전후로 같은 순서의 요청 70개를 HEAD 사본과 바꾼 사본에서 보내 비교했다. 화면 점검 시험의 준비 데이터와 화면 목록(광고주·운영·관리 사이트 전부)에, 운영 광고주 목록의 쪽 나누기 세 쪽(1·2·범위 밖), 404 둘(광고주·익명), 역할 밖 경로, 로그아웃과 그 뒤, 로그인 잠금을 더했다. 상태·이동·HTML 이 70개 모두 같다(무작위 값 — UUID·CSRF·요청 키·CSP nonce·시각·axes 순번·비밀번호 해시 요약 — 을 맞춘 뒤). 바꾸기 전 기준선을 두 번 찍어 같음을 먼저 확인했다. 프론트가 직접 그리는 413·502 화면도 전후 같음. 쪽 나누기와 머리글 이름은 6-17b 의 강화한 시험이 지킨다. 함께: 화면 점검 시험 준비의 그룹 한 줄(6-16h 뒤 그룹 관리 화면이 없다). 제품 코드 −19줄·파일 −1(프론트 `ui/apps.py`), 시험 1,345 그대로 |
| **6-17f 마무리** | `check.sh`, 150 동시 부하, `failure_test.py` processor-kill·relay-kill, 서빙 질의 수(결정 11 · 반응 36 · 클릭 36), 문서 정합 점검·완료 기록 | **완료(이 커밋)** — HEAD `e28743f` 에서 서빙 질의 수 결정 11 · 반응 36 · 클릭 36 그대로(같은 측정 파일로 기준 `f63ecff` 에서도 11 · 36 · 36). 150 동시 부하 검사 52개 모두 충족(저장 행 결정 1,415 · 반응 2,427 · 과금 1,372, 결정의 서버 안쪽 비용 11.8ms, MySQL 1040 은 §9 의 알려진 현상으로 재시도에서 통과). `failure_test.py` processor-kill·relay-kill 통과(구간 대조 match 12, 남은 임시 폴더·컨테이너 0). 정합 점검: 설계서·위협 모델·부하 시험 문서·DRD 가 인용한 시험 이름 520개가 모두 있음, 지우거나 합친 시험·코드 이름은 이 계획의 지난 기록(6-14b 행)·이 절·합침 표시를 한 §5 에만 남음. 설계 §2·§8 Step 6 의 6-17 완료 |

**시험 먼저**(6-17b) — 리팩터링이 지날 곳, 이름과 다른 것을 보는 시험
- 쪽 나누기 시험(`test_console_frame::test_pager_keeps_other_query_values`)이 Django `Page` 로 그린다. 실제 경로인 화면 데이터(`$page`)와 프론트 `DisplayPage` 로 그리게 한다(6-17e 가 `DisplayPage` 를 줄이기 전에).
- 운영 화면 머리글의 로그인한 관리자 이름을 보는 시험이 없다. 화면 데이터의 사용자(`presentation._user`)를 줄이기(6-17e) 전에 단언을 더한다.
- `test_event_hops::test_open_windows_are_not_summarized_but_listed` 는 6-14d 뒤 다른 이유로 통과한다. 결정은 실제 지금인데 내보내기 기준 시각(`--as-of`)은 2026-10-10 이라, 그 결정은 "아직 열린 창"이 아니라 "범위 밖"이다. 결정을 기준 시각의 창에 둔다.
- `test_campaigns_services` 의 후보 사실 시험은 입찰 없는 광고그룹이 "소재가 있어도 빠진다"고 적었다. 그런데 그 광고그룹에는 소재가 없다. 소재를 연결해 이름대로 본다.

**시험**(6-17c, 백엔드 약 −5 · 프론트 −1)
- 폐기(변형 검사를 통과할 때만):
  - `test_engine_policies::test_below_floor_bid_never_beats_an_eligible_one` — 하한 미만 제외는 필터·결정 시험이 본다.
  - `test_campaigns_services::CreateAdTests::test_only_an_advertiser` — 6-13b 의 `test_only_an_advertiser_may_create_an_ad_whatever_the_input` 가 포함한다.
  - `test_records_decision::test_two_advertisers_at_the_same_amount_both_get_picked_reproducibly` — 동점 시절의 준비가 남았다. 둘 다 뽑히는 것은 6-16d 시험이, 시드 재현은 정책 시험이 본다.
- 합치기:
  - `test_bid_and_applied_amounts_are_reported_separately` → 결정 이벤트 전체 비교(`test_one_event_per_decision_matching_the_stored_snapshot`)를 상한을 넘는 입찰로.
  - `test_assets_serving::test_no_set_cookie_header` → 계약 시험 `test_no_cookie_is_set_and_no_auth_is_required`(T33)에 `Vary: Cookie` 단언. 이 계획 §5 의 인용에 "6-17c 에서 합침" 표시.
  - 프론트의 413 시험 둘 → 하나.
- 죽은 것·낡은 것:
  - 쓰이지 않는 도우미 `keyed`(`test_event_hops`).
  - pyflakes 가 찾은 쓰지 않는 지역 변수 여섯·자리표시 없는 f-string 하나·쓰지 않는 import(`test_frontend_sync` 의 `rendering`).
  - `setUp` 의 `self.client = Client()` 11곳. Django 가 시험마다 같은 클라이언트(시험 설정의 `PresentationClient`)를 새로 만든다.
  - `test_slot_audience` 의 여분 `World()`.
  - `test_ledger_check` 의 함수 안 import 넷.
  - `test_screens_quality` docstring 의 CSS 경로(6-15 뒤 프론트).

**L0~L2·scripts**(6-17d)
- billing:
  - 소진액 세 함수가 같은 집계를 되풀이한다 → 묶는 열만 다른 도우미 하나. 오늘 소진액은 그날 하루의 캠페인별 소진액이다(같은 SQL, 질의 1).
  - `_charged_on(day, **scope)` 는 6-16f 뒤 지갑 하나만 쓴다.
- 값이 같은 것을 한 벌로: `engine/registry.DEFAULT_POLICY = WeightedByBid.name`, `assets.ALLOWED_FORMATS = tuple(FORMAT_INFO)`.
- `campaigns.ad_created_by_key` 를 짝(`campaign_created_by_key`)과 같은 한 줄 모양으로.
- `records/assemble.py` docstring 의 질의 목록. 정책은 질의 없이 `slot` 에 있다.
- scripts:
  - `load_test.py` 의 쓰지 않는 `signal` import(6-16i 뒤), `stop_relays` 감싸개 → lambda.
  - `failure_test.py` 의 `send_signal(SIGKILL)` → `kill()`.
  - `mongo_admin.py` 의 오류 문구 → `events.mongo.error_text`(같은 모양을 직접 만든다).

**L3·L4·프론트**(6-17e)
- 몸통 없는 `ConsoleLogoutView` → `LogoutView`.
- 호출자 하나뿐인 `operator/views._site_context` → `_render` 안으로.
- `console/errors.form_errors` 의 반복 변수가 모듈의 `messages` import 를 가린다 → 이름만 바꾼다.
- 화면 데이터:
  - `presentation._user` 의 `get_short_name` 분기는 늘 거짓이다. 사용자 모델에 그 메서드가 없다.
  - `None` 분기와 낡은 주석: 6-16e 뒤 사용자를 싣는 화면은 모두 인증 미들웨어 뒤이고, 본문 크기 오류는 오류 화면(세션 없음)이다.
  - 오류 화면 문맥의 `status`(위 "정한 것"), 프론트 `error_page` 의 `status`·`user`·`messages`.
  - 쪽 나누기의 `count`·`object_list`. 템플릿이 읽지 않는다.
- 프론트:
  - `ui/apps.py` 삭제. 이름만 있는 앱 설정이라 Django 기본과 같다.
  - `settings.env()` 한 줄.
- 시험 클라이언트(`tests/presentation.py`)의 쓰이지 않는 `.presentation` 과 `Context` 감싸기.

**검증**(리팩터링 세션)
- 단계마다 `check.sh`(`DB_NAME=ads_refactor7`) 종료 코드 0 — `check --deploy` 경고 0, 마이그레이션 최신, 20 동시 부하·불변식, 프론트 `check --deploy`·시험, `pip-audit`·`bandit`.
- 시험 1,349 → 1,350(6-17b) → 1,345(6-17c), 프론트 13 → 12. 전체 시험 약 130초.
- 줄 수(`f63ecff` → `e28743f`): 시험 코드 −69, scripts −5, 제품 코드 −19(파일 −1).
- 변형 검사(HEAD 사본): 6-17b 넷(지금 시험은 놓치고 강화한 시험은 잡음), 6-17c 백엔드 열·프론트 둘, 6-17d 일곱. 6-17d 는 소진액 SQL 을 캡처해 비교했고, 6-17e 는 화면 70개를 비교했다.
- 메모: 기준선 `check.sh` 를 처음 돌릴 때 이 세션의 DB(`ads_refactor7`)가 아직 없어 DB 를 쓰는 단계 셋(`check --deploy`·마이그레이션 검사·배포 점검 시험)이 실패했다. 만든 뒤 다시 돌려 통과했다(코드 문제 아님).

**정리하지 않는 것**
- 6-13a 가 일부러 만든 폼 속성 싣기(`PRESENTED`).
- 프론트 보안 설정 넷: 백엔드와 같은 값을 명시하고, 6-16i 시험이 대조한다.
- 의도한 사본: 경로 표·이름표·KST, 설계 §6.6.
- 백엔드 WhiteNoise(설계 결정)와 `status_of`(설계가 인용).
- `test_ledger_check` 의 격리 수준 시험 셋은 겹쳐 보이지만, 각각 다른 검토(DB-1c·`6fc9664`·`f2e930b`)의 재현이라 남긴다.
- 이전 차수에서 남긴 것: §8.2.4·§8.3.4·§8.4.5·§8.4.7·§8.4.13.

**보고만**(구현 세션 몫 — 리팩터링 세션이 6-17c 변형 검사 중 발견, 2026-10-14)
- R28 결정 후보 조립(`records/assemble.py`)이 잔액·오늘 소진액을 후보마다 **그 광고주·그 캠페인의 값**으로 넣는지 보는 시험이 없다.
  - 변형 둘을 전체 백엔드 시험이 잡지 못했다: 모든 후보가 첫 후보 광고주의 잔액을 쓴다, 모든 후보가 첫 후보 캠페인의 소진액을 쓴다.
  - 6-17c 에서 지운 `test_two_advertisers_at_the_same_amount_both_get_picked_reproducibly` 도 이것을 못 잡았다(두 광고주 모두 잔액·예산이 넉넉하다).
  - 필요한 시험: 광고주 둘의 후보가 한 구성에 있고 한쪽만 잔액 부족(또는 예산 소진)일 때 그쪽만 빠진다. → **6-18b 에서 더함**(`test_each_candidate_carries_its_own_advertisers_balance_and_campaigns_budget`, §8.4.19)

### 8.4.19 6-18 시험 축소와 운영·개발 분리 (기준 코드·문서 `e803cc5`)

**무엇**: 운영을 목적으로 시험과 개발 도구를 다시 나눈다.
- 백엔드 시험 1,345개(97파일·306클래스, 약 125초)를 **운영용 300개 이하**와 **개발용 약 40개**로 줄인다. 프론트 12개는 그대로다.
- 개발 문서·계약 파일·코드 구조와 대조하는 시험과 시험 도구 자체의 시험은 개발용으로 뺀다.
- 개발 도구(`scripts/` 13개·`docker/innodb-cluster/`)와 시험을 `tests/` 아래로 모은다 — **`tests/` 밖은 운영 코드**다.
- 배포된 환경에서 돌리는 운영 점검 명령(`ops_check`)을 새로 둔다.
- 제품 동작·계약·설계 결정은 바뀌지 않는다. 점검 명령을 더하는 것만 예외다.

**정한 것** [2026-10-14, 사용자 — 설계 §10 "시험 구성"]
- 개수 기준(서버당 최대 500·권장 300): **운영용 ≤ 300**, 백엔드 합계(운영용 + 개발용) **≤ 500**. 개발용은 개발 중(`check.sh`)에만 돈다.
- 운영용 = 제품 동작(돈·보안·데이터 정합·동시성·계약에 보이는 동작·화면). 개발용 = 개발 문서·계약 파일·코드 구조와의 대조, 시험 도구의 시험.
- "운영용 시험"은 지금 시험에서 나누고, **배포 후 점검 명령**을 더한다.
- 개발 도구와 시험은 `tests/` 아래 전부.
- 줄이는 방식은 **합치기 위주 + 측정**: 한 규칙 = 시험 하나(경우는 `subTest`). 지우는 것은 다른 시험이 같은 결함을 잡는다고 측정으로 확인된 것만.

**지금**(기준 `e803cc5`)과 목표

| 묶음 | 시험 | 파일 | 목표 |
|---|---|---|---|
| 반응 판정·퍼널 | 204 | 9 | 45 |
| 이벤트·정합(manifest·백필·중계) | 207 | 11 | 40 |
| 화면(광고주·운영) | 201 | 16 | 45 |
| 계정·보안·설정(운영 점검 명령 포함) | 161 | 14 | 40 |
| 캠페인·소재 | 154 | 9 | 40 |
| 매체 API | 87 | 4 | 25 |
| engine·선출 | 52 | 5 | 20 |
| 과금·원장 · 마스터·매체 키 · 이미지 · 시나리오 | 44 · 48 · 51 · 1 | 11 | 45 |
| **운영용** | **1,210** | 79 | **≤ 300** |
| 개발용: 문서·계약 대조 · 코드 구조 규칙 · 시험 도구의 시험 | 43 · 38 · 54 | 18 | 약 40 |

- 개발용 파일: 문서·계약 대조 — `boundaries/test_threat_model_sync`·`test_contract_files`·`test_contract_framework`·`test_contract_provider_assets`·`test_console_contract_rules`. 코드 구조 — `boundaries/test_layers`·`test_judgment_scope`·`test_console_rules`·`test_model_conventions`·`test_single_source_rules`, `test_frontend_sync`. **[6-18c 에서 정정]** `test_service_input_contracts`(서비스 입력 검사의 종류·위치·순서)·`test_append_only_all_models`(추가 전용 모델을 덮어쓸 수 없음)는 제품 동작이라 운영용이다. 시험 도구 — `test_load_invariants`·`test_event_invariants`·`test_mysql_admin`·`test_cluster_check_script`·`test_docker_cli`.
- 섞인 파일은 6-18e 에서 나눈다: `test_http_security`(운영용)의 템플릿 인라인 금지 검사(T9)는 개발용으로, `test_frontend_sync`(개발용)의 CSRF·화면 데이터 시험은 운영용으로.
- 문서가 인용하는 지금 시험: 위협 모델 508 · DRD 39 · 설계 11 · 부하 시험 문서 1.

**폴더**
```
apps/ads_server/
  manage.py · requirements.txt · config/ · foundation/ … serving_api/   운영 코드
  tests/
    ops/       운영용 시험(≤ 300)    manage.py test tests.ops
    dev/       개발용 시험(약 40)    manage.py test tests.dev
    support/   공용 도우미(factories·helpers·concurrency·contract_support·presentation …), 시험용 URL(urls_*)·앱(support_app)
    tools/     지금 scripts/ 13개(check.sh·load_test·failure_test·cluster_check·mysql_cluster·mongo_temp_rs·clock_shift_test·run_split …)
    docker/    innodb-cluster/
```
- 예외: 시험·개발 설정(`config/settings/test.py`·`dev.py`)은 설정 모듈 한곳에 둔다(`manage.py` 가 고른다).
- `requirements.txt` 는 한 파일로 두고(사용자 규칙 — 쓰는 라이브러리는 모두 이 파일) **"운영"·"개발·시험" 두 묶음**으로 나눈다. 개발·시험: pip-audit·bandit·packaging·PyYAML·jsonschema·openapi-spec-validator·rfc3339-validator·rfc3986-validator, 6-18b 의 coverage. 제품 코드는 이 여덟을 import 하지 않는다.
- `check.sh` 는 `tests/tools/check.sh` 다. 운영용·개발용을 따로 돌리고 개수를 보인다.

**운영 점검 명령**(`manage.py ops_check`, 새로)
- 배포된 백엔드에서 **읽기만** 하고, 하나라도 실패하면 종료 코드 1. 4층(`console` 의 관리 명령)에 두어 각 모듈의 `api` 를 부른다. `/api/media/v1/health` 는 지금처럼 살아 있는지만 답한다.
- 점검: ① 배포 설정(`check --deploy` 와 같은 시스템 점검) ② MySQL 접속·적용 안 된 마이그레이션 0 ③ MongoDB 이벤트 저장소 접속·색인(`check_event_store` 와 같은 함수) ④ 반응 처리 — `stuck` 0, 가장 오래된 대기(`process_reactions --status` 와 같은 값) ⑤ outbox 미전송 수·가장 오래된 미전송 ⑥ 원장 대조(`check_ledger`) ⑦ `MEDIA_ROOT` 읽기·쓰기.
- 대기 시간 상한 같은 기준값은 설정값으로 둔다. 시험은 운영용(정상 하나, 항목마다 실패 하나).
- 문서: 백엔드 README "운영 점검", 설계 §7.

**줄이는 방법**
1. 개발용으로 옮긴다(위 표). 개발용도 합쳐 약 40 으로.
2. **합친다** — 지금의 시험 클래스(306개)가 대개 규칙 하나다. 한 규칙 = 시험 하나, 경우는 `subTest`. 경우마다의 준비는 그대로 두고(필요하면 경우마다 새 준비), 실패 보고에는 경우 이름이 남는다.
3. **지운다** — 고정 변형 목록과 커버리지로 다른 시험이 같은 결함을 잡는다고 확인된 것만.
4. 남기는 우선순위: 돈(과금·원장·예산), 보안(인증·접근·CSRF·잠금·매체 키), 데이터 정합(추가 전용·outbox·결정 스냅샷), 잠금 규약마다 대표 경쟁 시험 하나, 계약에 보이는 동작.
- 합치기는 개수를 줄이지만 단언은 그대로라 실행 시간은 개수만큼 줄지 않는다.

**검증** — 규모가 커서 시험 하나씩의 변형 대신 기계적으로 본다(6-6·6-12·6-17 의 "지울 시험이 잡는 결함을 남는 시험이 잡는다"를 넓힌 것).
- 기준선(6-18b):
  - 제품 코드의 줄·분기 커버리지(coverage.py).
  - **고정 변형 목록**: 작은 스크립트(`scripts/measure.py`, 6-18c 뒤 `tests/tools/`)로 만든 변형 약 300개(비교 뒤집기·and/or·조건 부정·정수 +1·덧셈/뺄셈·호출 문장 빼기)와, 지금 시험이 그중 무엇을 잡는지. 모든 영역을 줄이므로 핵심 모듈만이 아니라 **제품 코드 전 패키지와 프론트 화면 코드**에서 덮인 자리를 패키지마다 비례해 뽑는다(6-18b 에서 넓힘).
- 단계마다: 커버리지가 줄지 않는다. 기준선에서 잡던 변형을 모두 잡는다 — 못 잡으면 단언을 옮기거나 시험을 남긴다. 동등 변형은 이유와 함께 적는다.
- **대응표**(옛 시험 → 새 시험)를 파일로 남기고 문서 인용을 스크립트로 바꾼다. 이 계획서의 지난 기록은 고치지 않고 대응표를 가리킨다.
- `check.sh` 개수 관문: 운영용 > 500 이면 실패, > 300 이면 경고. 개발용·합계도 보인다.
- 마지막(6-18k): 150 동시 부하, `failure_test.py` processor-kill·relay-kill, 시계 점검, 서빙 질의 수(11 · 36 · 36).

**단계** (한 단계 = 한 커밋, `check.sh`(`DB_NAME=ads_impl`))

| 단계 | 할 일 | 완료 |
|---|---|---|
| **6-18a 결정·계획** | 이 절·§8 요약·§10, 6-17f 해시, 설계 §2·§8 Step 6·§10 "시험 구성" | **완료 `0f0e9e2`** |
| **6-18b 기준선·빈 곳** | coverage(requirements 의 개발·시험 묶음), 변형 스크립트·고정 목록, 기준선 기록. R28 시험(광고주 둘의 후보 중 한쪽만 잔액 부족·예산 소진이면 그쪽만 빠짐) — 지금 코드에서 통과하고 6-17c 의 변형 둘을 잡는지 확인 | **완료 `866f276`** — R28: `test_records_assemble::test_each_candidate_carries_its_own_advertisers_balance_and_campaigns_budget`(광고주 둘, 한쪽에 과금 900) — 지금 코드에서 통과, 6-17c 의 변형 둘(모든 후보가 첫 후보 광고주의 잔액 · 첫 후보 캠페인의 소진액)을 사본에서 넣으면 이 시험만 실패. 시험 1,345 → 1,346. `requirements.txt` 를 "운영"·"개발·시험" 두 묶음으로, 개발·시험에 `coverage~=7.16.2`. `scripts/measure.py`(coverage·mutants·run·compare)와 기준선 `scripts/measure_baseline/`: 커버리지(1,346개 모두 통과, 약 170초) **줄 6,086/6,367 · 분기 1,355/1,434**, 변형 **307개**(덮인 자리 2,071개 중 패키지 비례·시드 618 — 비교 91·호출 빼기 81·정수 48·조건 부정 42·and/or 29·덧셈/뺄셈 16) 중 **270개를 잡음**(살아남은 37 — assets 3·billing 2·campaigns 4·console 7·engine 1·events 6·foundation 2·프론트 3·masters 2·records 6·serving_api 1, 무한 반복 1개는 시간 초과로 잡음). 변형마다 그 줄을 덮은 시험만 `--keepdb --failfast` 로(일꾼 4, 약 6분). 측정 DB(`ads_cov`·`ads_mut{n}` 과 시험 DB)는 측정이 만들고 지운다 — 배포 점검 시험이 새 프로세스에서 `DB_NAME` 의 실제 DB 에 접속하므로 빈 DB 가 있어야 한다. `compare` 는 기준선끼리 0 · 0, 줄 하나·변형 하나를 일부러 나쁘게 한 결과에서 둘 다 보고 종료 코드 1 |
| **6-18c 폴더 이동** | `tests/ops`·`dev`·`support`·`tools`·`docker`. 내용은 그대로(시험 수 그대로), import·경로, `check.sh`·README·문서의 `scripts/` 경로 | **완료 `b1c034d`** — `git mv` 로 운영용 81파일 → `tests/ops/`, 개발용 10파일·`boundaries/` → `tests/dev/`, 도우미 9·시험용 URL 셋·`support_app` → `tests/support/`, `scripts/` 14파일·`measure_baseline/` → `tests/tools/`, `docker/` → `tests/docker/`. 앱 폴더에는 운영 코드와 `tests/` 만 남는다. 시험 내용은 그대로이고 바뀐 것은 가져오기(`tests.support.*`)·깊이가 바뀐 경로(`parents[2]`)·시험 설정의 모듈 이름(`tests.support.hashers`·`tests.support.support_app`)·제품 코드 주석의 경로뿐이다. `check.sh` 는 운영용(`tests.ops`)·개발용(`tests.dev`)을 따로 돈다. 분류 정정 둘(위) — **운영용 1,223 · 개발용 123**(문서·계약 대조 34 · 코드 구조 35 · 시험 도구 54) = 1,346. 경로는 백엔드·프론트 README, 설계·위협 모델·부하 시험 문서·DRD, 스크립트 안내문을 고쳤다. 이 계획서의 지난 기록(`scripts/…`·`tests/test_…`)은 그대로 둔다 — 6-18c 전 경로다. 옮긴 도구 중 `check.sh` 가 돌리지 않는 것은 구문 검사와 짧은 실행(`clock_shift_test.py --days 4`, `measure.py compare`)으로 확인 |
| **6-18d 운영 점검 명령** | `ops_check` 와 시험, README·설계 §7 | **완료 `910fea7`** — `console/management/commands/ops_check.py`: 기존 점검 명령(`check --deploy`·`migrate --check`·`check_event_store`·`check_ledger`)과 `records.api.inbox_status`·`events.api.outbox_status`(새로 공개)를 부르고, 기다림의 상한 `OPS_CHECK_MAX_WAIT_SECONDS`(600초 — 보류 300 + 재확인 30 보다 길게)만 여기서 본다. 콘솔 규칙(`django.db`·모델 매니저 금지)을 지킨다 — DB 는 명령을 거쳐서만. 점검마다 `OK`/`FAIL` 한 줄, 하나가 실패해도 나머지를 모두 보고 끝에 종료 코드 1. 시험 둘(운영용, `tests/ops/test_ops_check.py`): 건강한 백엔드(prod 와 같은 배포 점검 값)에서 일곱 줄 모두 OK, 점검마다 깨진 상태(시험 설정의 배포 경고, `django_migrations` 한 줄을 잠시 지움, MongoDB 닿지 않음, stuck 반응, 601초 된 미전송, 없는 `MEDIA_ROOT`, 고친 지갑 잔액)에서 그 줄만 FAIL. 변형 셋(stuck 판정 뒤집기, 상한 비교 뒤집기, 끝의 실패 빼기)을 모두 잡음. 개발 DB(`ads_impl`, 6-16 전 스키마)에서 돌리면 배포 설정(dev 설정)·마이그레이션만 FAIL. 문서: 백엔드 README "운영 배포"·"상시·주기 작업"(작업 목록의 원본, 설계 §10 "운영 작업 목록" — 설계 §7 대신). 함께: `check_ledger` 의 도움말에 남은 "일 소진액 == 원장 합계"(6-16f 뒤 낡음)를 뺌. 운영용 1,223 → 1,225 |
| **6-18e 개발용** | 135 → 약 40 | **완료(이 커밋)** — **합치는 방식 [사용자 2026-10-14, 시제품 108 → 23 을 보고]**: 시험 클래스(규칙)마다 시험 하나. 경우는 `case_…` 메서드로 두고 `test_<규칙>` 하나가 `tests/support/cases.py` 의 `run_cases` 로 모두 돈다 — 경우마다 새 인스턴스로 원래 시험처럼 따로 준비·정리·DB 격리(TestCase 는 저장점, TransactionTestCase 는 비우기), 결과는 경우 이름의 subTest. 바깥 시험은 클래스의 setUp·tearDown 을 하지 않는다(시제품에서 TransactionTestCase 의 바깥 준비가 커밋한 행이 경우에 섞여 한 경우가 2 를 셌다 — 고침). 경우 하나만은 `manage.py test …Class.case_y`. 개발용 123 → **25**(규칙 21 + 시험 하나짜리 넷). 섞인 파일 나눔: `test_http_security` 의 템플릿 인라인 금지(T9) → `tests/dev/boundaries/test_templates.py`, `test_frontend_sync` 의 화면 데이터·CSRF → `tests/ops/test_presentation_data.py`. 운영용 1,225 → 1,229, 합계 1,254. 위협 모델 동기화 시험이 `case_…` 인용도 본다. 이름 대응표 `tests/tools/test_renames_6_18.jsonl`(옛 이름 115개 → 경우), 인용을 스크립트로 바꿈(위협 모델 35·DRD 2·설계 2·프론트 주석 2). 측정(바뀐 뒤): 커버리지 줄 6,140/6,421 · 분기 1,366/1,446(`ops_check` 가 더해짐), 변형 278/307 을 잡음, **덮이지 않게 된 줄 0 · 놓친 변형 0**. 측정 보완: ① 기준선의 m103(`alerts.py` 잔액 비교)은 기준 코드(`866f276`) 사본에서 세 번 돌려도 잡히지 않아 "살아남음"으로 고침 — 처음 기록의 잡힘은 일꾼 넷이 함께 돌 때의 일시 실패(기준선 잡음 270 → 269) ② 커버리지 비교를 줄 번호가 아니라 **줄 내용**으로(6-18d 에서 설정 한 줄이 더해져 뒤 번호가 밀렸다) — 기준선에 그때의 줄 내용을 채우고, 고치거나 지운 줄(지금 소스에 없는 내용)은 덮일 수 없어 빼고 본다. 실제 손실(덮이던 줄 하나를 뺀 결과)은 여전히 잡는다 ③ 변형 자리가 밀렸으면 ±30줄에서 같은 원문을 찾는다. 함께: 6-18b 해시를 바로잡음(`866f226` → `866f276`) |
| **6-18f engine·매체 API** | 139 → 45 | |
| **6-18g 반응 판정·퍼널** | 204 → 45 | |
| **6-18h 과금·캠페인·마스터·이미지** | 298 → 85 | |
| **6-18i 이벤트·정합** | 207 → 40 | |
| **6-18j 화면·계정·보안·설정** | 362 → 85(운영 점검 명령 시험 포함) | |
| **6-18k 마무리** | 개수 관문, 측정, 대응표·문서 인용, 완료 기록 | |

**리팩터링 세션과**: 6-18c 는 모든 시험 파일의 경로를 바꾼다. 6-18 동안 리팩터링 8차를 시작하지 않고, 끝난 뒤 8차 점검으로 결과를 본다.

**남는 위험**
- 합친 시험은 한 경우가 실패하면 그 시험 전체가 실패로 센다(`subTest` 가 경우 이름은 남긴다).
- 변형 목록 밖의 결함은 측정이 보장하지 않는다 — 돈·보안·정합 묶음은 줄일 때 사람이 한 번 더 본다.
- MySQL 경쟁 시험(트랜잭션 시험 33파일)은 합쳐도 경우마다 커밋된 준비가 필요해 실행 시간이 크게 줄지 않는다.

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
| **Step 6-16** 결함·DRD 축소·검토 지점(리팩터링 7차 점검 후속, 기준 코드·문서 `0e6fa94`) | **완료 (2026-10-14)** — 6-16a `ce3be44` 결정·계획 · 6-16b `aa12d31` 시계 의존 시험 · 6-16c `29b1347` 미리보기 500 · 6-16d `fb9e984` 결정의 `bid_id` · 6-16e `9fc4734` 오류 화면의 세션 · 6-16f `f4a6800` 소진액은 원장에서 · 6-16g `7ea74d6` 상한은 사용자 행 잠금 · 6-16h `5f5f2fb` 권한 M2M 제거·그룹 화면 · 6-16i `e5a8159` 시험 빈 곳·스크립트 · 6-16j `440e7a9` DRD 정리·R27 · 6-16k `82b0dcf` 측정·완료 기록 · 6-16l `f63ecff` 실제 검토 후속(낡은 소진액 서술, "나가는 중" → "선택됨"). 시험 1,351 → 1,349, 서빙 질의 수 11 · 36 · 36, 150 동시 부하·장애 시험 두 시나리오·시계 점검 셋·실제 검토(확률 선출·예산 소진·클릭 과금) 통과 | §8.4.17. 리팩터링 세션 요청(결함 E1~E4·DRD 축소·R20~R27)을 구현 세션이 판단·계획. 사용자 결정: 표 −4(B3·O8·권한 M2M), DRD 는 현재 구조만, R23 프론트 필터 포함, 시계 점검 스크립트. E1 은 2026-10-17 12:00 UTC 전에. 끝나면 리팩터링 세션이 7차(6-17) |
| **Step 6-17** 코드 정리(리팩터링 7차 — 시험 코드 포함, 기준 코드·문서 `f63ecff`) | **완료 (2026-10-14)** — 6-17a `3d807a2` 결정·계획 · 6-17b `129277f` 시험 먼저 · 6-17c `a503ba1` 시험 정리 · 6-17d `9dcbb5e` L0~L2·scripts · 6-17e `e28743f` L3·L4·프론트 · 6-17f `e803cc5` 측정·완료 기록. 시험 1,349 → 1,345 · 프론트 13 → 12, 동작 불변(화면 70개 비교), 서빙 질의 수 그대로(11 · 36 · 36), 150 동시 부하·장애 시험 두 시나리오 통과 | §8.4.18. 6-16 뒤 새 HEAD 로 리팩터링 세션이 진행(사용자 2026-10-14). 동작·계약·설계 결정은 바뀌지 않는다. 동작 변화가 필요한 발견은 "보고만"(R28) |
| **Step 6-18** 시험 축소와 운영·개발 분리(기준 코드·문서 `e803cc5`) | **진행 중 (2026-10-14~)** — 6-18a `0f0e9e2` 결정·계획 · 6-18b `866f276` 기준선·R28 시험 — 커버리지 줄 6,086/6,367 · 분기 1,355/1,434, 변형 307개 중 270개를 잡음, 시험 1,345 → 1,346 · 6-18c `b1c034d` 폴더 이동 — 운영용 1,223 · 개발용 123, `scripts/`·`docker/` → `tests/tools/`·`tests/docker/` · 6-18d `910fea7` 배포 후 점검 `ops_check` — 운영용 1,225 · 6-18e 개발용 규칙마다 시험 하나(이 커밋) — 개발용 123 → 25, 운영용 1,229, 측정 손실 0 | §8.4.19. 사용자 결정: 운영용 ≤ 300·합계 ≤ 500, 운영용 = 제품 동작·개발용 = 문서·계약·구조 대조와 시험 도구, 배포 후 점검 명령 `ops_check`, 개발 도구·시험은 `tests/` 아래 전부, 합치기 위주 + 측정 |
| **Step 6-15** 프론트·백 서버 분리(기준 코드·문서 `90e1a28`) | **완료 (2026-10-14)** — 6-15a `22b2d8c` 결정·계획 · 6-15b `6c9c694` 프론트 골격 · 6-15c `f1a1595` 화면 데이터(모든 우리 화면, 6-15d 를 합침) · 6-15e `1a9a891` 배포·실행 · 6-15f 측정·완료 기록(이 커밋). 시험 1,343 → 1,351 + 프론트 13, 150 동시 부하·장애 시험 두 시나리오 통과 | §8.4.16. 운영 환경(프론트 서버만 공개, DB 는 백 서버에서만)에 맞춰 팀 메타버스와 같은 구조로. 사용자 지시: 운영 화면도 프론트, 관리 사이트 공개, `apps/ads_frontend` |
| **Step 6-14** 선출 정책 교체 — 최고가 → 상한 근접 가중 추첨(기준 코드·문서 `63058aa`) | **완료 (2026-10-14)** — 6-14a `d254675` 결정·계획 · 6-14b `967b19c` 시험 먼저 + 교체 · 6-14c `90e1a28` 측정·완료 기록 · 6-14d 이벤트 홉 시험의 기준 시각 고정(이 커밋, 체크포인트 검증 중 발견). 시험 1,342 → 1,343, 150 동시 부하·장애 시험 두 시나리오 통과 | §8.4.15. 사용자가 운영 전에 선출 로직을 확인하고 지시(가중치 = (상한 − 하한) + 2 × (적용 금액 − 하한), 하한 = 상한이면 균등, 옛 정책 삭제·교체 구조 유지·`trace` 요약) |
| **Step 6-13** 검토 지점 보완(R1~R19의 동작 변화, 기준 코드·문서 `9e262e4`) | **완료 (2026-10-14)** — 6-13a `efe83c4` 화면 오류 표시·응답 코드(R1·R2·R6) · 6-13b `5f03306` 서비스 동작(R3·R4·R5·R9) · 6-13c `df2442b` 접근성(R8) · 6-13d `cf6fd98` 시험 보강(R11·R12·R13, R7 그대로) · 6-13e `493c144` 소재 선택 경로 하나(R17) · 6-13f `77db030` 엔진 후보·정책 제약·구성 성격(R18) · 6-13g 스크립트(R19)·측정(이 커밋). 시험 1,335 → 1,342, 150 동시 부하·장애 시험 세 시나리오 통과 | §8.4.14. 리팩터링 6차가 "보고만"으로 넘긴 것(§8.4.13) 중 동작이 바뀌는 것, 사용자가 넘김. 결정이 필요한 곳은 그 단계에서 묻는다 |
| **Step 6-12** 코드 정리(리팩터링 6차 — 시험 코드 포함, 기준 코드·문서 `e621248`) | **완료 (2026-10-13)** — 6-12a `e621248` 시험 먼저(구현 세션) · 6-12b `78effec` 결정·계획·인용 · 6-12c `1b0146b` 시험 정리(시험 1,343 → 1,336) · 6-12d `0177dbc` L0·L1·scripts · 6-12e `45ddf24` L2 · 6-12f `800797b` L3·L4 · 6-12g 측정·완료 기록(이 커밋) | §8.4.13. 사용자가 진행을 맡김(D-1~D-4 권장안). 동작 불변, 계약·설계 결정 그대로. "보고만" R1~R19(R10은 6-12a) |
| **Step 6-11** 광고 상세의 이미지 칸 — 고르기만·올리기만(기준 코드·문서 `9822393`) | **완료 (2026-10-13)** — 한 커밋 `5fe343c`(+ 시험 보완 `e621248`) | §8.4.12. 사용자 요청(브라우저 검토): "소재" → "이미지"(내 이미지 중 고르기만, 연결은 고를 때 함께), "소재 더하기" → "이미지 업로드"(올리기만), 수정·교체는 소재 상세에서만 |
| **Step 6-10** 과금 재설계 — 구성별 반응 비율(기준 코드·문서 `49e0ef3`) | **완료 (2026-10-13)** — 6-10a `3d6e017`·`ccb65d6` 결정·계획 · 6-10b `1be3658` 구성 정책에 비율 · 6-10c `335e81b` 과금 전환 · 6-10d `d557905` 단위 제거 + 광고주 화면 · 6-10e `d5a4b46` 화면 용어 · 6-10f 측정·완료 기록. 시험 1,337 → 1,341, 150 동시 부하·장애 시험 두 시나리오 통과, 서빙 질의 수 11 · 40 · 37(클릭도 과금) | §8.4.11. 사용자 결정 B1~B10, 계획을 쓰며 나온 K1~K6(2026-10-13): 옛 데이터 이전 없음 — 6-10b 착수 때 모든 DB를 지우고 새로 만든다(호환 코드 없음), 종류별 스키마 버전, 비율 열·`charge_shares`, DB 제약(하한 ≥ 100 포함), `share/v1`(`by-unit/v1` 삭제), 광고그룹 소진액은 모든 유형 |
| **Step 6-9** 구조 재편 — 캠페인 · 광고 · 소재(기준 코드·문서 `0eb674b`) | **완료 (2026-10-13)** — 6-9a `4669baf` 결정·계획 · 6-9b `576f3cd` 소재 끄기 제거 · 6-9c `724a276` 소재 목록·연결(서비스) · 6-9d `4503452` 화면 · 6-9e `35767b7` 화면 용어 · 6-9f 측정·완료 기록. 시험 1,308 → 1,337, 150 동시 부하·장애 시험 두 시나리오 통과, 서빙 질의 수 11 · 40 · 28 그대로 | §8.4.10. 다음은 6-10 과금 재설계 |
| **Step 6-8** 브라우저 검토 후속 — 작은 수정(기준 코드·문서 `a23873c`) | **완료 (2026-10-13)** — 6-8a `61880b8` 결정·계획 · 6-8b `25c52d9` 모니터링 링크 · 6-8c `0eb674b` 사유 기본값·완료 기록 | §8.4.9. 다음은 6-9 구조 재편·6-10 과금 재설계(§8.4.9 "다음") |
| **Step 6-7** 리팩터링 5차 보고 후속(기준 코드·문서 `5d75026`) | **완료 (2026-10-13)** — 6-7a `e9096a7` 결정·계획 · 6-7b `113abe3` 장애 시험의 임시 폴더 · 6-7c `068c98f` outbox PK 기본값 · 6-7d `a23873c` 운영 화면의 409·완료 기록 | §8.4.8. 시험 1,305 → 1,306, 서빙 질의 수 11 · 40 · 28 그대로. ④ 질의 줄이기는 보류 그대로 |
| **Step 6-6** 코드 정리(리팩터링 5차 — 시험 코드 포함, 기준 코드·문서 `0b2166a`) | **완료 (2026-10-13)** — 6-6a `3d48354` 시험 먼저 · 6-6b `4eab7dc` 결정·계획·인용 정리 · 6-6c `c161585` 시험 폐기·합치기·옮기기 · 6-6d `d9de54b` 시험 도우미 · 6-6e `81c15b1` L0·L1·scripts · 6-6f `613e3d7` L2~L4 · 6-6g `0db492e` 상세 질의 −1 · 6-6h 측정·완료 기록 | §8.4.7. 사용자 결정(2026-10-13): D-1 위협 모델 인용은 먼저 대체 시험으로 바꾸고 그 뒤에 시험을 지운다, 이번 문서는 리팩터링 세션이 고친다 · D-2 마이그레이션 이행 시험 9개 폐기(그 이전 상태의 DB가 없다) · D-3 콘솔 광고그룹 상세 질의 −1 포함. 6-6a: 폐기 후보 32개의 변형 61개 — 대체가 잡음 52, 대체만 잡음 6, 대체가 못 잡음 3(1개는 그대로 지움, 업로드 가드 순서 시험은 남김, 미전송 수 단언은 옮김), 잠금 없음 시험 고쳐 씀. 결과: 시험 1,355 → 1,305, 전체 시험 156초 → 120초, 시험 코드 순감 814줄, 150 동시 부하·장애 시험 두 시나리오 통과, 서빙 질의 수 11 · 40 · 28 그대로. 계획과 다르게 남긴 것: `ChargePolicy` Protocol(설계 §4.7)·`AdCreateForm(units=)` |
| **Step 6-5** 배포 구성 전환(nginx 앞단·HTTP 전제, 기준 코드 `6d80ecb`·문서 `6b4f662`) | **완료 (2026-10-13)** — 6-5a `b9edb2b` 결정·계획 · 6-5b `5e69276` 가입 시도 제한 제거 · 6-5c `6c5aa6d` 신뢰할 프록시 수 prod 필수 · 6-5d `f744769` HTTP 전제 · 6-5e `dd53bda` 정적 파일(WhiteNoise) · 6-5f 측정·완료 기록(질의 수 11 · 40 · 28 그대로, 시험 1,357 → 1,355) | §8.4.6. 사용자 결정(2026-10-13): nginx(certbot)가 TLS·80 → 443·HSTS·접속 허용 목록(강의실 라우터·메타버스 서버), Django는 HTTP 전제(HTTPS 리다이렉트·HSTS·`BEHIND_TLS_PROXY` 제거, Secure 쿠키 유지, `CSRF_TRUSTED_ORIGINS` 필수), IP 판정 골격 유지와 `TRUSTED_PROXY_COUNT` prod 필수(6-3h 경고 제거), 가입 시도 제한 제거(6-3d 환경값 포함, 위협 모델 T2로 관리), 정적 파일은 Django(WhiteNoise), 콘솔 분리 대비 두 행(설계 §6.6). 설계 §7-14를 닫음. 이번에는 구현 세션이 문서도 고친다(사용자 지시) |
| **Step 6-4** 코드 정리(리팩터링 4차, 기준 코드 `5d2d517`·문서 `950946b`) | **완료 (2026-10-13)** | §8.4.5대로 6단계 + 측정, 한 단계 한 커밋(`dd21833`~`39bb3da`, 6커밋). 6-4a `dd21833` 시험 먼저(변형 49개: 기존 시험 30, 새 시험 11개 `tests/test_consolidated_rules.py`(6-6c 에서 도메인 파일로 나눔)가 17, 등가·순서 불변이라 남긴 것 2) · 6-4b `6195e59` `foundation.is_int` · 6-4c `ce0c569` masters의 `_key_active`·`_get_media`, `IssuedKey.expires_at` 삭제 · 6-4d `604d05c` `events.api`의 쓰지 않는 공개 별칭 `window_start`·`canonical_json`·`manifest_sha256` 삭제, `_absent_from_mongo`, `CONTENT_TYPES` ← `FORMAT_INFO` · 6-4e `814a0bc` billing·campaigns의 `_charged_on`·`_duplicate`·`_spend_totals`·`_check_ends_at` · 6-4f `39bb3da` 재검토 요청 닫기 UPDATE 한 번, `create_ad_group`의 게재 위치 재사용 — 질의 수 해제 7 → 6, 기간 종료 5 → 4, 광고그룹 만들기 11 → 10(변형 7개 모두 잡음) · 6-4g 측정 — 150 동시 부하 통과, 서빙 질의 수 11 · 40 · 28 그대로. **검증**: 단계마다 `check.sh` 종료 코드 0, 시험 1,342 → 1,353. **사용자 결정**(2026-10-13): D-R1 서빙 경로 A1·A2는 하지 않음(§8.2.5 보류 두 행 — 클릭 28 → 27, 반응 40 → 39 가능), D-R2 6-4f 포함. **공개 이름 변경**: `foundation.api.is_int` 추가, `events.api` 별칭 3개·`IssuedKey.expires_at` 삭제(사용처 없음). 계약·설계는 바뀌지 않는다. 6-3h의 등록할 곳을 정했다(§8.4.4: `foundation/checks.py` + `FoundationConfig.ready()`). 보고(설계 변경 아님): `hopcheck`은 검증한 manifest·데이터 파일을 다시 읽어 써서, 그 사이 폴더가 바뀌면 검증한 바이트와 읽은 바이트가 다를 수 있다(§8.4.5). 다음: 6-3h·6-3i |
| **Step 6-3** 초기 운영 보완(O1~O8, 코드 `253334b`·문서 `164a7a6`) | **완료 (2026-10-13)** — 결정 반영·README 운영 보완, 서버 작업 6-3a `9e6e374`·6-3b `ea23a81`·6-3c `90fce97`·6-3d `a733e95`·6-3e `5d2d517`, 측정·문서 6-3g, 리팩터링 4차 뒤 6-3h `1509c10`·6-3i `6d80ecb`. **남은 것**: 운영하면서 할 것(§8.4.4) | §8.4.4. 리팩터링 세션이 6-2 완료 시점을 초기 운영 관점으로 검토해 O1~O8을 냈고 구현 세션이 코드로 모두 확인했다. 사용자 결정(2026-10-12): O1 B(웹 진입점은 `.env`의 설정 모듈을 무시, 실제 환경변수 또는 prod) · O2 A 지금(`inbox_status`·`--status`·60초 상태 줄·stuck 전환 로그) + B 리팩터링 4차 뒤(관리자 첫 화면 카드) · O3 B 두 단계(가입 상한 환경값, 프록시 설정 누락 경고는 리팩터링 4차 뒤 — 둘 다 임시방편) · O4 A(요청 ID 채우기, 화면·클릭 503 원인 한 줄) · O5 B(웹은 MongoDB 선택, 중계는 설정이 없으면 즉시 종료 — 운영 중 C로) · O6 C(배포 구성으로, §7.3.4 #4) · O7 A + 로그 시각 ISO 8601 `Z`(이후 logger 전환 고려) · O8 B(작업 목록 원본은 README). 계약은 바뀌지 않는다. **지금 반영**: 설계 §10 여섯 행("웹 진입점의 설정 모듈"·"반응 처리 현황 노출"·"운영 로그"·"이벤트 저장소 설정"·"DB 읽기·쓰기 시간 제한"·"운영 작업 목록")과 "가입 시도 제한" 덧붙임, 설계 §2·§7-9·§8 Step 6, 이 계획 §7.3.4 #4·§7.3.3 DB-2 행·§8 요약, README(prod 필수값에 `ADMIN_URL_PATH`·`MEDIA_ROOT`·`ASSET_PUBLIC_BASE_URL`, 운영 호스트의 설정 모듈, 배포 순서, 배포 점검의 프록시 수, 상시·주기 작업 목록에 `clearsessions`·`axes_reset_logs`, 매체 행 잠금의 운영 영향). **6-3g**: 서버 작업 — 웹 진입점 `config.env.load_env_for_web`, 로그 `UtcFormatter`·요청 ID 채우기·화면/클릭 503 한 줄·상시 명령 줄의 시각, `records.inbox_status`·`--status`·`idle` 줄·stuck 전환 로그, 가입 상한 환경값(1 이상), 중계는 설정이 없으면 종료 코드 1. 시험 1,322 → 1,342, 변형 34개 모두 잡음, 질의 수 기준선 그대로 11 · 40 · 28. 문서 — 설계 §2·§7-9·§8·§10 해시와 구현 세부, 위협 모델 T2·T6·T21·T22·T37 ⑬·T41 ⑤, README(웹 진입점, 단체 가입, 로그, `--status`·`idle` 줄, 중계 종료). 운영하면서 할 것: O5 → C, O7 → B 고려, O3 근본 보완. [열림] C1 503 로그 형식. **6-3h·6-3i**(리팩터링 4차 뒤): 서버 작업 — 6-3h `1509c10` 시스템 체크 `foundation.W001`(TLS 종단 프록시 뒤인데 `TRUSTED_PROXY_COUNT` ≤ 0이면 `check --deploy` 경고, `foundation/checks.py` + `FoundationConfig.ready()`, 결정의 "=0"을 "0 이하"로 넓힘), 6-3i `6d80ecb` 관리자 첫 화면 처리 현황 카드(카드 선택지 A — 반응 처리 현황만, 사용자 2026-10-13, 첫 화면 질의 +1). 시험 1,353 → 1,357, 변형 15개(8 + 7) 모두 잡음, 질의 수 11 · 40 · 28 그대로(HEAD `6d80ecb`). 문서 — 설계 §2·§7-9·§8·§10("가입 시도 제한"·"반응 처리 현황 노출"), 위협 모델 T6(시험 2개, 잡지 못하는 두 구성은 §6 잔여 위험)·T37 ⑬(카드, 시험 2개), README(`check --deploy`의 `foundation.W001`, 배포 점검, `--status` 행, 관리자 첫 화면 카드). 운영하면서 할 것에 O2 카드의 중계 현황·판정 기준값 재검토를 더했다 |
| **Step 6-2** 외부 검토 후속(코드 `7c4714b`·문서 `30b0195`) | **완료 (2026-10-12)** — 결정 반영·문구 정정, 서버 작업 6-2a `3827185`·6-2b `e872006`·6-2c `9189af8`·6-2d `253334b`, 측정 6-2e, 문서 6-2f(계약 1.3.0) | §8.4.3. 외부 검토 P2 4건·P3 2건, 구현 세션이 실제 MySQL로 모두 재현(결정 쪽 구멍·2^64 넘는 정수의 조용한 변환을 더 찾음). 사용자 결정 여섯(2026-10-12): ① 매체 행 = 매체 생명주기 잠금(B — 판정은 매체 행 공유 잠금 통과, 결정은 저장 트랜잭션 안에서 공유 잠금으로 활성 확인) ② `context` 숫자 ±(2^53−1), 범위 밖 400 ③ 503 = 성공을 확인하지 못했다(A — 문구만, 결정 요청 멱등은 Step 5 **5-5**) ④ DRD 물리 제약은 실제 구현대로 ⑤ 공개 응답 스키마는 추가 필드 허용, 서버 출력은 시험에서 닫아 검사(A) ⑥ C1 공통 설명 정정. **지금 반영**: 설계 §10 결정 넷("매체 비활성화와 판정·결정의 순서"·"결정 API 세부" ⑪·"503은 성공을 확인하지 못했다는 뜻"·"공개 응답 스키마의 추가 필드")과 ⑨·전환·⑪ (사)·6-1 ③·"계약 v1.2" 정정, 설계 §2·§8 Step 5 5-5·Step 6 6-2, 계약 C1 **1.2.0 안의 문구 정정**(`Unavailable`·`createDecision`·인증 예외 `/c/{token}`과 전역 전송 상한·`PayloadTooLarge`·전환 요약·반응 `PUT`의 클릭), 매체용 요약 503 한 줄, DRD 0.34(물리 제약, D-7 포함). **서버 작업**: 매체 생명주기 잠금(`masters.media_active_for_share` — 판정은 결정 행 다음에 매체 행 공유 잠금 통과, 결정은 저장 트랜잭션 안에서 커밋까지), `parse_json` 숫자 범위(상한 = `MAX_AMOUNT`), 응답 검사는 닫은 스키마 사본(`Problem` 포함), 503 주석 정정. 시험 1,310 → 1,322, 변형 20개 모두 잡음, 질의 수 기준선 11 · 40 · 28. **6-2f**: 계약 C1 **1.3.0**("v1.3 변경": 범위 밖 숫자 400, 응답 스키마 추가 필드 허용)·매체용 요약, 설계 §2·§3·§8·§10 해시와 "계약 v1.3", 위협 모델 T45 ⑥·T35 ⑪(⑧ 503 정정)·T33 ⑥·T12·§5.2, DRD 0.35, 부하 시험 문서의 결정 질의 수 |
| **Step 6-1** 매체 연동 검토 후속(게임 ad-bridge) | **완료 (2026-10-12)** — 결정 반영 → 서버 규칙 6-1a `fcee77b`·6-1b `7c4714b`·6-1c 측정 → 6-1d 문서 | §8.4.2. 사용자 결정 셋(2026-10-12): ① `subject_id`는 매체가 만든 광고 전용 가명 ② 반응 401은 고친 뒤 한 번 재전송·403은 재전송 없음, 매체 비활성화는 그 전 결정을 끝냄(`media_deactivated`) ③ 판정 결과·사유는 매체 서버용. **결정 반영**: 계약 C1 **1.2.0**(호환 — 전송 형식 그대로, 규약 MUST·규칙 5·`getReaction`·`ReactionReasonCode`)과 매체용 요약, DRD 0.32(D-5 해결), 위협 모델 A6·T41, 설계 §2·C1 규칙 5·§8 Step 6·§10 결정 넷. **서버 규칙**(기록 표 방식, 사용자 결정): 6-1a `fcee77b` `masters_media_deactivation`(켜져 있던 매체를 실제로 끌 때만 한 줄, 추가만, 관리자 화면 읽기 전용, `first_deactivation`), 시험 1,304개 · 6-1b `7c4714b` 규칙 `media-period`(`same-media` 바로 뒤, 구간 (결정, 접수], 필수 조건, `basis` v3 `media_deactivated_at`), 시험 1,310개 · 6-1c 질의 수 **결정 10 · 반응 39 · 클릭 27**(전 10 · 38 · 26). 단계마다 `check.sh` 종료 코드 0(20 동시·구간 `match` 12·`pip-audit`·`bandit`), 변형 검사 6·10개 모두 잡음(구현 세션). **6-1d**: 계약 1.2.0 안에서 `media_deactivated`(사유 코드 추가는 호환), 매체용 요약, 설계 §4.7 규칙 표·2-9 순서·§10, DRD 0.33(M5·`basis` v3·규칙 체인), 위협 모델 T45·T39 ⑥·§5.2. 매체(게임) 쪽 요청 셋은 사용자가 전달 |
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
