# ad-bridge

기존 Django 게임 서버와 광고 서버를 연결하는 개인 슬롯용 광고 연동 패키지다.
광고 요청, 발급 소유권 저장, 최초 노출 보고, 전송 실패 복구, 최종 판정 조회를 제공한다.
게임에 가져갈 코드는 `scripts/ad_bridge`이며, 별도 로컬 테스트 게임으로 실제 광고 표시와 포인트 차감을 검증했다.

## 현재 구현 범위

| 기능 | 현재 동작 |
|---|---|
| 연결 설정 | 광고 API 주소·매체 키·타임아웃·ADS_SUBJECT_SECRET을 환경변수로 읽고 검증 |
| 광고 요청 | 로그인 프로필 UUID에서 HMAC-SHA256으로 광고 전용 가명을 생성해 개인 슬롯 결정 요청. 광고 없음도 정상 처리 |
| 발급 저장 | 결정 ID·내부 owner_id·발급 당시 subject_id·슬롯·광고 유무를 저장한 뒤 게임에 응답 |
| 노출 보고 | 내부 owner_id로 소유권을 확인하고 발급 당시 subject_id·최초 반응 UUID·시각을 저장한 뒤 PUT |
| 중복 방지 | 같은 결정의 후속 알림은 기존 기록 반환. 새 반응을 만들지 않음 |
| 재전송 | 연결 실패·타임아웃·429·5xx에 같은 ID와 내용으로 재전송 |
| 재시작 복구 | DB에 저장한 일정과 만료된 작업 임대로 미접수 기록 복구 |
| 판정 조회 | GET 응답을 검증하고 RECEIVED·ACCEPTED·REJECTED 및 거절 사유 저장 |
| 게임 경로 | 로그인·CSRF를 적용한 결정 요청·노출 알림·판정 조회 POST |
| 공용 화면 코드 | Canvas 이미지 표시·click_url 이동·결정별 최초 유효 노출 감지 |

이 패키지는 광고 서버의 광고 선택·판정·과금 기능을 구현하지 않는다. 포인트 차감은 광고 서버가 수행한다.
2xx 접수 완료와 최종 인정·과금은 별도로 관리한다.

## 문서와 파일 구조

- [코드 탐색 목차](docs/bridge-routing/ROUTING-README.md): 파일·클래스·함수 위치와 역할.
- [기능별 테스트 안내](scripts/test/README.md): 그룹과 단일 사례 실행 방법.
- 광고 요청·반응·이미지·클릭 계약은 광고 서버의 C1/C3 v1.1을 기준으로 구현했다.
  계약 복제본은 현재 이 저장소에 포함하지 않으므로 광고 서버가 관리하는 계약을 함께 확인한다.

```text
ad-bridge/
├─ README.md
├─ docs/bridge-routing/           # 구현 파일별 탐색 문서
├─ integration_tests/            # 광고 서버에서 실행하는 별도 계약 검사
└─ scripts/
   ├─ ad_bridge/                 # 실제 게임에 가져갈 패키지
   │  ├─ api/                    # 설정·HTTP·응답 타입·오류
   │  ├─ decisions/              # 광고 요청·발급 저장
   │  ├─ impressions/            # 최초 노출·소유권·중복·DB 처리
   │  ├─ delivery/               # 전송·재시도 정책·작업자
   │  ├─ results/                # 판정 GET·저장
   │  ├─ game/                   # Django 요청 연결
   │  ├─ static/ad_bridge/       # 광고 표시·최초 노출 감지 JS
   │  ├─ management/commands/    # 재전송 실행 명령
   │  ├─ migrations/             # 최초 스키마·재전송 필드
   │  ├─ models.py
   │  └─ django_urls.py          # 게임 URL include 진입점
   └─ test/                      # 기능별 테스트·대체 저장소·임시 DB 설정
```

## 요청과 저장 흐름

```text
로그인한 게임 사용자
  → 광고 결정 요청
  → 결정 소유권·광고 유무를 게임 DB에 저장
  → 게임 화면에 이미지 표시
  → 화면에서 최초 유효 노출 감지
  → 반응 ID·발생 시각을 게임 DB에 저장
  → 광고 서버 PUT
      ├─ 접수 확인: PUT 재전송 종료
      └─ 일시 실패: DB 일정에 따라 같은 반응 재전송
  → 광고 서버 GET으로 판정 확인
  → 기존 기록의 판정·거절 사유 갱신
```

