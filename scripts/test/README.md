# 광고 연결 기능별 테스트

`scripts/ad_bridge`의 설정·광고 요청·노출 보고·재전송·게임 서버 연결을 검사한다. 단위 테스트는 HTTP·로그인 사용자·저장소를 대체하며 실제 광고 서버·게임 서버·DB를 켤 필요가 없다. 별도 `storage`·`retry_storage` 그룹은 임시 SQLite DB를 사용하는 저장소 통합 테스트다. 어떤 그룹도 실제 광고 서버로 요청하거나 포인트를 차감하지 않는다.

실행기는 `scripts`를 Python import 경로에 추가한다. `PYTHONPATH`를 직접 설정할 필요는 없다. 이 폴더는 개발용 테스트이며 실제 게임 서버에 복사할 대상은 `scripts/ad_bridge`다.

## 기능별 파일 위치

테스트를 구현 코드와 같은 기능으로 나눴다. 실행 명령의 기존 그룹 이름과 사례 이름은 유지한다.

```text
scripts/test/
├─ run.py                     실행할 그룹·사례 선택
├─ api/                       설정·광고 결정 POST·노출 PUT
│  ├─ test_config.py
│  ├─ test_client.py
│  └─ test_impression.py
├─ decisions/
│  └─ test_service.py         결정 요청 후 소유권 저장
├─ impressions/
│  └─ test_impression_service.py  최초 노출 예약·전송
├─ delivery/
│  ├─ test_retry.py           재전송 일정·복구
│  └─ test_retry_command.py   작업자 실행 명령
├─ game/
│  ├─ test_game_adapter.py    게임의 광고 요청 경로
│  └─ test_game_impression.py 게임의 노출 보고 경로
├─ storage/
│  ├─ test_impression_storage.py
│  └─ test_retry_storage.py
├─ support/                  공통 fixture·고정 시계·Django 테스트 설정
│  ├─ impression_fakes.py
│  ├─ clock.py
│  ├─ django_settings.py
│  └─ django_storage_settings.py
└─ results/                  결과 조회 구현 전, __init__.py만 있는 예정 위치
```

다른 테스트 파일에서 도구를 가져오지 않고 공통 fixture는 support에서 가져온다. results에는 아직 실행할 테스트가 없으며 결과 조회 GET도 미구현이다.

## 준비

PowerShell에서 저장소 루트로 이동한다.

```powershell
cd C:\third-project\ads\ad-bridge
```

config·request·decisions·impression·impression_service·retry 그룹은 Python 표준 라이브러리만 사용한다. game·game_impression·retry_command·storage·retry_storage·all 그룹은 Django가 필요하므로 실행할 가상환경에 테스트 의존성을 설치한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
```

이미 Django가 설치된 테스트 게임의 Python을 실행 도구로 사용할 수도 있다. 이 경우에도 검사 대상은 테스트 게임 코드가 아닌 `scripts/ad_bridge`다.

```powershell
..\game-client\.venv\Scripts\python.exe scripts/test/run.py all
```

## 실행 방법

명령 형식은 `python scripts/test/run.py <group> [case]`다. 그룹만 지정하면 그 기능의 테스트를 모두 실행하고, 뒤에 사례 이름을 붙이면 해당 사례 하나만 실행한다. `all`은 단위 테스트 110개만 실행하며 `storage`·`retry_storage`는 제외한다.

| 그룹 | 대상 | DB |
|---|---|---|
| `config` | 연결 환경변수·URL·키·타임아웃 | 사용하지 않음 |
| request | 광고 결정 POST·응답·오류 | 사용하지 않음 |
| `decisions` | 결정 요청 후 저장 순서·저장 실패·광고 없음, 3개 | 저장소 대체 |
| `game` | 로그인 사용자의 결정 요청·저장소 호출 | 저장소 대체 |
| `impression` | 노출 PUT 한 번·멱등 값·응답 | 사용하지 않음 |
| `impression_service` | 최초 전송·중복 알림·전송 결과 분류 | 저장소 대체 |
| `game_impression` | 게임의 로그인·CSRF·소유자·노출 경로 응답 | 저장소 대체 |
| `retry` | 재전송 일정·동일 요청 유지·중단·예약 만료 복구, 19개 | 저장소·시계 대체 |
| `retry_command` | 재전송 명령 옵션·반복 실행·종료·오류 복구, 12개 | 저장소·반복 실행 대체 |
| `storage` | ORM 저장·고유 제약·트랜잭션·기록 재조회, 15개 | 임시 SQLite, 별도 통합 검사 |
| `retry_storage` | 재전송 예약·작업자 충돌·상태 보존·마이그레이션, 17개 | 임시 SQLite, 별도 통합 검사 |
| `all` | 위 단위 테스트 전체, 110개 | 사용하지 않음 |

```powershell
# 실행할 수 있는 기능과 사례 목록
.\.venv\Scripts\python.exe scripts/test/run.py --list

