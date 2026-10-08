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
6. **작업 환경**: `mamba activate claude`(Python 3.14.7). **코드에서 import하는 모든 라이브러리는 `requirements.txt`에 적는다**(§3 표).
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
        C1 v1.1 (2-6 이후, Step 3 전)   2-7 ─▶ 2-8 ─▶ 2-9 ─▶ 2-10 ─▶ 2-11
Step 3  화면 (Step 1 이후. 3-1 관리자와 3-2 광고주는 서로 독립)
Step 4~5  Raw 수집 → Kafka (Step 2 이후)
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
  README.md                    # 실행 방법(mamba activate claude, 환경변수, 명령)
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

**가입 흐름 확장**: `console`의 가입 뷰가 **한 트랜잭션(`transaction.atomic`) 안에서** `foundation.api.create_advertiser` → `billing.api.grant_signup`을 차례로 부른다(`foundation`이 `billing`을 알지 않는다). 지급이 실패하면 가입도 취소된다. 감사 로그에 `account.signup`과 `billing.signup_grant`가 남는다.

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
| `/reports/daily`, `/alerts` | **미구현** | 이벤트·반응 처리(Step 2) 이후. `alerts`는 현재 상태에서 계산하는 읽기 전용이라 Step 3 |
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
- [ ] **알려진 한계(후속 단계)**: 요청 제한 버킷이 프로세스 메모리라 다중 워커에서 한도가 최대 N배로 느슨해짐 · 동시성은 SQLite 결과이며 같은 결정·유형의 `ACCEPTED` 하나를 보장하는 조건부 유일 제약은 MySQL·MariaDB에서 쓸 수 없음(전환 시 재설계·재검증) · 이벤트 outbox(C2)는 Step 4 · C6의 `/reports/daily`·`/alerts`는 Step 3 · 부하는 단일 프로세스 `wsgiref` 서버 기준(운영 서버·프록시·장시간 미측정)

## 7.2 C1 v1.1: 퍼널 규칙·일괄 슬롯·클릭 관측 [계획, 결정 확정 2026-10-08]

결정은 설계 §10 "반응 퍼널 규칙"·"일괄 슬롯"·"클릭 출처"·"퍼널 집계"·"계약 v1.1"에, 계약은 [contracts/serving.openapi.yaml](contracts/serving.openapi.yaml) `1.1.0-draft`에 있다. 계약의 `[v1.1]` 필드는 **해당 단계를 구현할 때 `required`로 올린다**(그 전에 올리면 현재 응답이 계약 위반). **Step 3보다 먼저** 한다: 3-1a(슬롯 등록 화면)가 `audience`·`max_viewers`를, 3-2a(대시보드)가 퍼널 집계를 쓴다.

