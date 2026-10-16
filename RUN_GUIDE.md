# 프론트·백엔드 실행 가이드

기준일: 2026-10-15. 아래 명령은 저장소 루트에서 시작하는 PowerShell 기준임.

## 함께 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run-split.py
```

프론트 **8004**, 백엔드 **9003**을 실행함. 브라우저는 [캠퍼스 화면](http://127.0.0.1:8004/)으로 접속함. `run-local.cmd`·`run-develop.cmd`도 같은 실행기를 사용하며, Ctrl+C로 두 서비스를 종료함. 사용 중인 포트가 있으면 기존 서버를 종료하지 않고 실행을 중단함.

```powershell
python run-split.py --frontend-port 8005 --backend-port 9004 --bind 127.0.0.1
```

백엔드는 기본 loopback에만 열고, 프론트 기본 bind는 `0.0.0.0`임. `0.0.0.0`은 접속 주소가 아니라 수신 설정이며 인터넷 공개 주소를 자동으로 만들지 않음.

## 개별 실행

공용 가상환경을 설치한 뒤 백엔드 터미널에서 실행함.

```powershell
cd backend
python manage.py migrate --noinput
python run-campus.py --port 9003 --bind 127.0.0.1
```

다른 터미널에서는 같은 가상환경을 활성화한 뒤 프론트를 실행함.

```powershell
cd frontend
$env:BACKEND_URL = 'http://127.0.0.1:9003'
python manage.py runserver 0.0.0.0:8004
```

각 폴더의 `requirements.txt`로 개별 가상환경을 만들어도 됨. 프론트에는 DB 설정·마이그레이션이 필요 없음. 프론트와 백엔드 각각 자신의 `config` 모듈을 사용하므로 명령은 해당 폴더에서 실행함. 루트 `manage.py`는 백엔드 호환 명령, 루트 `run-campus.py`는 백엔드 단독 실행 명령임.

## 기존 DB와 실행 데이터 사용

실제 DB는 저장소에 포함하지 않음. 새로 클론하면 빈 DB에 마이그레이션만 적용하며 실제 계정 정보는 복사되지 않음.

기존 서버를 종료하고 **db.sqlite3 및 var 폴더를 백업한 뒤** 아래 두 방법 중 하나를 사용함.

- 기존 `db.sqlite3`와 `var`를 `backend/`로 복사하고 백엔드에서 마이그레이션함. 덮어쓰기 전에 대상 데이터도 보존해야 함.
- 백엔드 `.env`의 `CAMPUS_DATA_DIR`를 기존 데이터 폴더의 절대 경로로 지정함. 기존 파일을 옮기지 않고 사용 가능함. 서로 다른 버전의 서버가 같은 DB를 동시에 사용하지 않도록 함.

`CAMPUS_DATA_DIR` 아래의 `db.sqlite3`, `var/board-menu`, 세션 정리 상태를 사용함. 원래 루트에 DB가 있고 루트 실행기를 사용하면 그 루트를 데이터 폴더로 자동 지정해 기존 데이터를 이어 사용함. `CAMPUS_DATA_DIR`를 명시하면 그 값을 우선함.

마이그레이션은 기존 문제·답안·기준정보 ID를 보존하고 필요한 UUID·학습 기준정보·포인트 지갑/원장을 추가함. 기존 사용자 지갑은 0P에서 시작하고 과거 답안은 소급 지급하지 않음. `seed_learning_questions`는 빈 개발 환경에만 필요한 기본 문제 등록 명령이며 운영 중 수정한 문제를 자동으로 재등록하지 않음.

## 환경 변수

- 백엔드: `backend/.env` (`backend/.env.example` 참고).
- 프론트: `frontend/.env` (`frontend/.env.example` 참고).
- 루트 호환 실행기는 기존 루트 `.env`도 읽음. 직접 폴더에서 실행할 때는 해당 폴더의 `.env`를 사용함.
- `.env`, DB, 캐시, 로그, 가상환경은 Git에서 제외함.

| 위치 | 변수 | 기본/용도 |
| --- | --- | --- |
| 프론트 | `BACKEND_URL` | `http://127.0.0.1:9003` |
| 프론트 | `FRONTEND_ALLOWED_HOSTS` | localhost·현재 PC 사설 IP; `.env.example` 복사 시 LAN IP 추가 필요 |
| 프론트 | `FRONTEND_DEBUG`, `FRONTEND_SECRET_KEY` | 개발 화면 설정 |
| 백엔드 | `DJANGO_ALLOWED_HOSTS` | 프론트에서 사용자에게 노출하는 호스트도 포함 |
| 백엔드 | `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS 프론트 등 신뢰할 공개 origin |
| 백엔드 | `DJANGO_DEBUG`, `DJANGO_SECRET_KEY` | 개발/배포 설정 |
| 백엔드 | `CAMPUS_DATA_DIR` | 기본 backend 폴더 |
| 백엔드 | `DATABASE_ENGINE` | 로컬 기본 sqlite; AWS 운영 mysql |
| 백엔드 | `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | 팀 운영 DB 연결 시 설정 |
| 백엔드 | `CAMPUS_LOGIN_MAX_AGE_SECONDS` | 28800: 최대 8시간 |
| 백엔드 | `CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS` | 1800: 비활동 30분 |
| 백엔드 | `CAMPUS_LOGIN_WARNING_SECONDS` | 60: 만료 직전 안내 |
| 백엔드 | `CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS` | 15: 활동 시간 저장 간격 |
| 백엔드 | `CAMPUS_SESSION_CLEANUP_ENABLED`, `CAMPUS_SESSION_CLEANUP_TIME` | 기본 켬·한국 시간 04:00; 만료 세션 하루 한 번 정리 |
| 백엔드 | `LEARNING_POINTS_BEGINNER`, `LEARNING_POINTS_INTERMEDIATE`, `LEARNING_POINTS_ADVANCED` | 정답별 20·50·80P; 변경 후 재시작 |
| 백엔드 | `KAFKA_BOOTSTRAP_SERVERS` 및 인증 변수 | 비어 있으면 DB Outbox 보관만 수행 |
| 백엔드 | `CAMPUS_OUTBOX_IDLE_POLL_SECONDS` | 기본 5초: 빈 Outbox의 최대 조회 간격; 같은 프로세스의 커밋은 즉시 알림 |
| 백엔드 | `CAMPUS_OUTBOX_CONNECTION_MAX_AGE_SECONDS` | 기본 60초: MySQL 발행기 스레드 하나의 연결 재사용 수명; 0이면 재사용 끔 |