매체 키는 게임 서버의 요청 헤더에서만 사용한다. 브라우저가 제출한 사용자·슬롯·반응 ID·발생 시각은
게임 연결부에서 사용하지 않는다. 사용자 식별자는 로그인 프로필 UUID를 정규화한 뒤
`HMAC-SHA256(ADS_SUBJECT_SECRET, "ads-subject/v1:" + user_uuid)`의 앞 16바이트를 UUID로 변환한다.
같은 사용자와 같은 비밀은 같은 광고 가명을 사용한다. 결정 발급 시 내부 사용자 UUID인 owner_id와
광고 가명 subject_id를 게임 DB에 별도로 저장한다. owner_id는 소유권 확인에만 사용하고 외부로 전송하지 않는다.
최초 노출은 결정에 저장된 subject_id를 복사하며, 중복 알림·재전송·판정 조회도 저장된 값을 사용한다.
ADS_SUBJECT_SECRET을 교체하면 새 결정의 가명은 바뀌지만, owner_id가 있는 기존 결정의 소유권과 전송 가명은 유지된다.
원본 프로필 UUID를 광고 요청의 subject_id로 전달하지 않는다.
발생 시각은 게임 서버가 최초 알림을 확인한 시각으로 고정한다.

광고 클릭은 반환된 click_url로 이동시킨다. CLICK PUT을 보내거나 redirect_url로 직접 이동하지 않는다.

## 기존 게임에 설치

### 1. 실행 환경과 패키지

Python 3.12 이상을 사용한다. HTTP 클라이언트 자체는 표준 라이브러리로 동작하며,
게임 연결·DB 저장·관리 명령에는 Django가 필요하다. Django 5.2 계열에서 검증했다.

`scripts/ad_bridge` 폴더 전체를 게임의 manage.py 옆에 복사한다.
테스트·별도 테스트 게임·가상환경·캐시는 복사하지 않는다.

### 2. 기존 설정에 추가

게임 설정의 환경변수 로딩 이후에 다음 값을 추가한다.

```python
import os

# 기존 게임 앱 목록에 광고 저장 앱을 한 번 추가한다.
INSTALLED_APPS += ["ad_bridge.apps.AdBridgeConfig"]

# 광고 위치는 서버 설정에서 결정한다.
ADS_SLOT_ID = os.environ.get("ADS_SLOT_ID", "").strip()

# 광고 전용 가명을 만들 때 사용할 게임 프로필 UUID 위치다. 기본값도 이 경로다.
ADS_SUBJECT_ID_ATTRIBUTE = "campus_profile.user_uuid"
```

별도 테스트 게임은 player.subject_id를 사용한다. 실제 게임에서는 해당 게임의 로그인 프로필 경로를 지정한다.
브리지 자체는 .env를 읽지 않으므로 게임의 기존 .env 로딩 또는 프로세스 환경변수를 사용한다.

```dotenv
ADS_API_BASE_URL=http://127.0.0.1:8001/api/media/v1
ADS_MEDIA_KEY=<발급받은 실제 매체 키>
ADS_API_TIMEOUT=5
ADS_SUBJECT_SECRET=<게임 서버만 보관하는 광고 가명 생성 비밀>
ADS_SLOT_ID=<같은 매체에 등록된 individual 슬롯 UUID>
```

광고 서버가 다른 컴퓨터에 있으면 실제 서버 주소로 바꾼다. 매체 키와 ADS_SUBJECT_SECRET을 Git·프런트 코드·로그에 넣지 않는다.
ADS_SUBJECT_SECRET은 비어 있지 않은 UTF-8 문자열이어야 하며 공백·제어 문자를 허용하지 않는다.
설정 누락·오류 시 광고 연결은 HTTP 503·ads_invalid_config로 중단하며 원본 UUID로 대체하지 않는다.
직접 AdsConfig를 생성하는 호출자도 필수 키워드 인자 subject_secret을 전달해야 한다. 두 비밀값은 설정 객체의 repr에서 제외한다.

0003_decision_owner 마이그레이션은 내부 소유자 필드만 추가한다. 기존 결정·반응의 subject_id나 요청 내용은 바꾸지 않는다.
이전 기록의 owner_id는 None으로 남는다. 광고 가명에서 내부 사용자를 역산하거나 원본 UUID 기반 기록으로
자동 간주하지 않는다. 소유자가 확인되지 않은 기록은 게임의 노출 예약·판정 조회에서 제외한다.
기존 기록에 소유권을 연결하려면 신뢰할 수 있는 게임 내부 자료에 따른 별도 이행 방침이 필요하다.
재전송 작업자는 기존처럼 저장된 subject_id를 사용하므로 원본 UUID 기반 미전송 기록의 운영 처리 방침은 별도 확정해야 한다.
401 수동 복구·브라우저 판정 응답 제거는 이번 변경에 포함하지 않는다.

### 3. 기존 URL에 추가

```python
from django.urls import include, path

# 기존 urlpatterns 안에 광고 경로를 추가한다.
path("api/ads/", include("ad_bridge.django_urls")),
```