# 설정 기능
.\.venv\Scripts\python.exe scripts/test/run.py config

# 광고 요청 기능
.\.venv\Scripts\python.exe scripts/test/run.py request

# 결정 요청 후 저장하는 서비스
.\.venv\Scripts\python.exe scripts/test/run.py decisions

# 게임 서버 연결 기능
.\.venv\Scripts\python.exe scripts/test/run.py game

# 노출 PUT 기능
.\.venv\Scripts\python.exe scripts/test/run.py impression

# 저장된 첫 노출만 보내는 흐름
.\.venv\Scripts\python.exe scripts/test/run.py impression_service

# 게임의 노출 보고 경로
.\.venv\Scripts\python.exe scripts/test/run.py game_impression

# 재전송 정책과 작업 흐름
.\.venv\Scripts\python.exe scripts/test/run.py retry

# 재전송 명령의 옵션·반복·중단 동작
.\.venv\Scripts\python.exe scripts/test/run.py retry_command

# 전체 단위 테스트 110개: DB를 사용하지 않는다.
.\.venv\Scripts\python.exe scripts/test/run.py all
```

한 가지 사례만 확인하려면 다음처럼 실행한다.

```powershell
# 잘못된 타임아웃 설정을 거부하는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py config timeout

# 개인 광고 요청에 슬롯·사용자 UUID가 정확히 들어가는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py request personal

# 광고 결정이 반환되기 전에 소유권을 저장하는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py decisions save

# 게임 서버의 CSRF 검증 확인
.\.venv\Scripts\python.exe scripts/test/run.py game csrf

# 광고 서버에 보낼 노출 PUT 형식 한 가지 확인
.\.venv\Scripts\python.exe scripts/test/run.py impression send

# 호출자가 같은 기록을 다시 보내면 ID·시각·본문이 유지되는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py impression resend

# 게임의 중복 노출 알림이 광고 서버 PUT을 다시 실행하지 않는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py impression_service duplicate

# 다른 사용자의 결정으로 노출을 보고할 수 없는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py game_impression owner

# 예정 시각에 같은 요청으로 재전송하는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py retry due

# Retry-After가 로컬 대기 상한보다 커도 존중하는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py retry retry_after

# 재전송 명령의 1회 실행만 확인
.\.venv\Scripts\python.exe scripts/test/run.py retry_command once

# Ctrl+C 한 번으로 진행 중인 배치 처리 후 종료하는지 확인
.\.venv\Scripts\python.exe scripts/test/run.py retry_command stop
```

마지막에 `OK`가 나오면 선택한 테스트가 모두 통과한 것이다. 한 사례 안에서 여러 잘못된 입력을 함께 검사하는 경우도 있다. 단위 테스트 통과는 실제 서버 연결이나 광고 표시·과금 성공까지 의미하지 않는다.

기능별 폴더 이동 후 검증 결과: `all`의 단위 테스트 110개, 별도 storage 15개와 retry_storage 17개가 통과했다. 저장소 두 그룹은 임시 SQLite를 생성·폐기한다.

`impression resend`는 **호출자가 저수준 함수를 같은 값으로 다시 호출했을 때**의 검사다. `impression_service duplicate`는 **게임의 중복 알림은 기존 기록만 반환하고 즉시 재전송하지 않는 정책**의 검사다. 재전송·복구 작업자는 별도로 구현되어 있으며 `retry`·`retry_command`에서 검사한다. 2xx 접수를 확인하면 PUT 재전송을 멈춘다. 반응 처리 결과 GET은 results/result_client에서 검사하며, 접수 확인은 인정·과금 완료를 뜻하지 않는다.

## storage·retry_storage — 별도 저장소 통합 검사

실제 게임 DB에 연결하지 않는다. 테스트 전용 SQLite DB를 만들고 마이그레이션과 ORM을 사용한다. `storage`는 소유권 저장·첫 UUID/시각 유지·DB 고유 제약·트랜잭션 실패·기록 재조회를 15개 테스트로 확인한다. `retry_storage`는 재전송 일정과 작업 예약·충돌·복구·마이그레이션을 17개 테스트로 확인한다. 두 그룹 모두 `all`에 포함하지 않는다. 이 검사는 실제 MySQL에서 동시에 실행되는 작업의 부하·잠금 동작까지 입증하지 않는다.

```powershell
# 임시 SQLite로 저장소 전체 검사
.\.venv\Scripts\python.exe scripts/test/run.py storage

