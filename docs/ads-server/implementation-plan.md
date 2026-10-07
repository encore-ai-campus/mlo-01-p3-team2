# 광고 서버 구현 계획

> Status: Approved (2026-10-07 `intake/`에서 승격). 구현은 `apps/ads_server/`에서 진행하며 진행 상태는 §10에 기록한다.
> 작성: 2026-10-07
> 기준 문서: [ads-server-design.md](ads-server-design.md) (구조·계약·결정), [console-ui-benchmark.md](console-ui-benchmark.md) (화면)
> 상세도: **Step 0은 구현 수준으로 상세**, Step 1~2는 개요, Step 3~5는 요약. 뒤 단계는 앞 단계 결과에 따라 바뀔 수 있어 그때 상세화한다.
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
Step 3  화면 (Step 1 이후. 3-1 관리자와 3-2 광고주는 서로 독립)
Step 4~5  Raw 수집 → Kafka (Step 2 이후)
```

| 병렬로 나눠 맡을 수 있는 지점 | 조건 |
|---|---|
| 0-5(`assets`)와 0-2~0-4 | 0-1(골격) 이후. 서로 import하지 않는다 |
| 1-4(`engine`)와 1-1·1-2·1-3 | `engine`이 정의하는 `Candidate`·`SelectionPolicy` 시그니처만 먼저 합의 |
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
| `PyYAML` | 계약 파일(`serving.openapi.yaml`) 로드 | 2-1 | 계약 테스트용 |
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
2. **재인코딩**: 디코딩한 뒤 **새로 인코딩해서 저장**한다(EXIF·ICC·텍스트 청크 제거, 위치 정보 등 개인 정보 방지). JPEG은 품질 고정, PNG는 최적화. 원본 바이트를 그대로 저장하지 않는다.
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

# 6. Step 1: 도메인 코어 (개요)

상세 계획은 Step 0 종료 후 작성한다. 지금 정해 둘 것만 적는다.

| 단계 | 모듈 | 핵심 산출물 | 완료 증거(요지) |
|---|---|---|---|
| 1-1 | `masters` | `Media`, `Slot`(과금 단위 고정), `BidPolicy`(버전 추가, `floor≤base≤cap` DB 제약+서비스 검증) | 제약 위반 거부, 동시 버전 저장 한쪽 실패 |
| 1-2 | `campaigns` | `Campaign`(일예산), `AdGroup`(슬롯 M:N, 과금 단위 고정), `Creative`, `Bid`(버전), **`ReviewRequest`(재검토 요청)**, 상태 전이 표 한 파일, 슬롯별 적용 금액·노출 자격 계산 함수, **`assets` 서빙 가능 여부 함수(`is_asset_servable`) 제공** | 설계 §4.6 예시(30 → 30/20/제외) 통과, 단위 불일치 거부, 중단된 캠페인 이미지 404 |
| 1-3 | `billing` | `Wallet`, `LedgerEntry`(추가 전용), 일 소진액(원장에서 재계산 가능), 예산 일 경계 함수, `ChargePolicy`(`by-unit/v1`), 가입 지급 | 잔액=원장 합계, 0 밑으로 안 내려감, 일 경계 설정 변경 후 재계산 일치 |
| 1-4 | `engine` | `Candidate`·`SelectionPolicy`·`Selection`, 자격 필터(상태·기간·하한·예산·잔액), `highest-bid/v1`(동점 무작위), 이름 → 구현 등록 | DB·Django 없이 판정표·동점 분포·`subject_id` 무관·정책 이름 교체 테스트, import 금지 테스트 |
| 1-5 | `records` | `Decision`(불변 스냅샷: 후보·적용 금액·슬롯·두 버전·알고리즘 이름·`trace`), 결정 유스케이스 | 입찰·정책·소재를 수정해도 과거 결정이 변하지 않음 |

**Step 1 시작 전에 정할 것**
- `Candidate` 필드 목록(1-4가 정의하고 1-5가 채운다). 병렬 작업의 합의점이므로 1-1 전에 확정한다.
- **C6 초안 리뷰**(`contracts/console.openapi.yaml`): `campaigns`·`billing` 서비스 `api`의 함수와 반환 구조가 이 계약의 자원·규칙(입찰 추가만·`expected_version`·과금 단위 고정·정지 중 제한·쿼터·소유권 404·`effects` 계산)과 일치하도록 1-2 시작 전에 확정한다.
- 가입 지급 포인트 양(설정값, 설계 §7-2), 광고그룹당 소재 수(V1은 1개로 확정, 설계 §10).
- **Step 0 결과 반영**: 가입 흐름이 1-3에서 `billing` 지급을 호출하도록 `console` 가입 흐름을 확장한다(`foundation` → `billing` 방향 의존이 생기지 않게 `console`이 두 `api`를 순서대로 호출).

---

# 7. Step 2: Serving API (개요)

| 단계 | 핵심 | 완료 증거(요지) |
|---|---|---|
| 2-1 | **계약 확정**: `contracts/serving.openapi.yaml`(초안 작성됨, 설계 §3). `openapi-spec-validator`로 파일 검증, **provider 계약 테스트 틀**(`PyYAML`+`jsonschema`로 실제 응답을 계약 스키마에 대조) | 검증기 통과, 매체 쪽 담당자와 공유(재시도·`reaction_id`·접수/처리 분리 약속 포함) |
| 2-2 | 매체 인증(공유 키 `X-Media-Key`, 해시 저장·상수시간 비교·교체), 매체별 요청 제한. 인증은 입력 검증보다 먼저. **실패는 401, 비활성 매체는 403, 제한 초과는 429 + `Retry-After`** | 인증 실패·제한·키 교체 테스트 |
| 2-3 | `POST /decisions`(**201 + `Location`**, 광고 없음도 201), `GET /decisions/{id}`(**본인 매체만, 아니면 404**), `GET /health`. **저장 뒤에만 `decision_id` 응답** | 계약 테스트, 저장 실패 시 `decision_id`가 나가지 않음, 다른 매체의 결정은 404 |
| 2-4 | `PUT /decisions/{id}/reactions/{reaction_id}`(inbox): 원문 보존 + **(매체, `reaction_id`) 유니크** + `RECEIVED`를 한 트랜잭션에, **저장 뒤 2xx**(**201 처음 / 200 같은 내용 재전송 / 409 같은 ID 다른 내용**), 잠금·장애 시 503 + `Retry-After` | 중복·충돌(409)·저장 실패 테스트, 원문 보존, 다른 매체가 같은 `reaction_id`를 써도 충돌 없음 |
| 2-5 | 반응 처리(+ `GET .../reactions/{reaction_id}`로 결과 조회, 본인 매체만): 별도 트랜잭션, 규칙 체인(`known-decision`·`same-media`·`once-per-type`), `ChargePolicy` 과금, `ACCEPTED`/`REJECTED`, **`process_reactions` 재처리 명령** | 타 매체 거부, 유형별 1회, 거부 반응 보존, 처리 중 실패 후 재처리해도 이중 과금 없음 |
| 2-6 | **동시성 검증**: 150개 동시 결정·150개 동시 반응 | 수신 확인한 건 전부 저장, 유실 0, 이중 과금 0, 잔액=원장 합계 |

**Step 2 시작 전에 정할 것**: 계약 초안 리뷰(요청 제한 수치, `title` 최대 길이), 전환(CONVERSION)의 정의(설계 §7-3), `process_reactions` 실행 방식(설계 §7-9), 매체 쪽 재시도 구현 여부 확인.

---

# 8. Step 3~5 (요약)

| 단계 | 내용 |
|---|---|
| Step 3-1 | 관리자(Django admin): 입찰 정책 새 버전 입력과 **일괄 입력 동작**, 매체·슬롯, 광고 모니터링(썸네일·이동 주소 도메인), 중단/해제(사유), **재검토 대기 목록(해제/반려)**, 광고주 비활성화·비밀번호 초기화, 포인트 조정, 감사 로그 열람 |
| Step 3-2 | 광고주 콘솔: 대시보드(포인트 위젯), 캠페인·광고그룹 목록, 광고 만들기(단계형), **정지 사유·재검토 요청 버튼**, 포인트 내역, 내 정보. **콘솔 뷰에 비즈니스 규칙을 두지 않는다**(설계 §6.6). **규칙의 원본은 `contracts/console.openapi.yaml`(C6 초안)** — 서비스가 이 규칙을 지키고 화면은 그대로 따른다 |
| Step 4-1 | outbox + `EventSink`(JSONL), 이벤트 스키마(C2) 확정 |
| Step 5 | Kafka sink + relay, C4 Insight 입력 방식 결정과 최소 수신, 재처리·백필 |

---

# 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| Django 6.1에서 axes가 동작하지 않음 | 0-2 게이트, 실패 시 5.2 LTS로 내림 |
| 설정 이름을 기억에 의존해 틀림 | §4의 "구현 시점 확인" 목록 |
| 메타버스 쪽이 재시도를 구현하지 않음 | 2-1에서 매체 담당자와 계약 공유. 못 지키면 "유실 없음"은 수신 이후 구간만 보장된다고 문서에 명시 |
| SQLite 쓰기 직렬화가 부하에서 한계 | 2-6 부하 테스트로 확인, 한계가 보이면 설계 §7-10(DB 전환)로 |
| Step 1이 커서 일정이 늘어짐 | 1-3(`billing`)·1-4(`engine`)를 병렬로 분담 |
| 열린 결정이 구현 중 바뀜 | 설계 문서를 먼저 고치고, 정책 변경 지점(R8)은 설정·파일 하나로 닫혀 있다 |

---

# 10. 진행 상태

| 단계 | 상태 | 비고 |
|---|---|---|
| 승격 | 완료 (2026-10-07) | `intake/` → `docs/ads-server/`, 구현은 `apps/ads_server/` |
| 0-0 위협 모델 | 완료 (2026-10-07) | [threat-model.md](threat-model.md): 위협 26건, 0-1~0-6 모두 대응 행 있음 |
| 0-1 골격·설정·User | 완료 (2026-10-07) | 테스트 26개, `runserver` 확인, WAL·`synchronous=FULL` 확인. `check --deploy` 경고 5건 기록(README) |
| 0-2 계정·인증·세션 | 완료 (2026-10-07) | 테스트 59개(보안 태그 33개) 통과, 브라우저로 가입→로그인→로그아웃 확인. **Django 6.1 / axes 게이트 통과**(설계 §9 기록) |
| 0-3 접근 통제 | 완료 (2026-10-07) | 테스트 79개 통과. URL 전수 점검이 보호 없는 URL·예상 밖 공개 뷰를 잡는 것을 의도적 변조로 확인 |
| 0-4 HTTP 보안 | 완료 (2026-10-07) | 테스트 106개(보안 태그 80개) 통과, `check --deploy` 경고 0(W021만 사유를 적어 의도적으로 끔), 실제 응답 헤더·admin 화면 CSP 동작을 브라우저로 확인 |
| 0-5 assets | 완료 (2026-10-07) | 테스트 144개(보안 태그 118개) 통과. 실제 이미지를 서비스 함수로 저장→서버에서 200/304/404 확인, 브라우저로 표시 확인. 업로드 전체 크기 가드(`MaxUploadSizeHandler`) 추가 |
| 0-6 감사·점검 | 완료 (2026-10-07) | 테스트 177개 통과, `scripts/check.sh` 전체 통과(`check --deploy` 경고 0·마이그레이션·테스트·`pip-audit` 취약점 0·`bandit` 이슈 0). 경계 검사(R1·R2·`engine` 순수성·R3)가 가짜 위반 소스를 실제로 잡음을 검증. 브라우저로 5회 실패 잠금·잠금 중 올바른 비밀번호 거부·감사 로그 기록 확인 |
| **Step 0 전체** | **완료 (2026-10-07)** | 아래 종료 점검표 모두 충족. 구현: `apps/ads_server/` |
