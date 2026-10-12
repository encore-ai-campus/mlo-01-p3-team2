# 광고 서버 계약 (매체 서버용 요약)

원본은 [serving.openapi.yaml](serving.openapi.yaml)(C1 Media API, C3 Asset URL, **v1.1**)이고, 이 문서는 **연동하는 쪽이 꼭 알아야 할 것**만 모은 요약이다.
요약과 원본이 다르면 원본이 맞다.

## 한눈에

| 하고 싶은 것 | 요청 | 성공 | 자주 만나는 실패 |
|---|---|---|---|
| 광고 요청 | `POST /api/media/v1/decisions` (`slot_id`, **슬롯 종류에 따라** `subject_id`, 선택 `context`) | **201** + `Location`, 광고가 없으면 `ad: null` | 400 `subject_id` 규칙 위반 · 401 키 없음 · 403 **매체 비활성** · 404 **없는/다른 매체의 슬롯** · 429 |
| 반응 보고 | `PUT /api/media/v1/decisions/{decision_id}/reactions/{reaction_id}` (`type`=`IMPRESSION`·`CONVERSION`, `occurred_at`, 일괄 슬롯은 `subject_id`) | 201 처음 / 200 같은 내용 재전송 | 409 같은 `reaction_id`에 다른 내용 · 429 · 503 |
| **클릭** | 사용자를 **`ad`의 `click_url`로 이동**시킨다(`GET /c/{token}`, 인증 없음). 광고 서버가 클릭을 기록하고 광고주 페이지로 302 | 302 | 404 위조·잘못된 주소 |
| 결과 확인 | `GET .../decisions/{id}`, `GET .../reactions/{reaction_id}` | 200 | 404 없거나 다른 매체의 것 |
| 이미지 | `GET /assets/{해시}.{png\|jpg}` (인증 없음) | 200 / 304 | 404 |

**`/health`·`/assets`·`/c/`를 뺀 모든 요청**에 `X-Media-Key` 헤더(서버 간 전용, 브라우저에 노출 금지). 인증이 필요한 요청은 키가 없거나 틀리면 **401**(`WWW-Authenticate: MediaKey realm="ads-media-api"` 포함), 키는 맞지만 매체가 비활성이면 **403**이다. 모든 응답에 `X-Request-ID`가 붙으니 문의할 때 알려 달라.

## 반응은 곧 과금이므로 유실되면 안 된다

1. 노출·전환을 **감지하는 즉시** 보고한다(모아서 보내지 않는다). **클릭은 보고하지 않는다** — 광고를 누르면 `click_url`로 이동시키고, 그 이동을 광고 서버가 기록한다.
2. `reaction_id`는 **매체가 만든 UUID**다. 감지 시점에 만들고 **재시도할 때 바꾸지 않는다**.
3. **2xx를 받을 때까지 같은 요청을 재시도**한다: 타임아웃·연결 실패·5xx·**429**. 지수 백오프를 쓰고 `Retry-After`가 있으면 그만큼 기다린다.
4. 400 같은 4xx(429 제외)는 재시도해도 소용없다. 409는 `reaction_id`를 새로 만들지 말고 원인을 확인한다.
5. **2xx는 "접수(저장 완료)"** 다. 과금 대상인지는 이후에 판정되고(`RECEIVED` → `ACCEPTED`/`REJECTED`), 결과는 `GET`으로 확인한다.

## v1.1: 슬롯 종류, 클릭, 반응 순서

### 슬롯은 두 종류다 (`audience`)

관리자가 슬롯을 만들 때 정하고 바뀌지 않는다. 결정 응답의 `audience`로 알 수 있다.

| | `individual` (개인) | `shared` (일괄, 전광판처럼 여러 사람이 같은 광고를 봄) |
|---|---|---|
| 결정 요청의 `subject_id` | **필수** | **보내지 않는다**(보내면 400) |
| 결정을 요청하는 때 | 보는 사람마다 | 광고를 띄울 때 한 번 |
| 반응의 `subject_id` | 선택(보내면 결정의 값과 같아야 함) | **필수** — 보는 사람마다 따로 보고 |

- **광고를 바꿀 때마다 새 결정을 요청한다.** 같은 결정으로 다른 광고를 보여 주면 안 된다.
- 일괄 슬롯은 **사람마다** 노출·전환을 보고하고, 사람마다 따로 판정·과금한다.

### 클릭은 광고 서버가 관측한다

- 결정 응답의 `ad` 객체에 있는 `click_url`로 **사용자를 이동**시킨다(새 창, `noopener`). 광고 서버가 클릭을 기록하고 `redirect_url`로 302 보낸다. 매체는 클릭을 보고(`PUT`)하지 않는다.
- 일괄 슬롯의 `click_url`에는 `{subject_id}` 자리가 있다. **클릭한 사람의 `subject_id`로 바꿔 넣는다**(예: `.../c/<토큰>?s=0197a5c0-...`).
- 매체가 `CLICK`을 `PUT`으로 보내도 접수(2xx)는 되지만 **과금·판정에 쓰이지 않고** `REJECTED`(`click_not_reported`)로 끝난다.
- 이동 주소(`redirect_url`)는 결정에 저장된 값뿐이다. 요청으로 바꿀 수 없다.

### 반응은 순서와 기간을 지켜야 인정된다

노출 → 클릭 → 전환 순이다. 일괄 슬롯은 **같은 사람** 안에서 이어져야 한다(A의 노출로 B의 클릭이 인정되지 않는다).

| 규칙 | 내용 | 거부 사유(`reason_code`) |
|---|---|---|
| 클릭은 인정된 노출 뒤 | 노출이 **클릭 접수 후 300초 안에 도착**해야 한다. 제때 도착했는데 아직 처리 전이면 **보류**(`RECEIVED`로 기다림). 기한 뒤에 처음 도착한 노출로는 인정되지 않는다 | 제때 도착한 노출이 없으면 `missing_prerequisite` |
| 전환은 인정된 클릭 뒤 | 클릭이 **전환 접수 시각까지** 생겼어야 한다. 클릭보다 먼저 접수된 전환은 나중에 클릭이 생겨도 인정되지 않는다 | 〃 |
| 클릭은 결정 후 300초 안, 광고가 표시 중일 때 | 같은 슬롯(개인 슬롯은 같은 사람)에 **새 광고의 노출이 도착한 뒤 5초까지**. 새 결정을 받고도 화면에 적용하지 못했다면 기존 광고는 계속 표시 중으로 본다(새 광고를 그렸으면 그 노출을 바로 보고한다) | `window_expired`, `display_ended` |
| 전환은 클릭 후 30일 안 | | `window_expired` |
| 캠페인 종료 전에 수신한 것만 | | `campaign_ended` |
| `occurred_at`이 말이 되는 범위 | 결정 시각 −60초 ~ 수신 시각 +60초 | `invalid_occurred_at` |
| 사람 | 일괄 슬롯은 `subject_id` 필수, 개인 슬롯은 결정의 사람과 같아야 함 | `subject_required`, `subject_mismatch` |