HTTP 중계는 로그인 쿠키·CSRF·Origin·원래 Host를 백엔드에 전달함. 프론트가 인증을 다시 판단하지 않음. 백엔드 포트는 프론트 및 신뢰할 인프라에서만 접근하도록 배포함. 공개 HTTPS 환경은 두 서비스 앞의 프록시와 호스트·CSRF·쿠키 설정을 함께 맞춰야 함.

HTTPS를 종료하는 Nginx는 `X-Forwarded-Proto`를 실제 외부 프로토콜로 덮어써야 함. 프론트는 `SECURE_PROXY_SSL_HEADER`로 이를 인식해 백엔드에 같은 프로토콜을 전달함. 해당 헤더를 신뢰하므로 프론트 앱 포트는 루프백 또는 신뢰된 프록시에서만 접근하도록 제한함. 운영 환경의 `/static/`은 Nginx에서 수집된 정적 파일 디렉터리로 연결해야 함. HTTPS 서버 블록에서 이 경로가 빠지면 로그인 CSS·맵 스크립트가 404로 응답함. 배포 후 로그인 페이지 200뿐 아니라 CSS 응답, 로그인 POST, 맵 렌더링과 WSS 연결까지 확인함.

## 내부망 접속

같은 LAN의 사용자는 `http://서버PC의사설IP:8004/`로 접속함. 프론트 bind가 `0.0.0.0`이고 두 서비스의 허용 호스트에 해당 IP가 있어야 함. 필요할 때만 Windows 관리자 권한으로 `allow-lan.cmd`를 실행하면 **프론트 TCP 8004**에 현재 LAN 접속 규칙을 적용함. 포트를 바꾸면 `configure-lan.py --port 변경포트`로 맞춤. 백엔드 9003을 사용자에게 직접 공유하지 않음.