| 단계 | 핵심 | 완료 증거(요지) |
|---|---|---|
| 2-7 **[완료 2026-10-08]** | **슬롯 성격**(`masters`): 슬롯에 `audience`(`individual`·`shared`, **생성 뒤 변경 불가**)와 `max_viewers`(`shared`일 때 필수, 양의 정수) 추가, 기존 슬롯은 `individual`. 결정 API: 응답에 `audience`(계약 `required`로), 결정 요청의 `subject_id`는 `individual` 필수·`shared` 금지(어기면 400), 결정 스냅샷에 `audience` 기록(이벤트·집계용) | 슬롯 생성·변경 불가 테스트, 결정 요청 400 두 경우, 계약 대조(`audience` 필수), 기존 결정 응답 회귀 없음 |
| 2-8 | **클릭 관측** `GET /c/{token}`(`serving_api`, 루트 경로): Django `signing`(전용 salt) 토큰 = `decision_id`(+ `individual`은 `subject_id`), 결정 응답 `ad.click_url`(계약 `required`로, `shared`는 `?s={subject_id}` 템플릿). 유효한 토큰은 **항상 302** → 결정에 저장된 `redirect_url`, 무효·없는 결정·광고 없는 결정은 404. 클릭을 수신함에 `CLICK`으로 기록: 매체 = 결정의 매체, `reaction_id` = (결정, 사람)에서 결정적으로 만든 UUID(중복 클릭 1건), 시각 = 서버 수신, **출처 열 `source`(`media`·`server`)** 추가. `shared`에서 `s`가 없거나 틀리면 이동만. 헤더 `Cache-Control: no-store`·`Referrer-Policy: no-referrer`, 쿠키 없음, 인증 없음(URL 전수 점검 목록에 공개 뷰로 등록) | 302 대상이 요청 값과 무관함(열린 리다이렉트 없음), 위조·변조 토큰 404, 같은 사람 중복 클릭 1행·서로 다른 사람은 각각, `s` 누락 시 이동만, 쿠키·헤더 계약 대조, 기록 실패해도 이동은 되는지(사용자 경험)와 그 경우 로그 |
| 2-9 | **반응 판정 확장**(`records`): ① 반응 요청 `subject_id`(선택, 저장, 재전송 비교 대상에 포함) ② 규칙 파일 추가: `click-source`(매체가 보고한 `CLICK` → `click_not_reported`, 유형별 1회 자리를 차지하지 않음), `subject`(`subject_required`·`subject_mismatch`), `campaign-open`(`campaign_ended`: 판정 시점의 캠페인 종료 시각 이후 수신), `occurred-at`(`invalid_occurred_at`), `viewer-limit`(`viewer_limit`), `funnel-order`(`missing_prerequisite`), `funnel-window`(`window_expired`·`display_ended`: "같은 표시 단위의 다음 결정 시각"을 처리 단계가 조회해 사실로 넘김) ③ **보류**: 규칙이 "아직 판단 불가"를 돌려주면 `RECEIVED`로 두고 `attempts`를 올리지 않음, 보류 기한(300초)이 지나면 `missing_prerequisite`. `process_reactions`가 보류분을 다시 집음 ④ 판정 단위: `individual` = 결정, `shared` = (결정, 사람). 같은 결정·유형의 `ACCEPTED` 부분 유일 제약을 (결정, 사람, 유형)으로 확장 ⑤ 수치(300초·5초·30일·허용 오차 60초·보류 기한)는 설정값 ⑥ 응답 `subject_id`(계약 `required`로) | 규칙별 인정·거부 테스트(새 사유 9개), 보류 → 늦게 온 노출로 인정 / 기한 초과 거부, 매체 `CLICK`이 과금·전환 전제에 쓰이지 않음, 일괄 슬롯에서 A의 노출로 B의 클릭이 인정되지 않음, 캠페인 종료 뒤 수신은 과금 없음(기존 빈틈 회귀 테스트), 규칙을 설정에서 빼도 필수 조건(`guard`)은 유지 |
| 2-10 | **퍼널 집계** = Step 3의 S1을 앞당김: `records.api.daily_report`(노출·클릭·전환 수, CTR = 클릭/노출, 전환율 = 전환/클릭, 소진 포인트, 앞 구간 비교). 조회 시점 집계(별도 테이블 없음), `ACCEPTED`만 센다. 반응이 많아지면 함수 안쪽만 카운터·파이프라인 결과(C4)로 바꾼다(설계 §10 "퍼널 집계") | 개인·일괄 슬롯 섞인 데이터로 수치 대조, 다른 광고주 범위 차단, 질의 수 고정(N+1 없음) |
| 2-11 | **마무리**: 계약 `info.version` `1.1.0`(draft 해제), `[v1.1]` 표시 정리, 부하 시험에 클릭 경유·보류·일괄 슬롯 추가(유실 0·이중 과금 0 유지), 변형 검사, 위협 모델 새 행(클릭 경유 공개 GET·토큰 위조·링크 미리보기·시청자 부풀리기·보류 악용), DRD C1 절·[contracts/README.md](contracts/README.md)(매체 안내) v1.1로 갱신 | `scripts/check.sh` 통과, 계약 ↔ 구현 대조에 `/c/{token}` 포함, 매체 안내에 "광고를 바꿀 때마다 새 결정"·"이동은 `click_url`로"·"일괄 슬롯은 사람별 보고" 명시 |

**알려진 한계(설계 §10 "계약 v1.1")**: 클릭 주소는 공개 GET이라 링크 미리보기·프리페치가 클릭으로 기록될 수 있다(중복 1건·표시 중 5초 창·`max_viewers`로 폭 제한, IP 단위 제한은 필요해지면). 일괄 슬롯의 "누가"와 노출·전환은 여전히 매체 보고다.

---

# 8. Step 3~5 (요약)

| 단계 | 내용 |
|---|---|
| Step 3-1 | 관리자(Django admin): 입찰 정책 새 버전 입력과 **일괄 입력 동작**, 매체·슬롯, 광고 모니터링(썸네일·이동 주소 도메인), 중단/해제(사유), **재검토 대기 목록(해제/반려)**, 광고주 비활성화·비밀번호 초기화, 포인트 조정, 감사 로그 열람 |
| Step 3-2 | 광고주 콘솔: 대시보드(포인트 위젯), 캠페인·광고그룹 목록, 광고 만들기(단계형), **정지 사유·재검토 요청 버튼**, 포인트 내역, 내 정보. **콘솔 뷰에 비즈니스 규칙을 두지 않는다**(설계 §6.6). **규칙의 원본은 `contracts/console.openapi.yaml`(C6 초안)** — 서비스가 이 규칙을 지키고 화면은 그대로 따른다 |
| Step 4-1 | outbox + `EventSink`(JSONL), 이벤트 스키마(C2) 확정 |
| Step 5 | Kafka sink + relay, C4 Insight 입력 방식 결정과 최소 수신, 재처리·백필 |

## 8.1 Step 3 상세 계획 (2026-10-08 작성, 착수 전 결정 6건은 아래 [결정 대기])