- **보류는 서버가 풀어 준다.** 매체는 다시 보낼 필요 없이 `GET .../reactions/{reaction_id}`로 결과를 확인한다(보류 중에는 `status: RECEIVED`).
- 노출은 늦게 도착해도 괜찮다(재시도 큐). 단 클릭이 이미 보류 기한(300초)을 넘기지 않아야 한다.
- 새 `reason_code`가 앞으로 늘 수 있으니 **모르는 값을 만나도 오류로 처리하지 않는다.**
- 응답에 새 필드가 늘 수 있으니 **모르는 필드는 무시한다.**

## 알아 둘 값

- 요청 본문 최대 16 KiB, `context`는 4 KiB·깊이 4 이하. 사용자를 직접 식별하는 키(`login_id`, `nickname` 등)는 넣을 수 없다.
- `subject_id`는 가명 UUID다(대문자로 보내도 소문자로 저장·응답한다). 같은 `reaction_id`의 재전송은 `subject_id`까지 같아야 한다(다르면 409).
- 요청 제한은 매체별로 결정 150/초(버스트 300), 반응 450/초(600), 조회 150/초(300). 개발용 초기값이며 바뀔 수 있다.
- 응답의 문자열(`title`, `redirect_url`)은 광고주가 입력한 값이다. 화면에 쓸 때 이스케이프한다. 광고를 누르면 **`click_url`로** 새 창(`noopener`)을 연다(`redirect_url`로 직접 이동하면 클릭이 기록되지 않아 클릭과 그 뒤의 전환이 인정되지 않는다).
- 전환(`CONVERSION`)은 **매체가 사전에 정의한 목표 완료**를 보고한다. 클릭을 거치지 않은 전환은 인정되지 않는다.

## 연동 전에 확인해 달라

- 재시도(위 3번)를 구현할 수 있는가? 못 하면 "유실 없음"은 수신 이후 구간만 보장된다.
- `slot_id`로 쓸 UUID를 어떻게 받는가(관리자가 슬롯을 만든 뒤 알려 준다).

## 현재 연동 코드

계약 설명과 실제 구현 범위는 구분한다. 현재 연결 설정·광고 결정 요청·노출 PUT·게임용 Django 연결·미접수 노출 재전송을 구현했다. 개인 슬롯의 발급 소유자와 광고 유무를 확인하고, 첫 노출의 반응 UUID·감지 시각을 게임 DB에 저장하여 중복 알림과 재전송에도 같은 기록을 사용한다. 별도 테스트 게임에서 광고 결정 201과 광고 없음은 확인했지만, GitHub 게임에 아래 설치 절차를 아직 적용하지 않았다. 결과 GET과 판정 저장은 구현했다. 광고 이미지 표시·노출 감지는 공용 JS와 로컬 테스트 게임에 연결했다. 선택적 context 전송은 미구현이다. 자동 재전송에는 마이그레이션 적용과 별도 작업자 실행이 필요하다.

- `scripts/ad_bridge/api/config.py::AdsConfig`: 광고 API 기본 주소, 매체 키, 초 단위 타임아웃을 검증한다. 키는 객체 표현에 포함하지 않는다.
- `scripts/ad_bridge/api/config.py::AdsConfig.from_env(cls, environ: Mapping[str, str] | None = None) -> 'AdsConfig'`: 환경변수에서 설정을 읽는다.
- 필수 환경변수: `ADS_API_BASE_URL`, `ADS_MEDIA_KEY`, `ADS_API_TIMEOUT`. 기본 주소는 `/api/media/v1`까지 포함한다. `.env` 파일은 자동으로 읽지 않는다.

파일별 코드 탐색은 [통합 라우팅 목차](bridge-routing/ROUTING-README.md)에서 시작한다. 구현·설정 파일 33개와 Git 제외 설정 .gitignore를 저장소 상대경로 그대로 문서 34개에 대응시켰으며 테스트 코드는 제외했다. 아래 절은 설치·사용법과 주요 진입점의 요약이다. 삭제 상태인 저장소 루트 README는 복원하지 않았다.

### Git 제외 규칙

루트 [.gitignore](../.gitignore)는 로컬 가상환경 `.venv/`, Python 캐시 `__pycache__/`와 컴파일 결과 `*.py[cod]`를 제외한다. 이미 Git에 등록된 가상환경과 캐시는 이 규칙만으로 추적이 해제되지 않는다. 현재 변경은 제외 설정 추가이며 기존 추적 파일과 로컬 실행 환경은 유지한다. 상세 안내는 [Git 제외 설정 문서](bridge-routing/.gitignore.md)를 참고한다.

### 광고 요청 사용법

HTTP 클라이언트와 응답 타입은 Python 3.12 이상 표준 라이브러리만 사용한다. 게임 연결부의 소유권·중복 검사에는 Django와 게임 DB가 필요하다. 최종 호출자는 기존 GitHub 게임 서버이며, 작은 게임은 검증용이다. 브라우저에서 저수준 클라이언트를 호출하거나 매체 키를 전달하지 않는다.

연동 코드 원본은 `scripts/ad_bridge/`에 모아 둔다. 루트의 이전 ad_bridge 폴더는 이동했으므로 복사본을 따로 유지하지 않는다. 테스트는 이 원본을 import하며, 테스트용 게임 안에 연동 코드를 별도로 작성하지 않는다.

기능별로 `api`(외부 HTTP 계약), `decisions`(결정 발급·소유권 저장), `impressions`(첫 노출·중복 방지), `delivery`(전송·재시도·작업자), `game`(Django 요청·응답)을 나눈다. 한 함수가 서로 다른 책임의 작업을 직접 처리하지 않도록 게임 요청은 서비스에, 서비스는 통신·저장소에 위임한다. 이번 폴더 정리 자체로 새로운 광고 동작을 추가하지 않는다.

호출자의 **`from ad_bridge import AdsClient, AdsConfig, ...` 공개 import는 유지**한다. **`include("ad_bridge.django_urls")`와 기존 게임 HTTP 경로·URL 이름도 유지**한다. django_urls는 game.urls의 app_name·urlpatterns를 내보내는 호환 파일이다. 내부 모듈을 직접 import한 코드나 테스트에서는 아래 새 기능 경로를 사용한다.

### 실제 게임 서버에 가져갈 범위

실제 게임 서버의 manage.py가 있는 폴더 아래로 **scripts 안의 ad_bridge 폴더 전체**를 복사한다. 설정·통신·응답 타입·오류 처리·Django 연결부·모델·마이그레이션이 한 패키지에 있다. 다른 로컬 폴더나 테스트 게임에 의존하지 않는다. __pycache__ 폴더는 복사할 필요가 없다.