## 학습·포인트·Kafka

답안·성적·지갑·원장·Outbox·재시도 응답을 같은 트랜잭션에 저장함. 동일 사용자의 동일 `submission_request_uuid` 재시도는 이전 응답을 돌려주며 중복 지급하지 않음. 빈칸은 `choice_uuid=null`, 객관식은 실제 선택지 UUID를 기록함.

이동 중 약 5초마다 `position_dirty`인 사용자의 최신 위치를 저장하고, 이전 저장 위치와 층 또는 x/y가 다를 때 `movement_observed` Outbox도 저장함. 방향 변경만 있으면 복원용 방향을 저장하며 Kafka 이벤트를 생성하지 않음. 정지 중에는 새 위치 기록을 만들지 않고, 종료·층 전환·로그아웃·만료는 마지막 변경 위치를 즉시 저장함. 전송 재시도는 동일 이벤트 UUID를 사용함.

브로커에 `raw.account`, `raw.chat`, `raw.board`, `raw.comment`, `raw.content_usage`, `raw.movement`, `raw.points`가 필요함. `quiz_answered`는 **1.1**, 나머지는 **1.0**임. 수신 서비스가 빈칸 답안·포인트 토픽을 지원하는지 확인한 뒤 Kafka 발행을 켬. 이 PR은 플랫폼 발행 측을 연결하며 팀원이 관리하는 기존 수신 파이프라인을 덮어쓰지 않음. 세부 계약은 [KAFKA_TOPICS.md](KAFKA_TOPICS.md) 참고.

`run-campus.py`와 `manage.py runserver` 모두 실제 서비스 프로세스에서 Outbox 발행기를 시작함. 다른 ASGI 실행기로 운영 배포하면 `eventing.publisher.start_outbox_publisher()`의 구동·종료 수명주기를 별도로 연결해야 함. 이 가이드는 제공된 개발 실행기를 기준으로 함. 브로커 장애 시 DB Outbox 대기를 유지하며, 대기량·DB 디스크 공간을 운영에서 관찰해야 함.

빈 Outbox 조회는 0.25초부터 최대 `CAMPUS_OUTBOX_IDLE_POLL_SECONDS`까지 늘어남. `transaction.on_commit()` 알림은 저장 성공 후에만 발행기를 깨우며, 다른 프로세스에서 작성한 이벤트는 최대 조회 간격 안에 발견함. MySQL 연결 옵션은 발행기 스레드의 복사본에만 적용함. HTTP·WebSocket은 `CONN_MAX_AGE=0`을 유지하고, 발행기의 연결 수명 초과·DB 오류·종료 시 연결을 정리함. Kafka ACK 후 완료 표시와 실패 시 같은 UUID 재전송 규칙은 유지함.

## 추가 기능 이용