# 임시 SQLite로 재전송 저장소와 마이그레이션 전체 검사
.\.venv\Scripts\python.exe scripts/test/run.py retry_storage

# 만료된 전송 예약의 복구 한 가지 검사
.\.venv\Scripts\python.exe scripts/test/run.py retry_storage lease

# 오래된 작업자의 실패가 새 상태를 덮어쓰지 않는지 검사
.\.venv\Scripts\python.exe scripts/test/run.py retry_storage stale_failure

# 기존 DB 기록을 새 재전송 스키마로 옮기는 마이그레이션 검사
.\.venv\Scripts\python.exe scripts/test/run.py retry_storage migration
```

이 테스트를 위해 실제 게임에서 `migrate ad_bridge`를 실행할 필요는 없다. 실제 게임 설치 시에만 앱 등록과 마이그레이션이 필요하며 절차는 [게임 서버 설치 안내](../../docs/README.md)에 있다.

retry_storage의 단일 사례는 다음과 같다. 각 이름을 `python scripts/test/run.py retry_storage <case>`의 마지막에 넣는다.

| 사례 이름 | 확인하는 내용 |
|---|---|
| `reserve` | 최초 시도 횟수와 유효한 전송 예약이 저장된다. |
| `schedule` | 다음 시도 시각·오류 코드·HTTP 상태가 저장 후 재조회된다. |
| `lease` | 전송 중 종료된 작업의 예약 만료 후 같은 이벤트를 다시 확보한다. |
| `terminal` | 접수 확인 또는 영구 오류 기록은 작업자가 가져가지 않는다. |
| `stale_failure` | 오래된 작업자의 실패가 현재 작업자의 결과를 덮지 않는다. |
| `late_retry_after` | 늦은 응답의 긴 대기 시간을 보존하고 조건부 선점 중 일정 변경도 지킨다. |
| `token` | 현재 예약 식별자가 없는 작업자는 새 예약을 완료 처리하지 못한다. |
| `stale_ack` | 이전 작업자의 접수 확인도 보존되며 뒤늦은 실패가 덮지 않는다. |
| `blocked_ack` | 이전에 차단된 기록도 같은 이벤트의 접수 확인이 도착하면 보존한다. |
| `duplicate` | 게임의 중복 알림이 기존 예약을 늘리거나 바꾸지 않는다. |
| `legacy` | 과거 기록에 일정·예약 만료 시각이 없어도 복구할 수 있다. |
| `race` | 조건부 갱신 경쟁에서 진 작업자가 다른 작업자의 예약을 가져가지 않는다. |
| `rollback` | 작업 확보 중 트랜잭션 실패 시 이전 일정이 보존된다. |
| `transaction` | 외부 트랜잭션 안에서 작업을 확보하지 않는다. |
| `clock` | 잘못된 시계·예약 유지 시간을 거부한다. |
| `metadata` | 오류 원문이나 잘못된 HTTP 상태를 진단 정보로 저장하지 않는다. |
| `migration` | 스키마 변경 시 대기 기록은 복구 대상으로 두고 종료된 기록은 유지한다. |

## config — 광고 연결 설정

| 사례 이름 | 확인하는 내용 |
|---|---|
| `valid` | 정상 API 주소와 끝 슬래시·타임아웃을 올바르게 정규화한다. |
| `required_env` | 필수 환경변수가 없거나 비어 있으면 거부한다. |
| `isolated_env` | 전달한 설정 매핑을 바꾸지 않고 프로세스 환경변수와 섞지 않는다. |
| `process_env` | 별도 매핑이 없으면 호출 시점의 광고 환경변수를 읽는다. |
| `url` | 잘못된 경로·사용자 정보·쿼리·제어 문자·포트가 있는 주소를 거부한다. |
| `key` | 공백·제어 문자·비ASCII 매체 키를 거부하고 오류에 키를 노출하지 않는다. |
| `timeout` | 불리언·무한대·숫자가 아닌 값·0 이하 타임아웃을 거부한다. |
| `secret` | 설정 객체를 문자열로 출력해도 매체 키가 드러나지 않는다. |

## request — 광고 서버 요청

| 사례 이름 | 확인하는 내용 |
|---|---|
| `personal` | 개인 광고 요청의 슬롯·가명 UUID·인증 헤더·타임아웃이 정확하다. |
| `no_ad` | 광고 없음 응답을 정상 처리하고 새 응답 필드는 무시한다. |
| `shared` | 공유 광고 요청에서 사용자 UUID를 생략하고 클릭 주소 자리표시자를 보존한다. |
| `uuid` | 잘못된 UUID를 통신 전에 거부한다. |
| `http_error` | HTTP 오류 상태·요청 ID·재시도 대기 시간을 보존하고 임의로 재요청하지 않는다. |
| `error_metadata` | JSON이 아닌 오류도 처리하고 오류 메타데이터에서 키를 숨긴다. |
| `timeout` | 타임아웃·연결 실패·응답 수신 중단을 통신 오류로 처리한다. |
| `success_status` | 예상한 201 JSON 응답이 아닌 성공 상태나 콘텐츠 형식을 거부한다. |
| `schema` | 필수 필드 누락·잘못된 값·요청과 응답의 불일치를 거부한다. |
| `response` | 잘못된 JSON·인코딩·너무 큰 응답·안전하지 않은 URL을 거부한다. |

## decisions — 결정 요청과 소유권 저장

클라이언트와 저장소를 대체해 광고 요청 서비스의 책임만 확인한다. 결정 응답을 게임에 반환하기 전에 사용자의 소유권과 광고 유무가 저장되어야 한다.

| 사례 이름 | 확인하는 내용 |
|---|---|
| `save` | 광고 서버 요청 후 소유권을 저장하고 그 다음에 결정 응답을 반환한다. |
| `storage_error` | 저장 실패를 호출자에게 전달하고 광고 요청을 반복하지 않는다. |
| `no_ad` | 광고가 없는 결정도 저장해 이후 잘못된 노출 보고를 구분할 수 있다. |

## game — 게임 서버 연결

| 사례 이름 | 확인하는 내용 |
|---|---|
| `identity` | 브라우저 입력 대신 서버 슬롯·로그인 사용자 UUID를 쓰고 공개 필드만 반환한다. |
| `no_ad` | 광고가 없는 결정도 정상 응답으로 게임에 전달한다. |
| `login` | 로그인이 필요하며 POST 요청만 받는다. |
| `csrf` | CSRF 토큰이 없으면 거부하고 올바른 토큰은 허용한다. |
| `missing` | 슬롯 설정이나 사용자 UUID가 없으면 광고 서버를 호출하지 않는다. |
| `invalid_config` | 설정 형식 오류를 구분하고 내부 오류 원문을 노출하지 않는다. |
| `http_error` | 광고 서버 HTTP 오류의 상태와 요청 ID를 게임 응답에 전달한다. |
| `network_error` | 통신·응답 오류를 구분하고 키 노출이나 자동 재시도를 하지 않는다. |
| `uuid` | 실제 요청 코드가 잘못된 서버 슬롯·사용자 UUID를 통신 전에 거부한다. |
| `user_switch` | 로그인 사용자가 바뀌면 이전 사용자의 UUID를 재사용하지 않는다. |
| `storage_error` | 발급 소유권을 저장하지 못하면 201 대신 503으로 실패를 알린다. |

## impression — 노출 PUT 한 번

| 사례 이름 | 확인하는 내용 |
|---|---|
| `send` | 고정 ID 경로로 IMPRESSION·감지 시각·서버 매체 키를 한 번 전송한다. |
| `resend` | 호출자가 같은 보고를 재호출하면 경로·본문이 같고 200을 정상 처리한다. |
| `subject` | 선택한 가명 사용자 UUID를 소문자로 정규화해 전달한다. |
| `uuid` | 잘못된 결정·반응·사용자 UUID를 통신 전에 거부한다. |
| `time` | Z가 없는 시각·존재하지 않는 날짜·허용 범위 밖 소수초를 거부한다. |
| `precision` | 소수초 자리수 표기가 달라도 같은 UTC 시각이면 처리한다. |
| `status` | 세 판정 상태·새 필드·새 거부 사유를 처리한다. |
| `required` | 모든 필수 응답 필드 누락을 확인한다. |
| `schema` | 잘못된 필드 타입·유형·날짜를 거부한다. |
| `match` | 응답의 결정·반응·사용자·발생 시각이 요청과 일치해야 한다. |
| `http_error` | 4xx·429·503과 Retry-After를 보존하며 자동 재시도하지 않는다. |
| `network_error` | 접수 확인 전 연결 실패를 별도로 구분한다. |
| `json_ack` | 2xx 뒤 JSON 오류가 나도 접수 확인을 유지한다. |
| `read_ack` | 2xx 뒤 본문이 끊겨도 접수 확인을 유지한다. |
| `body_ack` | 잘못된 Content-Type·너무 큰 본문을 구분하고 접수 확인을 유지한다. |
| `status_ack` | 계약 밖 2xx는 응답 오류이지만 이미 받은 접수 확인은 보존한다. |
| `secret` | 반사된 매체 키를 결과·오류 메타데이터에서 제거한다. |
| `redirect` | 다른 주소로 자동 이동하거나 PUT을 다시 보내지 않는다. |

## impression_service — 첫 전송과 중복 처리

저장소와 광고 클라이언트를 대체하여 첫 예약만 전송하는지, 중복 알림은 기존 기록만 반환하는지, 전송 실패에도 ID·원래 시각을 유지하는지 확인한다. 2xx 본문 오류의 접수 확인과 HTTP·통신 실패 상태를 구분하고 저장소 실패 시 성공으로 응답하지 않는지도 검사한다. 한 사례씩 실행할 이름은 `--list`의 `impression_service` 목록을 사용한다.

## game_impression — 게임의 노출 경로

게임의 `POST /api/ads/decisions/<decision_id>/impression/`을 Django 요청 객체로 검사한다. 로그인·POST·CSRF, 서버 프로필 UUID와 서버 알림 시각 사용, 다른 사용자/광고 없는 결정 거절, 중복·접수·미확정·오류 응답을 각각 확인한다. 브라우저가 보낸 사용자·반응 ID·시각은 신뢰하지 않는다. 한 사례씩 실행할 이름은 `--list`의 `game_impression` 목록을 사용한다.

## retry — 재전송 정책과 복구

시계·저장소·HTTP를 대체하여 실제로 기다리지 않고 19개 사례를 검사한다. 게임의 중복 알림과 작업자의 재전송은 구분한다. 작업자는 예정 시각이 된 미확정 기록이나 만료된 전송 예약만 가져오고, 같은 결정·반응 UUID·사용자·원래 감지 시각으로 전송한다. 예약이 만료됐어도 서버가 지시한 다음 시도 시각 전에는 다시 보내지 않는다.

| 사례 이름 | 확인하는 내용 |
|---|---|
| `due` | 예정 시각 전에는 보내지 않고 시각이 되면 같은 요청을 보내 접수 확인한다. |
| `retry_after` | 서버의 대기 지시가 로컬 백오프 상한보다 길어도 그 시각까지 기다린다. |
| `late_retry_after` | 예약이 만료된 작업자의 429 응답이 늦게 와도 다음 재전송을 지시된 시각까지 미룬다. |
| `backoff` | 실패 횟수에 따라 대기가 늘고 상한을 넘지 않으며 큰 횟수도 처리한다. |
| `zero` | 429의 Retry-After가 0이어도 로컬 백오프를 적용한다. |
| `completed` | 실패한 HTTP가 끝난 시각부터 다음 대기를 계산한다. |
| `reschedule` | 작업자 재전송도 실패하면 증가한 시도 횟수에 맞춰 다시 예약한다. |
| `terminal` | 3xx·재시도 불가 4xx는 새 UUID 발급이나 작업자 재전송 없이 멈춘다. |
| `blocked` | 작업자가 받은 영구 오류를 차단 상태로 집계한다. |
| `lease` | 전송 중 종료된 작업은 예약 만료 후 같은 이벤트로 복구한다. |
| `legacy` | 과거 기록에 일정·예약 정보가 없어도 복구한다. |
| `malformed_ack` | 2xx 뒤 본문이 깨져도 접수 확인을 보존하고 PUT을 멈춘다. |
| `malformed` | 접수 확인 없는 응답 형식 오류는 차단한다. |
| `batch` | 지정한 수만 처리하고 나머지는 다음 실행에 남긴다. |
| `stop` | 중단 신호가 오면 새 작업을 확보하지 않고 진행 중인 작업 뒤에 멈춘다. |
| `save_fail` | 결과 저장 실패 후 예약 만료 전에는 기다리고 만료 후 같은 이벤트로 복구한다. |
| `policy` | 0 이하·불리언·무한대 등 잘못된 대기 정책 값을 거부한다. |
| `invalid_delay` | 잘못된 시도 횟수와 Retry-After 값을 거부한다. |
| `limit` | 잘못된 배치 크기는 작업 확보와 전송 전에 거부한다. |

## retry_command — 재전송 실행 명령

Django 관리 명령의 12개 사례를 검사한다. 실제 재전송 루프·대기·DB 연결은 대체하므로 서버를 켜거나 별도 작업자를 실행할 필요가 없다. 예를 들어 `python scripts/test/run.py retry_command reconnect`는 DB 오류 후 복구 흐름 하나만 검사한다.

| 사례 이름 | 확인하는 내용 |
|---|---|
| `once` | 한 번 실행 옵션으로 기본 크기 배치를 정확히 한 번 처리한다. |
| `options` | 지정한 배치 크기와 반복 간격을 사용한다. |
| `invalid_options` | 잘못된 옵션은 설정 읽기와 처리 시작 전에 거부한다. |
| `config` | 잘못된 광고 설정이면 작업을 확보하지 않고 비밀 원문도 노출하지 않는다. |
| `loop` | 기본 반복 실행은 배치 사이에서 종료 신호를 확인한다. |
| `stop` | 첫 Ctrl+C는 현재 요청의 결과 저장 후 새 요청을 멈추고 원래 신호 처리기를 복원한다. |
| `force_stop` | 두 번째 Ctrl+C는 즉시 종료할 수 있다. |
| `once_db` | 한 번 실행 중 DB 오류는 실패 종료하고 원문을 숨긴다. |
| `reconnect` | 반복 실행 중 DB 오류가 나면 대기·재연결 후 다음 배치를 시도한다. |
| `idle` | 처리할 작업이 없는 배치마다 같은 로그를 반복하지 않는다. |
| `unexpected` | 예상하지 못한 예외나 강제 종료를 삼키지 않는다. |
| `cleanup` | 연결 정리 중 DB 오류도 비밀 원문 없이 처리한다. |


## 결과 조회 검사

```powershell
# GET 요청·응답 계약 검사
python scripts/test/run.py result_client
# 조회 서비스 전체 또는 상태 하나 검사
python scripts/test/run.py results
python scripts/test/run.py results accepted
python scripts/test/run.py results rejected
python scripts/test/run.py results lookup_error
# 임시 SQLite 저장소 검사
python scripts/test/run.py result_storage
```

result_client: request, states, uuid, schema, response, http_error, transport, secret.
results: received, accepted, rejected, owner, pending, lookup_error, mismatch, save_error.
result_storage: save, terminal, owner, pending, failure, race.
각 이름을 그룹 뒤에 붙이면 한 사례만 실행한다. all에는 단위 126개가 포함되며 저장소 검사는 별도다.
기존 storage 15개·retry_storage 17개와 신규 result_storage 6개까지 총 164개 통과.
실제 광고 서버·게임 DB는 사용하지 않는다.