```text
ad-bridge/scripts/            ← 여기에서 개발하고 테스트하는 원본
└─ ad_bridge/                ← 이 폴더를 게임 서버로 복사
   ├─ __init__.py           ← 기존 공개 import 유지
   ├─ api/
   │  ├─ config.py          ← 주소·키·타임아웃
   │  ├─ client.py          ← 결정 POST·노출 PUT 한 번
   │  ├─ errors.py          ← HTTP·연결·응답 오류
   │  └─ types.py           ← 광고·결정·반응 응답 값
   ├─ decisions/
   │  ├─ service.py         ← 결정 발급 후 소유권 저장
   │  └─ store.py           ← 결정 소유권 DB 처리
   ├─ impressions/
   │  ├─ service.py         ← 첫 노출 예약·중복 처리
   │  └─ store.py           ← 노출 기록·재전송 일정·전송 임대
   ├─ delivery/
   │  ├─ sender.py          ← 예약한 반응 전송과 결과 저장
   │  ├─ policy.py          ← 지수 대기·Retry-After 정책
   │  └─ worker.py          ← 기한이 된 기록 선택·재전송
   ├─ game/
   │  ├─ views.py           ← 로그인 프로필·CSRF·게임 응답
   │  └─ urls.py            ← 결정·노출 HTTP 경로
   ├─ results/service.py    ← 접수된 노출 판정 조회·저장
   ├─ static/ad_bridge/
   │  ├─ display.js         ← Canvas 이미지 로드·표시·click_url 이동
   │  └─ impression.js      ← 게임이 전달한 노출 조건으로 결정별 최초 관측
   ├─ apps.py               ← Django 앱 등록
   ├─ models.py             ← 발급 소유자·노출·재전송 일정
   ├─ migrations/           ← 테이블 생성·재전송 필드·기존 기록 복구
   ├─ management/commands/dispatch_ad_reactions.py ← 재전송 작업자
   └─ django_urls.py        ← 기존 include를 유지하는 호환 파일

실제 게임 서버/
├─ manage.py
├─ accounts/
├─ campus/
└─ ad_bridge/                ← 복사 후 위치
```

scripts/test·integration_tests·로컬 가상환경·테스트 게임·광고 서버는 게임 서버에 복사하지 않는다. scripts/test에는 기능별 단위 테스트와 별도로 선택하는 임시 DB 저장소 검사가 있다. 아래 Django 연결부는 서버 설정에서 슬롯 UUID를, 로그인 프로필에서 사용자 UUID를 가져온다. 패키지를 복사하는 것만으로 광고가 표시되지는 않으며, 게임 화면의 호출 지점·이미지 표시·노출 감지는 이후 연결할 작업이다.

`results`는 접수 완료된 노출을 한 번 조회하고 판정을 저장한다. `static/ad_bridge`는 AdBridgeDisplay·AdBridgeImpressionDetector를 제공한다. 이미지 로더와 최초 관측을 재사용하고 실제 게임의 좌표·화면 가시성 조건은 게임에서 전달한다.

### feat;#17 게임의 기존 설정에 연결하기