- 이동·상호작용은 기존 WASD/방향키·E 사용. Z 또는 화면 찌르기 버튼으로 앞의 캐릭터에게 손 동작을 보냄. 길게 누르면 반복하고, 키/버튼을 놓으면 종료함. 입력창·팝업·층 전환·연결 종료 중에는 중단함.
- 같은 층의 가까운 사용자는 같은 효과를 보고, 개인 학습교실의 강사·학생 NPC 반응은 본인에게 표시됨. 벽·가구 너머의 대상은 찌르지 않으며 좌표나 포인트를 변경하지 않음.
- 우상단 보유 포인트를 누르면 본인의 적립 내역을 최근순 10건씩 표시하고 **더 보기**로 이전 내역을 조회함. 읽기만 수행하며 추가 지급하지 않음. 네트워크 오류 시 다시 불러오기를 제공함.
- 게임 카드 총 16종. 업데이트 후 백엔드 `migrate --noinput`으로 추가 8종의 기준정보를 등록함. 기존 콘텐츠 UUID·운영자가 수정한 항목을 덮어쓰지 않음.
- 옥상 콘텐츠 부스와 학습교실 표현을 개선함. 광고용 게시판과 광고 서버 연결은 별도 구성임.
- 한글·영문·IME 상태의 WASD·E·Z는 물리 키 위치를 사용함. 입력창·텍스트 선택·브라우저 단축키는 별도로 처리함.
- 통신이 끊기면 WebSocket 재접속을 시도함. 같은 세션의 새 연결이 이전 연결을 교체하며 현재 위치·개인 학습교실을 복원함. 교체된 이전 탭은 새로고침으로 다시 연결할 수 있음.
- 학습교실 진입 방향키를 계속 누르고 있어도 바로 퇴장하지 않음. 키를 놓고 다시 입력하거나 2초 뒤 나가기 버튼을 사용함. 개인 교실 사용자는 공용 지도·유리문 충돌에서 제외함.
- 유튜브 부스 중앙에서 상호작용하면 YouTube 홈페이지를 별도 팝업으로 열고, 차단되면 부스의 **YouTube 열기** 링크로 다시 시도함.

## AWS 운영 반영

프론트 `playdata-frontend`, 백엔드 `playdata-backend` 서비스를 사용함. 소스 반영 전 DB와 변경 파일을 백업하고 추가 마이그레이션·정적 파일 수집·서비스 재시작을 수행함. 실패 시 기존 소스와 설정으로 복구할 수 있도록 백업을 유지함.

공개 호스트는 프론트 `FRONTEND_ALLOWED_HOSTS`, 백엔드 `DJANGO_ALLOWED_HOSTS`와 필요한 `DJANGO_CSRF_TRUSTED_ORIGINS`로 설정함. 배포 시 기존 `.env`, DB, 식단 캐시를 덮어쓰지 않음.

2026-10-15 AWS 운영 DB를 MySQL로 전환함. Router `127.0.0.1:6446`의 쓰기 연결로 전용 `playdata_campus` DB를 사용하며, 문자 비교는 기존 아이디 중복 검사와 맞는 `utf8mb4_0900_as_ci`임. 3대 모두 ONLINE 상태와 데이터 복제를 확인함. Kafka 3대·7개 토픽·실제 메시지 조회와 Outbox 대기 0건도 확인함. 비밀번호·Vault·개인키·운영 DB는 Git이나 소스 배포 묶음에 포함하지 않음.

위치·Raw Outbox 정밀도 보존에는 `accounts.0007_preserve_json_precision`, `eventing.0009_preserve_json_precision` 마이그레이션이 필요함. MySQL에서만 JSON 원문을 LONGTEXT + JSON_VALID 검사로 보존하고 SQLite 동작은 유지함. Kafka payload와 fingerprint의 재조회 일치를 회귀 검증함.

전환 전 SQLite·설정을 비공개 배포 백업에 보관하고 전체 ORM 데이터 1,908건을 마이크로초·좌표 정밀도까지 동일하게 대조함. SQLite 백업은 전환 시점 데이터이며, 이후 복구 시에는 MySQL에서 추가된 데이터도 함께 보존해야 함.

분리된 임시 QA 사본과 테스트 DB에서 MySQL 회귀 444개를 실행해 통과함. 이 중 SQLite 전용 동시 처리 6개는 MySQL용으로 별도 실행해 모두 통과함. 로컬 SQLite 이동·JSON 회귀 24개도 통과함. 합성 테스트 계정에는 테스트용 해시를 사용했고 운영 비밀번호 해시는 변경하지 않음.

## 검증

실제 운영 DB를 사용하지 않는 별도 파일 SQLite 테스트 설정을 제공함. 파일 DB로 동시 제출·원장·Outbox·마이그레이션을 검증함.

```powershell
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --settings=config.kafka_test_settings --noinput
```

새 터미널 또는 루트에서 프론트 폴더로 이동해 렌더링과 HTTP 중계를 검증함.