### 8.1.1 전제와 원칙

- **서버 렌더(Django 템플릿) + 폼 POST.** 엄격한 CSP(`script-src 'self'`, 인라인 스크립트·`style` 속성 금지)가 이미 켜져 있어 JS 없이 동작하는 화면이 기본이다. 정적 JS는 꼭 필요한 곳에만 작은 파일로 더한다(없어도 쓸 수 있어야 한다). 차트는 **서버가 만든 인라인 SVG**(표현 속성만, 라이브러리 없음).
- **뷰는 얇다(설계 §6.6).** 비즈니스 규칙(검증·소유권·상태 전이·금액 계산)은 서비스 `api`/`engine`에만 둔다. 뷰는 "서비스 호출 → 렌더"이고, 도메인 예외를 화면 메시지·폼 오류로 바꾸는 코드는 **콘솔 가장자리 한 곳**(`console/errors.py`)에만 둔다. **경계 테스트로 강제**한다: `console` 아래 파일은 `models`·`django.db.transaction`·`engine` 가격 계산을 import하지 않고 `<module>.api`만 import한다.
- **여러 모듈의 값을 모으는 화면 전용 조립**(예: 캠페인 목록의 `today` = 캠페인 + 소진액, 알림, 입찰 미리보기 `effects`)은 `console/queries/`에 둔다. 규칙을 새로 만들지 않고 각 `api` 결과를 합치기만 한다(C6가 이미 "콘솔이 채운다"고 한 부분). 같은 층(L2)의 `campaigns`·`billing`은 서로 import할 수 없으므로 조립 위치는 L4 `console`이다.
- **관리자 화면은 Django admin 위에 얹는다.** 모델 직접 편집은 계속 막고(읽기 전용), 쓰기는 **서비스 `api`를 부르는 전용 페이지·동작**으로만 한다. 여러 모듈을 가로지르는 관리자 페이지는 L4 `console/operator/`에 두고 admin 사이트에 등록한다(각 앱의 `admin.py`는 자기 모델만 본다).
- 모든 쓰기는 PRG(POST → 리다이렉트 → GET)와 CSRF, 위험한 동작은 **사유 필수 + 감사 로그**(서비스가 이미 같은 트랜잭션에 남긴다). `subject_id`·매체 키·다른 광고주 정보는 어떤 화면에도 나오지 않는다. 시각은 KST로 표시하고 UTC 기준 항목(예산 리셋)은 리셋 시각을 적는다. 숫자에는 단위("포인트")를 붙인다.
- 광고주가 입력한 문자열(제목·이름·이동 주소)은 **항상 이스케이프**하고, 이동 주소는 `https`만 링크로 만들며 `rel="noopener noreferrer nofollow"`, 관리자 화면에는 **도메인을 눈에 띄게** 표시한다.

### 8.1.2 서비스 보강 (화면이 필요로 하는데 아직 없는 것)

| # | 필요 | 위치 | 내용 |
|---|---|---|---|
| S1 | 성과 지표(C6 `/reports/daily`) **→ 2-10으로 앞당김(퍼널 집계)** | `records.api.daily_report(owner, from, to, campaign_id=None, ad_group_id=None)` | `ACCEPTED` 반응 수를 유형별·예산 일별로 집계(결정의 `owner_id`·`campaign_id`로 소유 범위를 좁힌다) + `billing`의 그날 소진 포인트, 바로 앞의 같은 길이 구간 `previous_totals`. `records`(L3)가 `billing`(L2)을 읽는 방향이라 층 규칙에 맞는다 |
| S2 | 프로필·비밀번호(C6 `/me`, `/me/password`) | `foundation.api.update_profile`, `change_password` | 닉네임·반 검증(가입 규칙 재사용), 현재 비밀번호 확인, 비밀번호 검증기, 감사 로그, 변경 후 현재 세션 유지·다른 세션 무효화 |
| S3 | 광고 만들기(집행)의 원자성 | `campaigns.api.create_ad(user, campaign, ad_group, creative)` | 캠페인·광고그룹·소재를 **한 트랜잭션**으로 만든다(이미지 검증 실패 때 빈 캠페인이 남지 않는다). 기존 개별 서비스를 안에서 재사용 |
| S4 | 광고주 본인 소재 이미지 | `console` 전용 뷰 + `campaigns.get_creative`(소유 확인) + `assets.open_asset` | 공개 `/assets/…`는 `SUSPENDED`·`ENDED` 캠페인 이미지를 404로 막는다. 광고주는 **자기 소재**를 중단 중에도 봐야 하므로 소유 확인 후 같은 보안 헤더(`nosniff`, 캐시 정책)로 내려 주는 별도 경로를 둔다 |
| S5 | 관리자 목록용 조립 | `console/queries/` | 광고 모니터링(캠페인+소재+광고주 닉네임·반+이동 주소 도메인), 재검토 대기 목록. 읽기 전용 조립 |
| S6 | 매체 키 발급·교체·폐기를 화면에서 | 기존 `masters` 서비스 호출 | **평문 키는 응답 한 번만**(`no-store`), 목록에는 `key_id`·상태·만료만 |

