# 프론트·백엔드 실행 가이드

기준일: 2026-10-13. 아래 명령은 저장소 루트에서 시작하는 PowerShell 기준임.

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

실제 DB는 저장소에 포함하지 않음. 새로 클론하면 빈 DB에 마이그레이션만 적용하며 실제 계정·설문 연결 정보는 복사되지 않음.

기존 서버를 종료하고 **db.sqlite3 및 var 폴더를 백업한 뒤** 아래 두 방법 중 하나를 사용함.

- 기존 `db.sqlite3`와 `var`를 `backend/`로 복사하고 백엔드에서 마이그레이션함. 덮어쓰기 전에 대상 데이터도 보존해야 함.
- 백엔드 `.env`의 `CAMPUS_DATA_DIR`를 기존 데이터 폴더의 절대 경로로 지정함. 기존 파일을 옮기지 않고 사용 가능함. 서로 다른 버전의 서버가 같은 DB를 동시에 사용하지 않도록 함.

`CAMPUS_DATA_DIR` 아래의 `db.sqlite3`, `var/board-menu`, 세션 정리 상태를 사용함. 설문 연결 주소·키는 DB 안에 있으므로 DB 보존 시 함께 유지됨. 원래 루트에 DB가 있고 루트 실행기를 사용하면 그 루트를 데이터 폴더로 자동 지정해 기존 데이터를 이어 사용함. `CAMPUS_DATA_DIR`를 명시하면 그 값을 우선함.

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
| 백엔드 | `DATABASE_ENGINE` | 기본 sqlite; mysql 선택 가능 |
| 백엔드 | `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | 팀 운영 DB 연결 시 설정 |
| 백엔드 | `CAMPUS_LOGIN_MAX_AGE_SECONDS` | 28800: 최대 8시간 |
| 백엔드 | `CAMPUS_LOGIN_IDLE_TIMEOUT_SECONDS` | 1800: 비활동 30분 |
| 백엔드 | `CAMPUS_LOGIN_WARNING_SECONDS` | 60: 만료 직전 안내 |
| 백엔드 | `CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS` | 15: 활동 시간 저장 간격 |
| 백엔드 | `CAMPUS_SESSION_CLEANUP_ENABLED`, `CAMPUS_SESSION_CLEANUP_TIME` | 기본 켬·한국 시간 04:00; 만료 세션 하루 한 번 정리 |
| 백엔드 | `CAMPUS_RAFFLE_SURVEY_URL`, `CAMPUS_RAFFLE_SURVEY_FORM_ID` | 이벤트 참가용 Google 폼 |
| 백엔드 | `CAMPUS_RAFFLE_SURVEY_POLL_SECONDS` | 기본 10초; Google 제출 결과 조회 |
| 백엔드 | `LEARNING_POINTS_BEGINNER`, `LEARNING_POINTS_INTERMEDIATE`, `LEARNING_POINTS_ADVANCED` | 정답별 20·50·80P; 변경 후 재시작 |
| 백엔드 | `KAFKA_BOOTSTRAP_SERVERS` 및 인증 변수 | 비어 있으면 DB Outbox 보관만 수행 |

HTTP 중계는 로그인 쿠키·CSRF·Origin·원래 Host를 백엔드에 전달함. 프론트가 인증을 다시 판단하지 않음. 백엔드 포트는 프론트 및 신뢰할 인프라에서만 접근하도록 배포함. 공개 HTTPS 환경은 두 서비스 앞의 프록시와 호스트·CSRF·쿠키 설정을 함께 맞춰야 함.

## 내부망 접속

같은 LAN의 사용자는 `http://서버PC의사설IP:8004/`로 접속함. 프론트 bind가 `0.0.0.0`이고 두 서비스의 허용 호스트에 해당 IP가 있어야 함. 필요할 때만 Windows 관리자 권한으로 `allow-lan.cmd`를 실행하면 **프론트 TCP 8004**에 현재 LAN 접속 규칙을 적용함. 포트를 바꾸면 `configure-lan.py --port 변경포트`로 맞춤. 백엔드 9003을 사용자에게 직접 공유하지 않음.

## 학습·포인트·Kafka

답안·성적·지갑·원장·Outbox·재시도 응답을 같은 트랜잭션에 저장함. 동일 사용자의 동일 `submission_request_uuid` 재시도는 이전 응답을 돌려주며 중복 지급하지 않음. 빈칸은 `choice_uuid=null`, 객관식은 실제 선택지 UUID를 기록함.

이동 중 약 5초마다 `position_dirty`인 사용자의 최신 위치를 저장하고, 이전 저장 위치와 층 또는 x/y가 다를 때 `movement_observed` Outbox도 저장함. 방향 변경만 있으면 복원용 방향을 저장하며 Kafka 이벤트를 생성하지 않음. 정지 중에는 새 위치 기록을 만들지 않고, 종료·층 전환·로그아웃·만료는 마지막 변경 위치를 즉시 저장함. 전송 재시도는 동일 이벤트 UUID를 사용함.

브로커에 `raw.account`, `raw.chat`, `raw.board`, `raw.comment`, `raw.content_usage`, `raw.movement`, `raw.points`가 필요함. `quiz_answered`는 **1.1**, 나머지는 **1.0**임. 수신 서비스가 빈칸 답안·포인트 토픽을 지원하는지 확인한 뒤 Kafka 발행을 켬. 이 PR은 플랫폼 발행 측을 연결하며 팀원이 관리하는 기존 수신 파이프라인을 덮어쓰지 않음. 세부 계약은 [KAFKA_TOPICS.md](KAFKA_TOPICS.md) 참고.

`run-campus.py`와 `manage.py runserver` 모두 실제 서비스 프로세스에서 Outbox 발행기를 시작함. 다른 ASGI 실행기로 운영 배포하면 `eventing.publisher.start_outbox_publisher()`의 구동·종료 수명주기를 별도로 연결해야 함. 이 가이드는 제공된 개발 실행기를 기준으로 함. 브로커 장애 시 DB Outbox 대기를 유지하며, 대기량·DB 디스크 공간을 운영에서 관찰해야 함.

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

실제 Kafka·MySQL·MongoDB 및 운영 광고 서비스까지의 연결은 해당 팀 환경에서 별도 검증이 필요함.