대상은 [로컬에서 확인한 feat;#17 게임 커밋 3e4ccae](https://github.com/encore-ai-campus/mlo-01-p3-team2/tree/3e4ccae44f9cd0098be21a3ebc3378699ccab3d6)이다. 이후 원격 변경은 확인하지 못했다. 이 게임은 Django 5.2 계열을 이미 사용하므로 이 연결부를 위해 별도 Django를 설치하거나 새 계정 모델을 만들 필요가 없다. 기본 패키지 import는 Django에 의존하지 않지만 게임 연결부는 앱 등록과 DB 테이블 생성이 필요하다.

1. 위 패키지를 게임의 manage.py 옆에 복사한다.
2. 기존 config/settings.py의 환경변수 로딩 이후에 슬롯 설정을 추가하고, 기존 INSTALLED_APPS 목록에 앱을 한 번 등록한다. 기존 설정 파일과 앱 목록을 교체하지 않는다.

```python
# 광고 위치는 서버가 정한다. 브라우저에서 받은 슬롯 UUID를 사용하지 않는다.
ADS_SLOT_ID = os.environ.get("ADS_SLOT_ID", "").strip()

# 기존 INSTALLED_APPS 목록을 유지한 채 광고 발급·노출 저장 앱을 추가한다.
INSTALLED_APPS += ["ad_bridge.apps.AdBridgeConfig"]
```

3. 기존 config/urls.py의 urlpatterns에 다음 항목만 추가한다. 게임의 로그인·커뮤니티·웹소켓 경로를 유지한다.

```python
# 기존 파일에 이미 import된 path, include를 사용한다.
path("api/ads/", include("ad_bridge.django_urls")),
```

4. 게임 프로세스 환경 또는 해당 게임의 .env에 네 값을 설정한다. 최신 게임 설정은 .env를 로드하지만 브리지 자체는 환경변수만 읽는다. 실제 키·UUID를 소스에 넣지 않는다.

```dotenv
ADS_API_BASE_URL=http://127.0.0.1:8001/api/media/v1
ADS_MEDIA_KEY=<발급받은 매체 키 원문>
ADS_API_TIMEOUT=5
ADS_SLOT_ID=<같은 매체에 속한 개인 슬롯 UUID>
```

5. 기존 게임·재전송 프로세스를 종료한 상태에서 패키지를 갱신하고, 게임의 manage.py가 있는 폴더에서 마이그레이션을 적용한 뒤 재시작한다. 0002는 재전송 필드를 추가하고 기존 미접수 기록을 처리 대상으로 보존한다. 아래 명령은 실제 게임 설치 시 실행하는 절차이며 단위 테스트 준비 명령이 아니다. accounts의 기존 0005 마이그레이션도 적용되어 있어야 한다. 연결부는 누락된 사용자 UUID를 임의로 새로 만들지 않는다.

```powershell
python manage.py migrate ad_bridge
```

6. 같은 게임 환경변수·DB를 사용하는 별도 터미널에서 재전송 작업자를 실행한다. 게임의 runserver만 켜서는 저장된 실패 기록이 재전송되지 않는다.

```powershell
python manage.py dispatch_ad_reactions
```

게임 측 요청 경로는 **POST /api/ads/decision/** 이다. 로그인 세션과 CSRF 토큰이 필요하다. 기존 게임의 CSRF 미들웨어를 유지하고 같은 출처의 프런트에서 호출한다. 요청 본문의 slot_id·subject_id는 사용하지 않는다. 사용자 식별자는 서버의 request.user.campus_profile.user_uuid에서만 가져오고 매체 키는 광고 서버 요청 헤더에서만 사용한다. POST 한 번당 광고 결정 요청도 한 번이며 자동 재시도하지 않는다.

광고 서버에서 받은 결정의 소유자·슬롯·광고 유무를 게임 DB에 저장한 뒤에만 201을 반환한다. 응답은 decision_id·slot_id·audience·decided_at·request_id와 ad를 담으며, ad는 null 또는 creative_id·title·image_url·click_url이다. 사용자 UUID·매체 키·redirect_url은 브라우저 응답에 넣지 않는다. 광고 없는 응답도 성공이다. 설정·앱 미등록·DB 저장 문제는 503, 프로필 UUID 누락은 409, 광고 서버 HTTP/통신/응답 오류는 502로 구분한다. upstream_status와 request_id로 광고 서버 오류를 확인할 수 있다. 설치 전 발급한 결정은 로컬 소유권 기록이 없으므로 설치 후 새 결정을 요청해야 노출을 보고할 수 있다.

이 흐름은 game.views에서 decisions.service로 위임한다. 결정 서비스는 `AdsClient.create_decision`의 반환값을 decisions.store에 저장한 뒤 반환한다. 저수준 HTTP 클라이언트만 직접 호출하면 게임 DB의 소유권 저장은 수행하지 않는다.

이 연결부는 **개인 슬롯용**이다. 옥상 게시판이 모두에게 같은 광고를 보여주는 공유 슬롯으로 운영된다면, 결정 공유·교체와 사람별 노출 보고를 별도로 설계해야 한다. 지금 개인 슬롯의 의미를 바꾸지 않는다.

### 게임의 첫 노출 보고

게임 측 경로는 **POST /api/ads/decisions/<decision_id>/impression/** 이다. 로그인 세션과 CSRF 토큰이 필요하며 요청 본문은 필요 없다. 게임 화면은 광고가 실제로 보였다고 감지한 즉시 이 경로를 호출해야 한다. 이 구현은 서버에 알림이 처음 도착한 시각을 UTC occurred_at으로 사용한다. 화면에서 감지한 원래 시각을 별도로 검증·전달하는 기능은 아직 없다.

게임 서버는 request.user.campus_profile.user_uuid를 기준으로 자신에게 발급된 개인 결정인지, 광고가 실제로 있는 결정인지 확인한다. 브라우저가 보낸 subject_id·reaction_id·occurred_at 값은 사용하지 않는다. 다른 사용자의 결정이나 없는 결정은 동일한 404로 처리하고 광고 없는 결정은 409로 거절한다.

처음 생성한 노출 기록의 UUID·시각·사용자 값은 게임 DB에 커밋한 뒤 광고 서버에 PUT 한 번을 보낸다. 개인 결정 하나에 노출 기록 하나만 만들며, 동시에 온 요청도 DB 고유 제약으로 구분한다. 동일 결정의 후속 알림은 저장된 기록만 반환한다. 실패했거나 전송 도중 종료된 기록은 아래 재전송 작업자가 같은 요청으로 처리한다. 브라우저의 반복 알림으로 재전송 시간을 앞당기지 않는다.

| 게임 응답 | 의미 |
|---|---|
| 201 | 첫 전송이 접수됐고 반응 본문을 해석했다. |
| 200 | 이미 접수 확인한 기록의 중복 알림이다. 추가 PUT은 없다. |
| 202 | 접수 결과가 아직 미확정이거나, 2xx는 받았지만 본문을 확인하지 못했다. delivery_state를 함께 확인한다. |
| 502 | 첫 전송의 HTTP·통신·응답 오류 또는 자동 전송을 막은 기록이다. |
| 503 | 설정·앱 등록·로컬 DB 문제다. 전송 후 저장 실패일 수도 있으므로 광고 서버 미접수라고 단정하지 않는다. |

응답의 delivery_state는 게임 측 전송 상태이며 SENDING·UNCONFIRMED·ACKNOWLEDGED·BLOCKED를 구분한다. status는 광고 서버의 RECEIVED·ACCEPTED·REJECTED 또는 아직 모르면 null이다. **ACKNOWLEDGED는 접수 확인이며 과금 완료가 아니다.** 2xx 응답 본문이 손상돼도 접수 확인을 유지하고 status는 null로 남긴다. 실제 차감은 광고 서버에서 별도로 판정하며 이 응답에는 차감 금액·잔액이 없다.

### 미접수 노출 재전송

Impression 기록에 시도 횟수(attempts), 다음 시도 시각(next_attempt_at), 최근 오류 코드(last_error), HTTP 오류 상태(last_http_status), 전송 임대 토큰과 만료 시각을 저장한다. attempts는 실제 HTTP 도착 횟수가 아니라 전송을 예약한 횟수다. 예약 직후 프로세스가 종료돼도 증가한 값은 남는다. 기존 버전에서 넘어온 기록의 과거 시도 횟수는 완전하게 복원할 수 없다.

| 결과 | 저장·처리 |
|---|---|
| 연결 실패·타임아웃·5xx·429 | UNCONFIRMED와 다음 시각 저장. 기한이 되면 같은 요청 전송 |
| 4xx(429 제외)·차단된 리다이렉트 | BLOCKED로 보관. 자동 재전송 중단, 409도 새 UUID 생성 금지 |
| 200·201 등 2xx 확인 | ACKNOWLEDGED로 저장하고 PUT 중단. 본문 해석 실패도 접수 확인 유지 |
| 전송 예약 후 종료·결과 DB 저장 실패 | SENDING 기록을 남김. 임대 만료 후 같은 요청으로 복구 |

기본 대기는 실패 완료 시각부터 1·2·4·8초씩 증가하여 최대 300초다. Retry-After가 더 길면 그 값을 최소 대기 시간으로 사용하며 로컬 상한으로 줄이지 않는다. 시도 횟수 초과를 이유로 기록을 삭제하지 않는다. 오류 원문·매체 키는 진단 기록에 저장하지 않는다.

작업자는 기본 한 묶음 최대 100건, 묶음 사이 1초 대기로 실행된다. 처리 대상 하나마다 짧은 DB 트랜잭션에서 임대(기본 60초)를 확보하고 커밋한 뒤 HTTP를 보낸다. 임대 만료나 응답 유실로 같은 요청이 겹칠 수 있으며, 반응 ID·본문을 고정하고 광고 서버의 멱등 규칙을 사용한다. 늦게 도착한 실패가 다른 작업자의 결과를 덮어쓰지 않게 임대 토큰을 확인한다. 늦게 도착한 재시도 대기 시각은 미접수 기록에 더 긴 값으로 보존하며, 접수 확인은 실패보다 우선한다.

```powershell
# 실제 게임의 manage.py 폴더에서 계속 실행
python manage.py dispatch_ad_reactions

# 지금 기한이 된 최대 100건만 처리하고 종료
python manage.py dispatch_ad_reactions --once

# 한 묶음 크기와 조회 간격 조절
python manage.py dispatch_ad_reactions --batch-size 20 --poll-interval 2
```

--once는 미래 재시도 시각까지 기다리지 않는다. 계속 복구하려면 기본 반복 명령을 실행해야 한다. 첫 Ctrl+C는 진행 중인 요청의 결과 저장을 마치고 종료하며, 두 번째 Ctrl+C는 즉시 중단한다. 설정 오류는 작업 확보 전에 종료한다. 반복 모드의 DB 장애는 오류 원문 없이 알리고 다음 주기에 다시 연결하며, --once의 DB 장애는 실패 종료한다.

작업자는 이미 게임 DB에 저장된 노출만 복구한다. 최초 저장 자체가 실패하면 게임 요청은 503으로 실패하고 복구할 기록이 없다. 판정 GET은 별도 refresh_result 서비스로 호출한다. 재전송 명령은 판정 조회나 실제 차감 확인을 수행하지 않는다.

### 저수준 노출 PUT

`AdsClient.report_impression`은 프레임워크나 DB에 의존하지 않는 한 번 전송 함수다. 호출자가 감지 시점에 결정한 reaction_id와 UTC occurred_at을 저장한 뒤 전달해야 한다. 이 함수는 ID 생성·보관·자동 재전송·결과 GET을 수행하지 않는다.

```python
# 저장한 노출의 ID와 시각을 전달한다. 재전송할 때도 이 값을 바꾸면 안 된다.
reaction = client.report_impression(
    decision_id=saved_decision_id,
    reaction_id=saved_reaction_id,
    occurred_at=saved_occurred_at,
    subject_id=player_pseudonymous_uuid,
)
```

최초 201과 같은 보고의 200을 처리한다. subject_id를 생략하면 요청 본문에서도 생략하며, 공유 슬롯 호출자는 계약상 필수인 사용자 UUID를 직접 전달해야 한다. 저수준 함수의 공유 슬롯 지원이 개인 슬롯용 Django 저장소·경로의 공유 슬롯 지원을 뜻하지 않는다.

반응 필수 필드와 결정·반응 ID·유형·사용자·UTC 시각 일치를 검증하고 새 응답 필드·새 reason_code 문자열은 허용한다. HTTP 오류에는 상태·요청 ID·Retry-After를 보관한다. 2xx 확인 후 JSON 파싱·본문 수신 오류는 AdsResponseError.acknowledged=True로 구분한다. 호출자는 이를 미접수로 간주해 자동 재전송하면 안 된다. 키를 응답에 반사하는 서버라도 진단 메타데이터·거부 사유에서 키를 제거한다.

### 게임 화면 연결 전에 남은 사항

최신 게임의 실제 옥상 광고 자리는 dist/rooftop-data.js의 roof-ad-board이고, dist/campus.js에서 이미지를 읽어 Canvas에 그린다. 기존 이미지 로더가 다른 출처 URL을 차단하므로 광고 서버 image_url을 넣기만 해서는 표시되지 않는다. 기존 PNG 저장·클릭 판정이 깨지지 않게 제한된 동일 출처 이미지 전달 또는 CORS를 갖춘 로드를 준비해야 한다. 이미지 프록시·Canvas 변경·화면 노출 감지·위 게임 경로 호출은 아직 구현하지 않았다. 층 전환 화면의 빈 광고 영역도 이번 범위에 포함하지 않는다.

기존 Kafka EventOutbox는 행동 로그 전송용이다. 광고 서버 HTTP 반응 보고가 자동으로 되는 것은 아니며 이번 요청 연결에 Kafka 설정을 추가할 필요는 없다.

```python
from ad_bridge import AdsClient, AdsConfig, AdsHTTPError, AdsResponseError, AdsTransportError

# 실제 값은 실행 환경에 둔다. 설정에는 /api/media/v1까지 포함한다.
client = AdsClient(AdsConfig.from_env())

# 이 두 UUID는 게임 서버가 준비한다. 사용자 ID나 닉네임을 대신 보내지 않는다.
try:
    decision = client.create_decision(slot_id=slot_uuid, subject_id=player_pseudonymous_uuid)
except AdsHTTPError as error:
    # 401·403·404·429·5xx와 요청 ID를 구분한다. 이 함수는 자동 재시도하지 않는다.
    print(error.status, error.code, error.request_id, error.retry_after)
except (AdsTransportError, AdsResponseError):
    # 게임은 광고 요청 실패를 처리하고 계속 동작할 수 있다.
    print("광고를 불러오지 못했습니다.")
else:
    if decision.ad is None:
        print("현재 표시할 광고가 없습니다.")
    else:
        # 화면에서 제목은 이스케이프하고, 클릭은 click_url로 이동시킨다.
        print(decision.decision_id, decision.ad.image_url, decision.ad.click_url)
```

개인 슬롯은 subject_id가 필요하다. 공유 슬롯은 subject_id 인자를 생략하면 JSON 본문에서도 빠진다. 공유 광고의 click_url 안에 있는 사용자 자리표시는 이 모듈이 바꾸지 않고 반환한다. 실제 사용자의 값으로 채우는 것은 게임 서버의 책임이다.

요청 한 번당 POST 한 번만 보낸다. 타임아웃·5xx가 발생해도 결정이 이미 생성됐을 수 있으므로 임의로 재시도하지 않는다. 201 성공의 필수 응답 필드를 검증하고 추가 필드는 무시한다. 광고 없음과 잘못된 JSON·필수 필드 누락은 구분한다. HTTP 리다이렉트는 따르지 않는다. 응답 읽기는 1 MiB까지 허용한다(브리지의 방어 한도이며 광고 서버 계약의 요청 본문 한도와 다르다).

### 코드 탐색

| 파일·심볼 | 역할 |
|---|---|
| `scripts/ad_bridge/__init__.py` | 호출자용 클래스·예외 재노출 |
| `scripts/ad_bridge/api/client.py::AdsClient.__init__(self, config: AdsConfig) -> None` | 설정과 리다이렉트 차단 HTTP 클라이언트 준비 |
| `scripts/ad_bridge/api/client.py::AdsClient.create_decision` | UUID 정규화, 광고 요청 1회, 응답 해석. 전체 시그니처는 표 아래 참조 |
| `scripts/ad_bridge/api/client.py::AdsClient.report_impression` | 저장된 ID·시각으로 노출 PUT 1회, 200·201 및 접수 후 본문 오류 구분 |
| `scripts/ad_bridge/api/client.py::AdsClient._parse_reaction` | 반응 필수 값·요청 일치 검증, 새 필드·사유 허용 |
| `scripts/ad_bridge/api/client.py::_parse_decision` | 응답 필수 값·슬롯·개인/공유 응답·UTC 시각 검증 |
| `scripts/ad_bridge/api/client.py::_NoRedirect` | 인증 헤더를 다른 주소로 전달하지 않도록 리다이렉트 차단 |
| `scripts/ad_bridge/api/errors.py::AdsError` | 통신 예외 공통 부모 |
| `scripts/ad_bridge/api/errors.py::AdsHTTPError` | HTTP 상태·오류 코드·요청 ID·재시도 대기 초 보관 |
| `scripts/ad_bridge/api/errors.py::AdsTransportError` | 연결·타임아웃·응답 수신 중단 |
| `scripts/ad_bridge/api/errors.py::AdsResponseError` | 예상 밖 성공 상태·JSON·응답 스키마 오류, 반응 PUT의 2xx 접수 여부 보존 |
| `scripts/ad_bridge/api/types.py::Ad` | 소재 ID·제목·이미지·연결·클릭 주소 |
| `scripts/ad_bridge/api/types.py::Decision` | 결정 정보, 광고 또는 None, 요청 ID |
| `scripts/ad_bridge/api/types.py::Reaction` | 반응 접수·판정 상태, 사유, 요청 ID. 차감 금액은 포함하지 않음 |
| `scripts/ad_bridge/apps.py::AdBridgeConfig` | 게임 INSTALLED_APPS에 등록할 앱 설정 |
| `scripts/ad_bridge/models.py::IssuedDecision` | 개인 결정의 소유자·슬롯·광고 유무 저장 |
| `scripts/ad_bridge/models.py::Impression` | 결정당 첫 노출 ID·시각·전송 상태·판정 결과·재전송 일정 저장 |
| `scripts/ad_bridge/decisions/service.py::create_decision` | 결정 발급 후 소유권 저장을 완료한 결과만 반환 |
| `scripts/ad_bridge/decisions/store.py::remember_decision` | 결정 소유자 저장, 기존 발급 기록 변경 방지 |
| `scripts/ad_bridge/impressions/store.py::reserve_impression` | 소유권·광고 확인 후 첫 노출과 임대 저장, 고유 제약으로 중복 방지 |
| `scripts/ad_bridge/impressions/store.py::claim_due_impression` | 기한이 된 미접수·임대 만료 기록을 조건부 갱신으로 확보하고 커밋 |
| `scripts/ad_bridge/impressions/store.py::finish_impression` | 현재 임대의 결과 저장·접수 확인 우선·늦은 재시도 대기 보존, ID·시각 불변 |
| `scripts/ad_bridge/impressions/service.py::report_impression_once` | 첫 예약의 커밋 이후 PUT 한 번, 중복은 저장 결과 반환 |
| `scripts/ad_bridge/delivery/sender.py::send_once` | 최초 전송·재전송의 공통 HTTP 호출과 결과·실패 일정 저장 |
| `scripts/ad_bridge/delivery/sender.py::ImpressionReport` | 저장된 반응 기록과 게임에 전달할 안전한 오류 메타데이터 |
| `scripts/ad_bridge/delivery/worker.py::dispatch_due_impressions` | 기한이 된 기록을 제한 수만큼 재전송, 중단 신호 확인 |
| `scripts/ad_bridge/delivery/policy.py::RetryPolicy` | 기본 1초부터 최대 300초까지 지수 대기, Retry-After 최소값 우선 |
| `scripts/ad_bridge/management/commands/dispatch_ad_reactions.py::Command` | 설정 검증·작업자 반복·--once·중단·DB 오류 처리 |
| `scripts/ad_bridge/migrations/0002_impression_retry.py::recover_pending` | 기존 미접수 기록을 동일 ID로 재처리 가능하게 보존 |
| `scripts/ad_bridge/game/views.py::request_decision(request)` | 로그인 프로필 UUID와 서버 슬롯으로 결정 요청 후 소유권 저장 |
| `scripts/ad_bridge/game/views.py::report_impression(request, decision_id)` | 로그인·CSRF 기반 개인 노출 보고, 서버 UUID·시각 사용 |
| `scripts/ad_bridge/game/urls.py` | 기존 URL 이름과 결정·노출 경로 정의 |
| `scripts/ad_bridge/django_urls.py` | 기존 include 경로를 유지하며 game.urls의 app_name·urlpatterns를 내보냄 |
| `scripts/ad_bridge/results/service.py` | GET 판정 조회·동일 노출 검증·기존 판정 갱신 |
| `scripts/test/api/test_client.py::DecisionClientTests` | 외부 서버 없이 요청·응답·오류 처리 검증 |
| `scripts/test/api/test_config.py::AdsConfigTests` | 게임에 복사할 설정 코드의 환경변수·URL·키·타임아웃 검증 |
| `scripts/test/decisions/test_service.py::DecisionServiceTests` | 결정 발급·소유권 저장 순서, 광고 없음 저장, 저장 실패 전파 검사 |
| `scripts/test/api/test_impression.py::ImpressionClientTests` | 노출 PUT·멱등 값·반응 응답·접수 후 오류 단위 테스트 |
| `scripts/test/impressions/test_impression_service.py::ImpressionServiceTests` | 저장소·통신을 대체한 첫 전송·중복·실패 분류 단위 테스트 |
| `scripts/test/game/test_game_impression.py::GameImpressionTests` | DB 없는 로그인·CSRF·소유권·게임 노출 응답 단위 테스트 |
| `scripts/test/storage/test_impression_storage.py::ImpressionStorageTests` | 별도 임시 SQLite DB로 저장·고유 제약·복구 기록을 검사하는 통합 테스트 |
| `scripts/test/delivery/test_retry.py::RetryTests` | 고정 시계로 대기·재전송·오류 분류·중단·임대 복구 단위 테스트 |
| `scripts/test/delivery/test_retry_command.py::RetryCommandTests` | 설정·실행 옵션·반복·중단·DB 장애를 대체 객체로 검사 |
| `scripts/test/storage/test_retry_storage.py::RetryStorageTests` | 임시 SQLite에서 일정 저장·전송 선점·늦은 결과·롤백 검사 |
| `scripts/test/storage/test_retry_storage.py::RetryMigrationTests` | 기존 기록의 0001 → 0002 실제 마이그레이션 검사 |
| `integration_tests/test_provider.py::ProviderDecisionTests` | 광고 서버의 별도 DB와 실제 HTTP로 통합 검증 |
| `scripts/test/game/test_game_adapter.py::GameAdapterTests` | 게임용 요청 연결의 로그인·CSRF·프로필 UUID·응답/오류 경계 검증 |
| `scripts/test/support/django_settings.py` | 게임 연결 단위 테스트에만 사용하는 DB 없는 Django 설정 |
| `scripts/test/run.py::main` | 기능별 단위 테스트와 별도 저장소 통합 테스트 선택 실행 |

시그니처: `scripts/ad_bridge/api/client.py::AdsClient.create_decision(self, slot_id: str | UUID, subject_id: str | UUID | None = None) -> Decision`.

노출 시그니처: `scripts/ad_bridge/api/client.py::AdsClient.report_impression(self, *, decision_id: str | UUID, reaction_id: str | UUID, occurred_at: str, subject_id: str | UUID | None = None) -> Reaction`.

게임 발급 서비스 시그니처: `scripts/ad_bridge/decisions/service.py::create_decision(*, client, store, slot_id, subject_id) -> Decision`.

공통 전송 서비스 시그니처: `scripts/ad_bridge/delivery/sender.py::send_once(*, client, store, record: StoredImpression, policy: RetryPolicy, now) -> ImpressionReport`.

### 검증 실행

단위 테스트 대상은 게임 서버로 가져갈 scripts/ad_bridge 패키지뿐이다. 실제 게임·광고 서버·MySQL·Docker·실제 매체 키가 필요 없다. HTTP·로그인 사용자·저장소를 대체한다. Django는 게임 연결부를 검사하는 라이브러리이며 개발 서버는 실행하지 않는다. all은 DB 없는 단위 테스트만 실행하고, 실제 ORM·마이그레이션 검사는 storage·retry_storage로 별도 선택한다.

테스트 파일도 scripts/test의 api·decisions·impressions·delivery·game·storage 폴더로 나누며, 공통 시계·저장소 대역·Django 테스트 설정은 support에 둔다. results는 GET 계약과 판정 조회 서비스 단위 테스트를 포함한다. 폴더가 바뀌어도 run.py의 기존 기능 그룹 이름과 한 사례 선택 이름은 유지한다.

ad-bridge 가상환경에 테스트 의존성을 한 번 설치하고 전체 단위 테스트를 실행한다. 기존 통신 코드의 실행 의존성은 늘어나지 않는다.

```powershell
cd C:\third-project\ads\ad-bridge
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -B scripts/test/run.py all
```

실행기가 import 경로와 테스트용 Django 설정을 준비하므로 PYTHONPATH를 직접 설정할 필요는 없다. 이미 Django가 설치된 가상환경의 Python으로도 실행할 수 있다. 테스트 사용자 객체는 feat;#17의 프로필 접근 구조를 대체하며 실제 최신 게임을 실행한 통합 검증과는 구분한다.

기능별 또는 한 사례씩 실행할 수 있다. config·request·decisions·impression·impression_service·retry 그룹은 Django 없이도 실행된다. 전체 사례 설명은 [기능별 단위 테스트 안내](../scripts/test/README.md)를 참고한다.

```powershell
# 설정·광고 요청·기존 게임 연결을 각각 검사한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py config
.\.venv\Scripts\python.exe -B scripts/test/run.py request
.\.venv\Scripts\python.exe -B scripts/test/run.py game

# 분리한 결정 발급·소유권 저장 서비스를 검사한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py decisions

# 노출 통신·첫 전송 흐름·게임 노출 경로를 각각 검사한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py impression
.\.venv\Scripts\python.exe -B scripts/test/run.py impression_service
.\.venv\Scripts\python.exe -B scripts/test/run.py game_impression

# 미접수 전송 정책·작업자·관리 명령을 각각 검사한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py retry
.\.venv\Scripts\python.exe -B scripts/test/run.py retry_command

# 한 가지 사례만 선택한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py config timeout
.\.venv\Scripts\python.exe -B scripts/test/run.py request personal
.\.venv\Scripts\python.exe -B scripts/test/run.py game csrf
.\.venv\Scripts\python.exe -B scripts/test/run.py impression send
.\.venv\Scripts\python.exe -B scripts/test/run.py impression resend
.\.venv\Scripts\python.exe -B scripts/test/run.py impression_service duplicate
.\.venv\Scripts\python.exe -B scripts/test/run.py game_impression owner

# 실행 가능한 사례 이름을 확인한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py --list
```

DB 저장 동작은 별도의 통합 테스트다. 아래 명령만 임시 SQLite 테스트 DB를 생성·폐기하고 마이그레이션·고유 제약·기록 재조회·트랜잭션 실패를 확인한다. 실제 게임 DB나 광고 서버 DB를 사용하지 않으며 실제 MySQL 동시 처리 검증까지 대신하지는 않는다.

```powershell
# all에 포함되지 않는 저장소 통합 검사
.\.venv\Scripts\python.exe -B scripts/test/run.py storage
.\.venv\Scripts\python.exe -B scripts/test/run.py retry_storage
```

실제 광고 서버 코드와 HTTP 연결을 검증할 때는 아래처럼 광고 서버의 Python 3.14 가상환경과 테스트 설정을 사용한다. Django가 별도 test DB를 만들고 삭제하므로 테스트 DB 생성 권한이 필요하다. 광고 서버의 기존 DB 접속 설정을 사용하며 개발 DB의 사용자·광고·잔액은 변경하지 않는다.

```powershell
$env:PYTHONPATH = "C:\third-project\ads\ad-bridge\scripts;C:\third-project\ads\ad-bridge"
cd C:\third-project\ads\ads-server\apps\ads_server
.\.venv314\Scripts\python.exe -B manage.py test integration_tests.test_provider --noinput
```

계약 대조 기준: GitHub 게임 dev `3b914b3`, 광고 구현 feat;#8 `7fd1fa8`, 계약 doc;#10 `ecaa1b4` (2026-10-11 fetch 확인). 로컬 serving.openapi.yaml은 해당 GitHub 계약과 줄바꿈 정규화 후 동일하다.

최신 게임 기준은 feat;#17 `3e4ccae44f9cd0098be21a3ebc3378699ccab3d6` (2026-10-11 fetch 확인)이다. 이 버전에는 Profile의 고정 UUID 필드 user_uuid와 기존 계정 값을 채우는 0005 마이그레이션이 있으므로, 서버에서 request.user.campus_profile.user_uuid를 subject_id로 사용할 수 있다. 이전 dev 기준의 ‘UUID 필드 없음’ 설명은 더 이상 적용하지 않는다. 브리지는 계정을 생성하거나 게임 모델을 수정하지 않으며 광고 요청만으로 반응을 만들거나 포인트를 차감하지 않는다.

검증 결과 (2026-10-11): Python 3.12 단위 테스트 10개, 광고 서버 Python 3.14·MySQL 별도 테스트 DB·실제 HTTP 통합 테스트 5개 통과. 통합 테스트에서 광고 결정 저장, 광고 없음, 잘못된 키 401, 개인 슬롯의 사용자 누락 400, 공유 슬롯 응답, 리다이렉트 차단을 확인했다. 광고 요청 후 잔액·오늘 사용액이 그대로이고 반응이 생성되지 않는 것도 확인했다. 사용자는 실제 매체 키를 설정한 별도 테스트 게임에서 ‘요청 성공·광고 없음’ 응답을 확인했다. 실제 GitHub 게임 화면 연결은 아직 검증하지 않았다.

scripts로 이동한 뒤에는 5개 소스 파일의 SHA-256이 이동 전과 같음을 확인하고 단위 테스트 10개를 다시 통과했다. Python 격리 모드에서 scripts 경로만 추가해 패키지 import도 확인했다. 이동 후 사용자도 단위 테스트 10개와 실제 HTTP 통합 테스트 5개를 다시 실행해 OK 결과를 확인했다.

최신 게임용 Django 연결부를 추가한 뒤 기존 단위 테스트 10개와 연결부 테스트 8개를 통과했다. 기존 통신 5개 파일은 변경하지 않았다. 이 8개는 URL include·로그인·POST·CSRF·프로필 식별자 선택·오류 처리를 대체 사용자/통신 객체로 검증한 결과이며 실제 feat;#17 서버 배포·실행 완료를 뜻하지 않는다.

테스트 폴더를 scripts/test로 정리한 시점에는 설정 8개·광고 요청 10개·게임 연결 10개, 총 28개가 통과했다. 그 뒤 첫 노출 보고를 추가하여 impression·impression_service·game_impression 단위 테스트와 별도 storage 통합 검사를 나눴다. 현재 실행기의 all은 DB를 만들지 않는 단위 검사만 선택한다. 광고 서버 실제 HTTP 통합 검사와 최신 게임 배포·광고 표시·노출 이후 실제 차감 확인은 이번 변경의 검증 범위에 포함하지 않는다.

첫 노출 보고 추가 후 검증 결과 (2026-10-11): config 8개·request 10개·game 11개·impression 18개·impression_service 12개·game_impression 17개, **단위 테스트 총 76개 통과**. 별도의 임시 SQLite storage 통합 테스트 **15개 통과**. impression send·impression_service duplicate·game_impression owner의 단일 사례 실행도 각각 통과했다. 기존 테스트 게임 코드는 이번에 갱신하지 않았고 실제 feat;#17 설치·프로덕션 마이그레이션은 실행하지 않았다.

재전송 추가 후 검증 결과 (2026-10-11): retry 19개·retry_command 12개가 추가되어 **단위 테스트 총 107개**, 별도 SQLite storage 15개·retry_storage 17개로 **저장소 통합 검사 32개**가 통과했다. 저장소 검사에는 실제 0001→0002 마이그레이션과 늦은 Retry-After의 조건부 선점 경합 재현이 포함된다. 모델과 마이그레이션의 차이는 없고, 관리 명령 등록·단일 사례 선택도 확인했다. 실제 광고 서버 호출·게임 DB 변경·GitHub 게임 설치는 수행하지 않았다.

기능별 폴더 정리 후 검증 결과 (2026-10-11): 분리한 결정 서비스의 저장 순서·저장 실패·광고 없음 검사 3개를 추가하여 **단위 테스트 110개**, 별도 저장소 검사 storage 15개·retry_storage 17개, **총 142개**가 통과했다. 기존 기능 그룹·사례 이름과 공개 import·게임 URL은 유지한다. 새 decisions 그룹의 save·storage_error·no_ad로 결정 서비스의 각 사례를 하나씩 실행할 수 있다. 이번 변경은 기존 구현을 기능별로 나누고 후속 개발 위치를 마련한 것이며 결과 GET·광고 화면 동작은 추가하지 않았다.


## 접수된 노출 판정 조회

게임 서버에서 로그인 프로필의 가명 UUID를 전달한다. 브라우저가 제출한 사용자 ID를 그대로 쓰지 않는다.

```python
from ad_bridge import AdsClient, AdsConfig
from ad_bridge.impressions import store
from ad_bridge.results.service import refresh_result

# 기존 소유 기록의 ID로 GET 한 번을 수행하고 판정만 저장한다.
record = refresh_result(
    client=AdsClient(AdsConfig.from_env()), store=store,
    decision_id=decision_id, subject_id=request.user.campus_profile.user_uuid,
)
```

접수 상태가 ACKNOWLEDGED인 기록만 조회한다. 기록 부재·다른 사용자에는 DecisionNotFound,
미접수에는 ImpressionNotReady가 발생한다. HTTP·통신·응답 오류와 DB 저장 실패는 호출자에게 전달한다.
조회 실패로 PUT을 보내거나 새 반응을 만들지 않는다. GET 응답의 ID·사용자·종류·시각이 기존 노출과
일치해야 한다. status·reason_code·request_id만 갱신하며 전송 정보는 보존한다.
이미 ACCEPTED 또는 REJECTED라면 늦은 응답으로 덮지 않는다. 새로운 필드·거절 사유는 허용한다.
주기적 조회 작업자·게임 HTTP 경로는 추가하지 않았다. 기존 모델을 사용해 새 마이그레이션은 없다.
반응 응답에는 포인트 차감 금액이 없으므로 실제 차감은 별도 확인해야 한다.

검증: 단위 테스트 126개, storage 15개, retry_storage 17개, result_storage 6개 통과.
실제 광고 서버 대신 HTTP 대역과 임시 SQLite를 사용한다.


## 로컬 테스트 게임의 실제 연결 (2026-10-12)

형제 game-client가 ad_bridge 앱과 마이그레이션을 적용한다. 기존 실제 게임 프로필 기본값은
campus_profile.user_uuid이며 테스트 게임은 ADS_SUBJECT_ID_ATTRIBUTE="player.subject_id"로 설정한다.
공용 게임 경로에 POST decisions/{decision_id}/result/를 추가했다. 로그인·CSRF를 검사하며
사용자 소유의 노출만 조회한다. 미접수 기록은 로컬 전송 상태만 반환하고 이미 확정된 판정은 재조회하지 않는다.
429 조회 응답의 Retry-After는 게임 응답에도 전달한다.

테스트 게임은 공용 static/ad_bridge/display.js와 impression.js를 로드한다. 이미지가 그려진 상태에서
캐릭터 발 위치가 빨간 구역 안에 있고 활성 탭·포커스·전광판 광고 영역의 전체 가시성을 충족하면 노출을 한 번 알린다.
작은 창에서 Canvas 하단이 잘려도 광고 영역이 온전히 보이면 감지한다.
광고 계약에 근접 거리·대기 시간은 없으며 이 조건은 테스트 매체의 정의다.
브라우저는 같은 결정으로 알림 응답 유실을 복구하고 게임 DB에 저장된 뒤에는 재전송 작업자에게 맡긴다.
판정은 5초 간격 또는 새로고침 버튼으로 확인한다. 전광판 클릭은 click_url의 새 창 이동뿐이다.

실제 브라우저에서 이미지 표시·방향키 구역 진입·ACCEPTED 판정을 확인했다.
반응 e22048dd-db09-4dd6-94e9-338ead0ae553의 광고 원장에는 CHARGE -50, balance_after 49950이 있었다.
게임 테스트 20개, 이동·노출 감지 JS 검사, 기존 bridge 단위 테스트 126개가 통과했다.
실행 도구와 로컬 설정은 game-client에 있으며 설치·실행 안내는 [테스트 게임 README](../../game-client/README.md)다.
GitHub 게임에 패키지를 배포한 것은 아니고, 실제 캠퍼스의 Canvas 저장·좌표·클릭 연결은 별도 적용해야 한다.