### 8.1.3 단계

| 단계 | 내용 | 완료 증거 |
|---|---|---|
| **3-0 기반** | S2·S3 서비스(S1은 2-10)(+단위 테스트·위협 모델 행), 콘솔 공통 틀: 레이아웃·내비게이션·디자인 토큰 CSS(라이트/다크, 모바일 폭), KST/포인트 템플릿 필터, 메시지, `console/errors.py`(예외 → 화면 한 곳), 쪽 나누기, **경계 테스트(뷰에 규칙 없음)** | 서비스 테스트, 경계 테스트가 실제 위반을 잡음(변형 검사), 접근 제어 목록(`EXPECTED_*`) 갱신 |
| **3-1a 관리자: 매체·슬롯·키** | 매체·슬롯 등록·활성/비활성(과금 단위·**`audience`·`max_viewers`** 표시, 과금 단위와 `audience`는 생성 후 변경 불가 안내), 매체 키 발급·교체(유예 선택)·폐기, 키 평문은 한 번만 | 서비스만 호출, 감사 로그, 평문 키가 응답 한 번 외에 어디에도 없음(로그·DB·재조회), 일반 사용자·광고주는 403 |
| **3-1b 관리자: 입찰 정책** | 슬롯별 **새 버전 입력**(현재값이 채워진 폼, 사유 필수, 낙관적 잠금 `expected_version` 숨김 필드, 하한≤기준가≤상한 오류 표시), 이력 열람, **목록에서 여러 슬롯을 골라 같은 값으로 일괄 새 버전**(전부 성공/전부 실패 표시) | 충돌(409 동등)을 화면이 "다른 곳에서 먼저 바뀌었습니다"로 안내, 일괄 동작 원자성, 감사 로그 |
| **3-1c 관리자: 광고 모니터링·중단** | 최근 등록·변경 캠페인 목록 + **소재 썸네일 + 이동 주소 도메인(강조)** + 광고주 닉네임·반, **중단(사유 필수)·해제**, **재검토 대기 목록(해제/반려+답변)**, 관리자 전용 이미지 경로 | 중단 중인 소재도 썸네일 표시, 사유 없이 중단 불가, 광고주 정지 상태가 즉시 반영 |
| **3-1d 관리자: 광고주·포인트** | 광고주 목록(캠페인·소재 수, 업로드 용량 대 상한), 비활성화, 비밀번호 초기화(기존), 지갑·원장 열람, **포인트 조정**(사유 필수·0 밑으로 불가·반대 부호 항목) | 조정이 원장 + 감사 로그, 잔액 = 원장 합계 유지 |
| **3-2a 광고주: 대시보드** | 기간 선택(기본 최근 7일, 직전 같은 길이와 비교), 지표 카드(노출·클릭·전환·소진 포인트 + 증감률), SVG 추세 그래프, 상위 캠페인 표, **포인트 위젯**(잔액·오늘 소진·리셋 시각), **알림 패널**(S5: 중단 사유·반려 답변·기간 종료·예산 소진·잔액 부족·입찰 하한 미만/상한 적용) | 다른 광고주의 수치가 섞이지 않음(격리 테스트), 빈 데이터·0 나눗셈 처리, 알림은 상태에서 계산 |
| **3-2b 광고주: 캠페인** | 목록(상태 배지, **ON/OFF 토글**, 기간, 일예산, 오늘 소진, 지표, `SUSPENDED`는 토글 비활성+사유), 상세(일예산·기간 수정, 종료 버튼은 되돌릴 수 없음 경고), 광고그룹 목록 | `ENDED`·`SUSPENDED` 규칙을 화면이 서비스 오류로만 표시(뷰에 규칙 없음), 타인 캠페인 404 |
| **3-2c 광고주: 광고 만들기** | 단계 제목이 있는 **하나의 폼**: ① 과금 단위 카드 → ② 캠페인(이름·기간·일예산) → ③ 광고그룹(이름·게재 위치 체크 목록(매체별 묶음·하한~상한·기준가, 단위가 다른 위치는 비활성)·입찰) → ④ 소재(이미지·제목·이동 주소, 규격 안내, 미리보기) → ⑤ 확인 후 집행. 입찰 칸 아래 **위치별 적용 결과**(입력은 막지 않음) | `create_ad` 원자성, 중복 제출 방지(한 번 쓰는 폼 토큰 + PRG), 이미지 거절 사유 표시, 쿼터 초과 안내 |
| **3-2d 광고주: 광고그룹 상세** | 게재 위치별 적용 결과, **입찰 변경 이력**(버전 목록)과 새 입찰(낙관적 잠금 충돌 안내), 위치·ON/OFF 수정(과금 단위 불변 안내), 소재 미리보기·제목/주소 수정·이미지 교체(S4) | 입찰은 추가만, 충돌 안내, 교체한 과거 이미지 보유 규칙은 서비스 그대로 |
| **3-2e 광고주: 포인트** | 잔액, 원장 내역(최신순 커서 쪽 나누기, 지급·과금·조정, 과금은 캠페인 이름과 함께), 오늘 소진 | 커서 이동, 타인 원장 비노출 |
| **3-2f 광고주: 내 정보** | 닉네임·반 수정, 비밀번호 변경(S2) | 현재 비밀번호 틀리면 거절, 변경 뒤 다른 세션 무효 |
| **3-3 마무리** | 접근 제어 전수(관리자↔광고주 상호 차단, 익명 리다이렉트), 보안 헤더·CSP 위반 없음, 접근성 기본(레이블·키보드·대비), 모바일 폭, 브라우저 확인(캡처), 위협 모델 T38(콘솔 뷰)·T39(관리자 동작) 연결, 종료 점검표 | 브라우저로 주요 흐름 확인, `scripts/check.sh` 통과, 종료 점검표 |