| 게임 경로 | 역할 |
|---|---|
| POST /api/ads/decision/ | 광고 요청·발급 저장 |
| POST /api/ads/decisions/{decision_id}/impression/ | 최초 노출 알림·전송 |
| POST /api/ads/decisions/{decision_id}/result/ | 로컬 전송 상태와 광고 서버 판정 확인 |

같은 출처의 프런트에서 로그인 쿠키와 CSRF 토큰을 사용한다. 판정 조회 경로도 POST다.
다른 사용자의 기록과 없는 기록은 동일하게 접근을 거부한다.

### 4. DB와 작업자

게임의 manage.py가 있는 폴더에서 실행한다.

```powershell
python manage.py migrate ad_bridge
python manage.py runserver
```

이번 버전에는 0003_decision_owner가 포함되므로 새 코드를 실행하기 전에 migrate를 적용한다.
설치용 함수 연결도 변경됐다. create_decision과 remember_decision에는 내부 owner_id와 광고 subject_id를
별도로 전달하고, 노출 예약·판정 조회에는 subject_id 대신 내부 owner_id를 전달한다.

같은 설정과 DB를 사용하는 별도 터미널에서 재전송 작업자를 실행한다.

```powershell
python manage.py dispatch_ad_reactions

# 반복하지 않고 지금 처리할 한 배치만 실행할 수도 있다.
python manage.py dispatch_ad_reactions --once
```

게임의 runserver만 실행하면 재전송 작업자가 실행되지 않는다.
광고 서버에는 별도로 광고 API 서버와 process_reactions 판정 작업자가 필요하다.

## 재전송·판정 처리 규칙

- 최초 노출 기록은 HTTP 전송 전에 DB에 커밋한다. 저장 실패 시 접수 성공으로 응답하지 않는다.
- 재전송 시 decision_id·reaction_id·subject_id·occurred_at을 유지한다.
- 연결 실패·타임아웃·429·5xx는 재시도한다. 429 이외의 4xx와 리다이렉트는 자동 재시도하지 않는다.
- 대기는 기본 1초부터 지수 증가하며 로컬 상한은 300초다. Retry-After가 더 길면 그 시간을 지킨다.
- 기본 작업 임대는 60초다. 만료된 작업을 복구하고 오래된 실패가 접수 확인을 덮지 않게 한다.
- 2xx를 확인하면 PUT 재전송을 멈춘다. 본문 확인 실패 시 판정은 아직 모를 수 있다.
- 판정 GET 실패로 새 반응이나 PUT 재전송을 만들지 않는다.
- 이미 ACCEPTED 또는 REJECTED인 결과를 늦은 조회 응답으로 덮지 않는다.
- 새 응답 필드와 알 수 없는 거절 사유는 허용한다.

| 전송 상태 | 의미 |
|---|---|
| SENDING | 전송 작업 진행 중 |
| UNCONFIRMED | 접수 미확정, 재전송 대기 |
| ACKNOWLEDGED | 접수 확인, PUT 재전송 종료 |
| BLOCKED | 자동 재전송 중단, 확인 필요 |

광고 서버 판정은 별도 status 필드의 RECEIVED·ACCEPTED·REJECTED다.
반응 GET에는 차감 금액·잔액이 없으므로 실제 포인트는 광고 서버 원장과 광고주 대시보드에서 확인한다.

## 공용 화면 코드와 현재 노출 기준

- [display.js](scripts/ad_bridge/static/ad_bridge/display.js): 이미지 로드·비율 유지·click_url 새 창 이동.
  로딩 실패 시 기존 광고를 유지하고 늦은 로딩은 무시한다.
- [impression.js](scripts/ad_bridge/static/ad_bridge/impression.js): 게임이 전달한 조건으로 결정별 최초 관측만 반환한다.
  광고 영역의 화면 가시성을 계산하며 HTTP를 직접 호출하지 않는다.

현재 테스트 게임은 이미지가 그려짐·캐릭터 발 위치가 빨간 구역 안·활성 탭과 포커스·광고 영역 전체가
화면에 보임을 만족하면 즉시 한 번 보고한다. 게임 Canvas 하단이 잘려도 광고 영역이 보이면 감지한다.
같은 결정으로 계속 머무르거나 나갔다 들어와도 추가 보고하지 않는다.

연속 1초 노출 대기, 광고 면적 50% 기준, 구역 밖 연속 2초 후 재진입을 새 노출로 인정하는 규칙은
논의한 후속 설계이며 아직 구현하지 않았다. 매초 반복 차감하는 코드도 없다.

## 테스트

이 저장소에서 테스트를 실행할 Python 환경을 준비한다. requirements 파일은 현재 저장소에 포함하지 않는다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "Django>=5.2.8,<5.3"