```powershell
cd frontend
python manage.py check
python manage.py test pages --noinput
node --test tests/*.test.cjs
node learning/tests/test-kafka-ui.cjs
```

JavaScript 검증에는 Node.js가 필요함. 마지막 학습 UI 검증은 Playwright와 Chrome을 사용하고 API 응답을 대체해 실제 사용자 데이터에 영향을 주지 않음. 실제 두 서비스의 브라우저 확인은 별도 데이터 폴더·포트로 수행해야 함. 테스트 설정의 좌표 수신 호환 모드는 기존 회귀 검증용이며, 운영 서버는 키 입력 기반 서버 판정을 사용함.

AWS MySQL 저장·복제와 Kafka 발행 측을 확인함. 수신 측 처리·MongoDB 및 운영 광고 서비스 연결은 해당 팀 환경에서 별도 검증이 필요함.


### 2026-10-15 이용 안내·맵 UI 갱신

- 신규 회원은 닉네임·아바타 설정 뒤 최초 이용 안내를 받음. 완료·건너뛰기 상태를 운영 DB에 저장하며 설정에서 다시 열 수 있음. 기존 설정 완료 계정은 배포 마이그레이션에서 확인 완료로 처리함.
- 맵을 브라우저 창 전체에 표시하고 계정·설정·이동 키 안내를 하단으로 이동함. 공간 안내는 좌측 상단 버튼에서 접고 펼침.
- 18층 바깥 배경을 베이지색 아이소메트릭 배경으로 정리함. 강의실 유리문 7개를 제거하고 출입구를 바로 통과하도록 서버 충돌 판정도 맞춤. 창고 슬라이드문은 유지함.
- 층 전환의 3초 이동 차단은 유지함. 계단에서는 캐릭터의 오르내림, 포탈에서는 순간이동 애니메이션을 표시함.
- Python 초급 빈칸 10문항의 설명만 명확히 수정함. 문제 UUID·정답·기존 응답·포인트·Kafka 이벤트 형식은 유지함.
- 적용 마이그레이션: accounts 0008_profile_guide_completed, learning 0004_beginner_prompt_wording.


### 개인 쪽지함 활성화 (2026-10-16)

1. 백엔드에서 python manage.py migrate 실행함. direct_messages.0001_initial이 Conversation·Message 테이블을 추가하며 기존 데이터를 초기화하지 않음.
2. 쪽지함을 사용할 환경의 backend/.env에 CAMPUS_DM_ENABLED=1을 설정하고 백엔드를 재시작함. 기본값 0이면 API와 UI 모두 비활성화됨. 별도 발신자 허용 목록은 사용하지 않음.
3. 프런트 정적 파일을 다시 수집·배포하고 프런트를 재시작함. 일반적인 /api/ 프록시와 기존 /ws/campus/를 사용하며 추가 서버는 필요하지 않음.
4. 서로 다른 계정으로 닉네임 검색 → 전송 → 미확인 수 → 대화 열기·읽음 → 답장을 확인함. 제삼자 계정은 대화 조회·읽음 변경이 404여야 함.

- 한 메시지는 최대 2000자이며 계정당 1초 이내 연속 전송을 제한함. 같은 requestId의 동일 재시도는 기존 메시지를 반환함.
- UI는 대화 목록 최대 50개·대화별 최근 메시지 최대 100개를 표시함. 표시 범위는 DB 저장 수명을 뜻하지 않으며 자동 삭제 정책은 추가하지 않음.
- 웹소켓이 연결되면 수신자 계정 전용 갱신 알림을 사용함. 15초 주기 조회와 창 포커스 복귀 시 확인으로 알림 누락을 보완함. 다중 서버 운영 시 Django Channels 계층 공유가 필요함.
- 쪽지창에서는 이동·점프·상호작용 입력을 차단함. 내용은 HTML로 실행하지 않고 텍스트로 표시함.
- 점프는 Space 또는 하단 버튼으로 실행함. 일반 사용자 줌은 150% 고정이며 관리자만 버튼·키보드·휠로 조절함.