각 단계의 공통 완료 조건: ① 서비스 `api`만 호출(경계 테스트) ② 다른 광고주/권한 없는 역할 접근 테스트 ③ XSS·CSRF 회귀 테스트 ④ 감사 로그가 필요한 동작은 감사 확인 ⑤ 변형 검사 ⑥ 위협 모델 행 ⑦ `scripts/check.sh` 통과 후 커밋.

### 8.1.4 [결정 대기] 착수 전에 정할 것 (제안값으로 진행하면 이 값을 쓴다)

| # | 질문 | 제안 | 이유 |
|---|---|---|---|
| D3-1 | 화면에 JS를 쓰나 | **쓰지 않는다(V1).** 토글·미리보기·페이지 이동은 폼 POST·GET으로. 글자수 카운터 정도만 정적 파일로 나중에 추가 가능 | 엄격한 CSP 유지, 접근성·테스트 단순, 분리 대비(§6.6) |
| D3-2 | 차트 | **서버 렌더 SVG**(라이브러리 없음) | CDN·인라인 스크립트 금지, 의존성 0 |
| D3-3 | 광고 만들기 형태 | **단계 제목이 있는 한 페이지 폼 + 원자적 `create_ad`.** 다중 페이지 위저드(세션 초안)는 하지 않는다 | 초안 저장 상태·고아 객체·중복 제출 위험이 없다 |
| D3-4 | 알림 임계값 | `balance_low`: **잔액 < 활성 입찰의 최대 적용 금액**(노출 불가 상태)이면 경고, 0이면 심각. 설정값으로 최소 기준 포인트 추가 가능 | 숫자 임의 기준보다 "지금 노출이 안 되는가"로 정의 |
| D3-5 | 대시보드 기본 기간 | **최근 7일**(예산 일 경계 기준), 비교는 바로 앞 7일 | C6 `previous_totals`와 일치 |
| D3-6 | 관리자 화면을 어디에 | **Django admin 안**(읽기 전용 모델 + 서비스를 부르는 전용 페이지), 코드는 L4 `console/operator/` | 설계 §5.2 확정, 인증·권한·감사 재사용 |

**하지 않는 것(V1)**: 타겟팅 화면, CSV·엑셀 내보내기, 충전 버튼(C5), 알림 저장·이메일, 다국어, 프론트 분리(C6 JSON 구현), 실시간 갱신.

### 8.1.5 위험과 대응

| 위험 | 대응 |
|---|---|
| 뷰에 규칙이 슬금슬금 들어간다 | 경계 테스트(import 금지)와 리뷰 체크리스트, 규칙이 필요하면 서비스를 먼저 만든다 |
| 화면이 많아 일정이 늘어짐 | 3-1과 3-2를 병행 가능한 묶음으로 나눔(각 단계가 독립 커밋). 3-2c·3-2d(가장 큼)는 단계별 서비스가 이미 있어 화면 작업 위주 |
| 광고주 입력의 XSS·피싱 링크 | 자동 이스케이프 테스트(`<script>`·따옴표·유니코드), `https`만 링크, `noopener`, 관리자 화면의 도메인 강조 |
| 이미지 경로로 타인 소재 노출 | 소유 확인 후에만 내려 주고 다른 광고주·익명은 404(S4 테스트) |
| 중복 제출로 캠페인이 둘 | 한 번 쓰는 폼 토큰 + PRG + 서비스 이름 중복 규칙 |
| 대시보드 집계가 느려짐 | 소유·기간으로 먼저 좁히고(인덱스 `status, received_at`·`decision_id, type`), 150명 규모는 단순 집계로 충분. 필요해지면 일별 요약 테이블(파생값, 재계산 명령)을 둔다 |

---