# 실제 서버·매체 키·DB 없이 전체 단위 테스트를 실행한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py all

# 임시 SQLite로 실제 ORM·마이그레이션을 별도 검사한다.
.\.venv\Scripts\python.exe -B scripts/test/run.py storage
.\.venv\Scripts\python.exe -B scripts/test/run.py retry_storage
.\.venv\Scripts\python.exe -B scripts/test/run.py result_storage
```

실행기는 scripts를 import 경로에 추가하므로 PYTHONPATH를 따로 설정하지 않는다.
실제 게임 DB나 광고 서버 DB를 사용하지 않는다.

```powershell
# 기능 전체 또는 한 사례만 실행한다.
python -B scripts/test/run.py result_client
python -B scripts/test/run.py results accepted
python -B scripts/test/run.py results lookup_error
python -B scripts/test/run.py retry due
python -B scripts/test/run.py --list
```

위 python은 Django를 설치한 가상환경의 Python을 사용한다.

| 검사 | 개수 | 검증 범위 |
|---|---:|---|
| all | 126 | 설정·HTTP·결정 저장·노출·재전송·명령·판정·게임 요청 경계 |
| storage | 15 | 최초 저장·소유권·중복·트랜잭션 |
| retry_storage | 17 | 일정·임대·경합·복구·마이그레이션 |
| result_storage | 6 | 판정 저장·전송 정보 보존·확정 판정 보호 |
| 합계 | 164 | 단위 테스트와 임시 DB 검사 |

2026-10-12 README 갱신 시 위 네 그룹을 다시 실행해 모두 통과했다.
임시 SQLite 검사가 실제 MySQL의 동시 처리·부하 검증을 대신하지는 않는다.
integration_tests는 광고 서버의 별도 테스트 환경에서 실행하는 계약 검사이며 위 all에 포함하지 않는다.

## 별도 로컬 테스트 게임에서 확인한 결과

로컬 검증용 game-client는 이 저장소 밖에 있다. 배포 패키지나 브리지 테스트와 구분한다.

- 가입·로그인·방향키 이동·광고 이미지 표시·전광판 클릭·노출 상태·판정 조회를 연결했다.
- 게임 테스트 20개와 이동·광고 표시·노출 감지 JavaScript 검사를 통과했다.
- 실제 브라우저에서 광고 표시 → 구역 진입 → 노출 접수 → ACCEPTED 판정을 확인했다.
- 2026-10-12 검증한 반응의 광고 원장에 CHARGE -50, 차감 후 잔액 49,950포인트를 확인했다.
  이 금액은 해당 테스트 광고의 결과이며 모든 광고의 고정 단가가 아니다.
- 작은 창에서 Canvas 전체 가시성 때문에 보고되지 않던 문제를 수정하고 노출 인정까지 재확인했다.
- 로컬 실행 도구는 Windows PowerShell 5.1과 PowerShell 7에서 사용할 수 있다.

별도 테스트 게임이 함께 있는 로컬 환경에서는 game-client 폴더에서 start-test.ps1을 실행하고
http://127.0.0.1:8004/ 에 접속한다. 이 실행 도구는 게임·광고 서버와 재전송·판정 작업자를 준비한다.
광고 서버의 MySQL 환경과 로컬 연결 설정은 선행되어야 한다.

## 실제 GitHub 게임에 적용할 남은 작업

1. 기존 게임에 패키지·앱·URL·환경변수·마이그레이션을 적용한다.
2. 옥상 roof-ad-board와 기존 Canvas 렌더·클릭 처리에 연결한다.
3. 기존 동일 출처 이미지 제한과 PNG 저장 기능을 유지할 수 있는 제한된 이미지 전달 경로를 준비한다.
4. 실제 게임의 좌표·카메라·층·가시성을 노출 조건에 연결한다.
5. 실제 게임에서 광고 표시 → 노출 → 판정 → 포인트 원장을 검증한다.

현재 게임 연결의 기준은 확인했던 feat;#17 구조이며 이후 원격 변경까지 검증한 것은 아니다.
공유 슬롯의 전역 결정 공유·사람별 반응, CONVERSION 목표 정의·보고,
게임 포인트와 광고 포인트의 이동·충전은 구현 범위에 포함하지 않는다.

## 개발·문서 관리

- 코드 위치는 [라우팅 목차](docs/bridge-routing/ROUTING-README.md)에서 찾는다.
- Python 파일·클래스·함수·시그니처는 routing-doc-sync로 대조한다.
- 역할 설명과 실제 런타임 동작은 정적 참조 일치와 구분한다.
- 소스 파일을 추가·이동·삭제하면 해당 파일 문서와 목차도 갱신한다.
- 가상환경·캐시·실제 인증 키·로컬 DB·실행 로그는 커밋하지 않는다.