# 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| Django 6.1에서 axes가 동작하지 않음 | 0-2 게이트, 실패 시 5.2 LTS로 내림 |
| 설정 이름을 기억에 의존해 틀림 | §4의 "구현 시점 확인" 목록 |
| 메타버스 쪽이 재시도를 구현하지 않음 | 2-1에서 매체 담당자와 계약 공유. 못 지키면 "유실 없음"은 수신 이후 구간만 보장된다고 문서에 명시 |
| SQLite 쓰기 직렬화가 부하에서 한계 | **2-6에서 확인함**: 150 동시에서 한계가 보이지 않았다([load-test.md](load-test.md)). 150명을 크게 넘거나 다중 워커·MySQL 전환 때 다시 측정 |
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
| **Step 2 전체** | **승인 (2026-10-08, 외부 검토 `2aa0bf5` — V1 범위: SQLite·로컬 파일 독립 서버)** | §7.1 종료 점검표(사람의 일: 매체 담당자와 계약 공유). 구현: `serving_api`·`records`(수신함·처리)·`masters`(매체 키) |
| 2-7 슬롯 성격 | 완료 (2026-10-08) | `masters.Slot`에 `audience`(`individual`·`shared`, 만든 뒤 변경 불가, 기본값 없음)·`max_viewers`(`shared`일 때만 1~100000, DB `CHECK` — `NULL`이 `CHECK`를 통과하는 것을 시험이 잡아 `isnull=False` 명시), `create_slot(..., audience="individual", max_viewers=None)`·`SlotView`·관리자 목록. 결정: `records.decide`가 슬롯을 찾은 **뒤** `subject_id`를 검사(개인 필수·일괄 금지, 400 `/subject_id`; 순서는 슬롯 404 → 매체 비활성 403 → 400), 결정에 `audience` 스냅샷과 사람 유무 `CHECK`, 응답·조회에 `audience`. 계약: C1 `Decision.audience` `required`로, 예시·프레임워크 시험 갱신, **C6 `Slot`에 `audience`·`max_viewers` 추가**(광고주가 슬롯 선택 때 본다). 마이그레이션 `masters/0002`·`records/0005`. 새 시험 `tests/test_slot_audience.py` 16개(모델·서비스·결정·API), 변형 8종(변경 불가 검사·두 방향의 `subject_id` 검사·응답의 `audience`·`max_viewers` 타입/개인 검사·스냅샷 값·검사 순서)으로 실패 확인. 기존 시험의 개인 슬롯 결정에 `subject_id` 보강. 테스트 565 → 581. DRD M2·R1·ER 갱신, 위협 모델 T35 ⑩ |
| C1 v1.1 결정·계약 | 완료 (2026-10-08) | 반응 퍼널 규칙(순서·클릭을 거친 전환만·기간·표시 중 5초 창), 일괄 슬롯(`audience`·`max_viewers`), 클릭 출처 = 서버 관측(`click_url`, 매체 `CLICK`은 호환용으로 남기되 판정 제외, 이후 대조용 B안 확장 가능), 퍼널 집계는 광고 서버 담당을 설계 §10에 확정. 계약 `1.1.0-draft`(더하기만 하는 변경, 새 응답 필드는 구현 때 필수로). 슬롯 등급은 설계 §7-12(V1 제외). 구현 계획 §7.2(2-7~2-11, Step 3 전) |
| 2-6 보완 | 완료 (2026-10-08) | 외부 검토 3건(모두 시험 도구): 부하 검사기가 원장 내부 수치만 맞으면 통과 → 각 과금을 결정의 적용 금액(+부족분)·광고주·캠페인·접수 시각·정책과 대조, 수신 확인한 반응의 (매체, 반응 ID)→(결정 ID, 유형) 연결을 저장된 행과 대조(키의 매체 범위 유지), 재전송 시험이 호출마다 `occurred_at`을 새로 만들어 초 경계에서 409가 섞임 → 논리 반응의 ID·본문을 스레드 시작 전에 한 번 만들어 재사용. 변조 사례(금액 31·타 광고주 지갑·타 캠페인·타 접수 시각·타 결정 연결·타 유형)와 부족분의 정상/가짜 구분을 검사기 테스트로 고정, 변형 9종. 게이트에서 발견한 기존 테스트의 간헐 실패(`table is locked`가 재시도 범위 밖의 조회에서 나던 것, 40회 중 1회)도 수정(120회 연속 통과). 테스트 557 → 565 |
| 2-6 동시성 검증 | 완료 (2026-10-08) | `scripts/load_test.py`(임시 파일 SQLite·WAL·`synchronous=FULL`, 실제 미들웨어를 거치는 스레드형 WSGI, 별도 프로세스 `process_reactions`, 계약의 재시도 규칙을 지키는 클라이언트)로 150 동시: 결정 150·반응 150·같은 결정/유형 150(1건만 인정)·같은 reaction_id 150(201 하나)·지속 유입 중 SIGTERM+프로세스 2개+재기동·버스트 초과(429+Retry-After). **수신 확인 전부 저장(유실 0), 이중 과금 0, 잔액=원장 합계, 소진액=원장, 처리 후 `RECEIVED` 0**. 503·재시도 없이 전부 첫 시도 성공. 결정 요청 1건 = 질의 11개, `slot_name` 조회 비용 ≈ 0.1 ms. 요청 제한 수치는 측정 근거로 **유지 확정**. 검사기 자체를 변조 사례로 시험(변형 9종). 시험 중 발견: 처리 프로세스가 신호 처리기 설치 전에는 SIGTERM으로 즉사 → 시작 로그(`started`)를 남겨 준비를 확인. `scripts/check.sh`에 소규모(20 동시) 단계 추가. 결과·한계: [load-test.md](load-test.md). 테스트 548 → 557 |
| 2-5 반응 처리 | 완료 (2026-10-08) | `records/processing.py`(반응 하나 = 트랜잭션 하나: 규칙 → 과금 → 상태), 규칙 체인 `records/rules/`(`known-decision`·`same-media`·**`ad-shown`(추가)**·`once-per-type`, 설정 `REACTION_RULES`, 모르는 이름은 즉시 오류, 규칙을 빼도 근거 없는 보고는 `guard`가 거부), 과금은 결정의 `applied_amount`·`received_at`·`reaction_ref` = `<media_id>:<reaction_id>`(자정 뒤 재처리에서도 접수 일 기준), 같은 결정·유형의 `ACCEPTED`는 DB 부분 유일 제약, 처리 실패는 되돌리고 `attempts` 증가·한도 초과는 `stuck`으로 보고(자동 거부 없음), 수신 직후 한 번 바로 처리(실패해도 접수 응답 불변), 관리 명령 `process_reactions`(`--once`·`--interval`·`--batch`·`--retry-stuck`, 동시에 여러 개 안전). 소스 검사: 과금 호출·반응 상태 변경은 `processing.py`뿐. 테스트: 규칙별·원자성(과금 뒤 실패 롤백)·멱등·자정 뒤 재처리·큐 격리·동시 처리 2개·수신 직후 처리, 변형 검사 11종. 테스트 514 → 543. 위협 모델 T37. **검토 보완(같은 날)**: `same-media`를 설정에서 빼면 타 매체의 보고가 다른 광고주에게 과금되던 것(P1: 결정 존재·매체 소유·광고 있음을 규칙 설정과 무관한 필수 조건 `guard`로 강제, 교체 가능한 정책과 구분해 문서화), SIGTERM 뒤에도 큐를 다 비울 때까지 처리하던 것(반응 사이·배치 사이에서 종료 확인, 남은 것은 `RECEIVED`로 두고 재기동 뒤 재개), `--batch 0` 무한 반복과 옵션 검증 전에 `--retry-stuck`이 상태를 바꾸던 것(옵션을 모두 검증한 뒤 변경, `CommandError`). 조건부 유일 제약의 MySQL 미지원은 전환 시 점검 항목으로 기록. 테스트 543 → 548. 2-6 부하 항목에 같은 결정·유형을 서로 다른 반응 ID로 동시 보고, 지속 유입 중 SIGTERM, 재기동 후 재개 포함 |
| 2-4 반응 수신 | 완료 (2026-10-08) | `records.Reaction`(수신함: `UNIQUE(media_id, reaction_id)`, 원문 `raw` 보존, `RECEIVED`로 시작, 유형·상태·사유 `CHECK`), `PUT .../reactions/{reaction_id}`(**처음 201 / 같은 내용 재전송 200 / 다른 내용 409**, 다른 매체의 같은 ID는 충돌 없음, 없는·남의 결정에 대한 보고도 접수), `GET`(만든 매체·해당 결정 아래만, 아니면 같은 404). **2xx = 커밋됨**: 저장을 바깥 트랜잭션 안에서 하고 커밋 뒤에만 응답(저장·조회·커밋 실패는 503 + `Retry-After`, 재시도하면 처음 접수). 유일 제약 충돌 안전망, 유일 제약 외 무결성 오류는 숨기지 않음. 요청 검증(유형 enum·RFC 3339 UTC 시각·추가 속성 금지·경로 ID 400). 테스트: 계약 대조, 실제 커밋 실패, 스레드 동시 요청(같은 키 10개 → 201 하나, 충돌 요청 9개 → 승자 하나, 서로 다른 20개 전부 저장), 변형 검사 12종. 테스트 480 → 506. 위협 모델 T36. **검토 보완(같은 날)**: 소수 초 7~9자리를 6자리로 절삭해 다른 시각을 같은 재전송(200)으로 인정하던 것(6자리까지만 받고 초과는 400, 계약 `DateTimeUtc`에 문법 명시, 응답은 보낸 정밀도 유지), 시각 정규식의 `\d`가 전각·아라비아 숫자를 받던 것(ASCII 제한, 구현과 계약이 같은 입력을 받는지 대조하는 테스트), 기존 행이 있으면 CHECK 등 다른 무결성 오류도 중복으로 처리하던 것(유일 제약 충돌일 때만). 테스트 506 → 514 |
| 2-3 결정 API | 완료 (2026-10-08) | `POST /decisions`(201 + `Location`, 저장한 뒤에만 응답, 저장 실패 503), `GET /decisions/{id}`(본인 매체만, 형식 틀린·없는·남의 ID는 같은 404), `GET /health`(인증·저장소 접근 없음). 실제 URL `/api/media/v1/` 마운트(`serving_api.views`·`requests`·`urls`), 요청 본문 검증(필수·UUID·추가 속성 금지, 오류를 한 번에 보고). **DRD D-1~D-3 반영**: 꺼진 슬롯은 광고 없음으로 기록·비활성 매체 403·없는/남의 슬롯 404, `context` 저장(50개·4 KiB 바이트·깊이 4·직접 식별자 키 금지), `slot_name`은 응답 때 조회. 모든 응답을 계약에 대조하는 테스트 + 변형 검사 12종(각 규칙을 끄면 실패). 테스트 446 → 474. 위협 모델 T35. **검토 보완(같은 날)**: `context`의 짝 없는 서로게이트가 500이던 것(공통 `parse_json`에서 키·값·중첩 모두 400), 저장 뒤 `slot_name` 조회 실패가 "저장하지 않았다"는 503과 달리 결정을 남기던 것(저장과 응답 조립을 한 트랜잭션으로, 실제 커밋 테스트 포함), 조회 경로가 계약 밖 UUID 표기를 받던 것(같은 404). 변형 검사 5종 |
| PK 규칙 적용 | 완료 (2026-10-08) | 모든 모델의 PK를 UUIDv7로(자동 증가 없음), 버전 행·원장·결정은 UUID 식별자가 PK가 됨, 새 PK 열(`attempt_id`·`log_id`·`ad_group_slot_id`·`creative_image_id`·`wallet_id`·`spend_id`). 원장 `seq`(+`UNIQUE(wallet, seq)`)와 점검·커서 전환, 관리자 정렬은 시각 열. 마이그레이션을 앱별 새 `0001`로 재생성(옛 데이터 복구 단계·테스트 2개 제거). 모델 규약 테스트 추가. 변형 검사 3종(점검의 `seq` 검사·`seq` 계산·PK 기본값). 테스트 443 → 446. DRD D-8 해결 |
| 2-2 매체 인증·요청 제한 | 완료 (2026-10-07) | `masters.MediaKey`(평문 미저장, 발급·유예 교체·즉시 폐기, 감사), `serving_api.auth.media_endpoint`(401+challenge·403·429, 인증 → 요청 제한 → 뷰), 토큰 버킷(프로세스 메모리 한계 명시), `media_key` 관리 명령. 계약 경로의 임시 뷰로 4개 operation의 401·403·429를 계약에 대조. 변형 검사 5종(상수시간 비교·비활성 검사·`WWW-Authenticate`·폐기 키 허용 등) 확인. 테스트 407 → 439(+32). 위협 모델 T34. **검토 보완(같은 날)**: 토큰 버킷이 시각을 잠금 밖에서 읽어 처리 순서가 뒤바뀌면 같은 경과 시간을 두 번 충전(시각 조회부터 저장까지 한 임계 구역으로, 순서 역전 회귀 테스트), 인증 저장소 장애(`OperationalError`)가 500이던 것을 인증·뷰 전체를 감싸는 데코레이터에서 503 + `Retry-After`로 변환(`OperationalError`만, 다른 예외는 가리지 않음), 키 거절 로그 테스트가 비밀값 첫 글자가 `A`일 때(1/64) 정상 키를 만들어 실패하던 것, Bandit 대상에 `serving_api` 추가(`assert` → 명시적 설정 예외), 라이브러리 표 열 수 정리 |
| 2-1 계약 확정 | 완료 (2026-10-07) | 계약 응답 규칙 충돌 해소(2-2의 403 ↔ 2-3의 201), C1 `POST /decisions` 404 추가, 필수 헤더 표시, 요청 제한·전환·title 확정, C3 공유 파일 규칙. 계약 파일 검증·응답 검증 틀(`tests/contract_support.py`, `format` 검사 연결) + C3 provider 계약 테스트. **Step 1 마이그레이션 보완**: 교체된 과거 이미지의 보유 관계를 과거 결정·감사 로그로 복구(records 0003). 테스트 376 → 400(+24). **검토 보완(같은 날)**: 조회 두 API의 403 계약 누락, 쿠키 금지 검사가 `response.cookies`를 놓침, Problem 본문 `status` ≠ HTTP 상태 허용, 401 `WWW-Authenticate` 필수화·형식 확정, 304·204 본문 금지 검사, `Retry-After`는 ASCII 숫자만(각각 변형 검사로 실패 확인). 테스트 400 → 407(+7) |
