# ads_server

Django 광고 서버. 설계·계획·계약은 [docs/ads-server/](../../docs/ads-server/ads-server-design.md)에 있다.

## 실행

```bash
cd apps/ads_server
python3.14 -m venv .venv          # 처음 한 번. 프로젝트 전용 가상환경(Python 3.14)
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 값을 채운다(DB_USER·DB_PASSWORD 필수). .env 는 커밋하지 않는다
# MySQL 8.4 가 떠 있어야 한다 — 아래 "MySQL 시험 환경"
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

- **실행 환경은 `apps/ads_server/.venv`** 하나다. 의존성은 `requirements.txt`가 전부이고(직접 의존성은 패치 버전까지 고정), `.venv`는 커밋하지 않는다. 다시 만들 때는 `.venv`를 지우고 위 세 줄을 그대로 실행한다. `mysqlclient` 빌드에는 MySQL 클라이언트 개발 파일과 `pkg-config`가 필요하다(macOS: `brew install mysql-client pkg-config`, `requirements.txt` 주석). 이후 명령(`python manage.py …`, `scripts/check.sh`)은 모두 이 환경을 활성화한 셸에서 실행한다.
- `.env`는 python-dotenv가 읽고, **실제 환경변수가 `.env`보다 우선**한다.
- 설정은 `config/settings/{dev,prod,test}.py`. `manage.py`는 기본 dev, `manage.py test`는 항상 test, `wsgi/asgi`는 기본 prod.
- prod는 `SECRET_KEY`(50자 이상)·`ALLOWED_HOSTS`·`DB_NAME`·`DB_USER`·`DB_PASSWORD`·`DB_HOST`가 없으면 기동하지 않는다.
- 관리자 계정은 가입 화면이 없다: `python manage.py createsuperuser`.
- dev 에서는 `DEBUG`가 기본 꺼져 있어 `runserver`가 정적 파일(CSS)을 서빙하지 않는다. 화면을 볼 때는 `DJANGO_DEBUG=1`로 실행한다.

## MySQL 시험 환경

DB 는 **MySQL 8.4**다(Step DB). 시험·부하·`check.sh`는 개발 PC의 8.4 컨테이너를 쓴다(공유 인프라 서버에서는 돌리지 않는다). 컨테이너 정의는 `intake/db-standalone/`(인프라 제공, Ubuntu 24.04 + MySQL 8.4 + MongoDB 8.0 Standalone):

```bash
cd intake/db-standalone && cp .env.example .env     # MYSQL_ROOT_PASSWORD·MONGO_ROOT_PASSWORD 를 채운다
docker compose up -d --build --wait
```

앱 쪽 준비(한 번):

```bash
brew install mysql-client pkg-config                # mysqlclient 를 빌드하는 데 필요
pip install -r requirements.txt
cp .env.example .env                                # DB_USER·DB_PASSWORD 에 컨테이너 root 값(로컬 시험 전용)
python scripts/mysql_admin.py                       # 접속·8.4·생성/삭제 권한 점검. 안 되면 이유를 말하고 멈춘다
```

- 데이터베이스는 **정렬을 지정해** 만든다. 8.4 기본(`utf8mb4_0900_ai_ci`)은 대소문자·악센트를 구분하지 않아 유일 제약과 비교가 달라진다:
  `CREATE DATABASE ads_server CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;`
  (시험이 만드는 `test_ads_server`와 부하 시험의 `ads_load_*`는 코드가 같은 정렬로 만든다.)
- 시험은 `test_<DB_NAME>` 을 만들고 끝나면 지운다 → 접속 계정에 CREATE/DROP 권한이 필요하다. 시험 설정은 DB 접속 값(`DB_*`)만 환경에서 읽는다.
- `check --deploy`와 `makemigrations --check`는 이제 **DB 연결이 필요하다**(MySQL 에서는 모델 검사가 서버 정보를 읽는다).
- 이 컨테이너와 인프라 서버의 차이: 컨테이너는 GTID가 꺼져 있고 서버 기본 정렬이 `_ai_ci`다(인프라의 `infra.cnf` 핵심은 DB-1d의 인프라 서버 통합 확인에서 맞춘다).

## InnoDB Cluster 시험 환경 (운영 후보 구성)

기본 게이트는 단일 노드 MySQL에서 도는 `scripts/check.sh`다. 운영 후보 구성인 **InnoDB Cluster**(MySQL 3노드 그룹 복제, 단일 primary, 자동 failover + MySQL Router)에서 같은 점검을 돌릴 때는 아래를 쓴다(Docker 필요, 수 분).

```bash
env -u DB_NAME scripts/cluster_check.sh              # 클러스터를 띄워 check.sh(전체 시험·20 동시 부하·보안 점검)와 150 동시 부하를 돌리고 지운다
env -u DB_NAME scripts/cluster_check.sh --failure    # 거기에 클러스터 장애 시험 8개(자체 클러스터를 따로 띄운다)
eval "$(python scripts/mysql_cluster.py start)"   # 손으로 띄우기: MYSQL_CLUSTER_ID·DB_HOST·DB_PORT(Router 포트)·DB_USER·DB_PASSWORD 를 export
python scripts/mysql_cluster.py status "$MYSQL_CLUSTER_ID"
python scripts/mysql_cluster.py stop "$MYSQL_CLUSTER_ID"
python scripts/failure_test.py --mysql cluster primary-kill switchover   # 클러스터 장애 시나리오를 골라서
```

- **이미지** `ads-innodb-cluster:8.4`(`docker/innodb-cluster/`, 처음 한 번 빌드에 수 분): 서버 8.4.11(인프라 이미지와 같은 generic tarball), Shell·Router 8.4.10(arm64 tarball이 8.4.10까지).
- **구성**: 노드 3개(GTID·ROW 바이너리 로그, 일관성 `BEFORE_ON_PRIMARY_FAILOVER`, `expelTimeout` 5초, 자동 재합류) + Router 1대. 앱은 **Router 읽기·쓰기 포트로만** 접속한다. 계정은 운영처럼 나눈다: `root`(노드 안), `failover`(클러스터 관리), `router`(부트스트랩이 만듦), `dev`(앱·시험).
- 포트·비밀번호는 무작위이고 공유 컨테이너(`db-standalone-*`)는 건드리지 않는다. 시험이 실패해도 클러스터 컨테이너와 네트워크를 지운다. `cluster_check.sh`는 시작 전에 환경에 남은 이전 클러스터 값을 비우고, 기동 명령의 종료 코드를 직접 확인한다. 기동에 실패하면 후속 시험 없이 비정상 종료하고, 정리는 **이번 실행이 만든 클러스터에만** 건다(이전 ID를 지우지 않는다).
- `env -u DB_NAME`: 클러스터에는 `ads_server` 데이터베이스만 만들어지고, `cluster_check.sh`가 비우는 값은 접속 값(`DB_HOST`·`DB_PORT`·`DB_USER`·`DB_PASSWORD`)뿐이다. 동시 시험 때문에 셸에 `DB_NAME`을 따로 정해 두었다면 빼고 돌린다(클러스터는 따로 띄우므로 이름을 나눌 필요가 없다).
- **장애 시나리오**: `primary-kill`(자동 failover 뒤 죽은 노드 재합류), `primary-restart`, `switchover`(계획된 전환), `secondary-kill`, `router-restart`, `processor-kill`, `mongo-restart`, `relay-kill`. 끝에서 모든 노드 ONLINE·primary 하나·모든 노드의 GTID 집합과 표별 행 수가 같은지 확인한다.
- **그룹 복제는 기본 키 없는 표를 거부한다**(오류 3098). 시험에서 표를 만들 때도 기본 키를 둔다. 결과와 해석은 [`docs/ads-server/load-test.md`](../../docs/ads-server/load-test.md) §9, 전제는 설계 §10 "그룹 복제(InnoDB Cluster) 전제".

## MongoDB 시험 환경

이벤트 로그(MongoDB `ad_events`, Step 4부터 중계가 씀)는 **MongoDB 8.0**이다. 같은 `intake/db-standalone` 컨테이너(`mongodb` 서비스, Standalone·인증)를 쓴다. 접속 값은 `.env`의 `MONGO_*`(`.env.example`)이고,
시험 설정은 접속 값만 읽고 데이터베이스 이름은 시험마다 무작위로 정해 **그 이름만** 지운다. `check.sh`가 맨 앞에서 `scripts/mongo_admin.py`로 접속·쓰기를 점검한다(MongoDB가 없으면 시험을 건너뛰지 않고 멈춘다).

```bash
python manage.py ensure_event_store    # ad_events 컬렉션(봉투 검증)과 색인을 만든다(멱등, 배포 때 한 번)
python manage.py check_event_store     # 연결·버전·레플리카셋·쓰기 권한·컬렉션·색인 확인(하나라도 실패하면 비정상 종료)
```

- 레플리카셋 접속(운영과 같은 방식)을 시험하려면 임시 단일 노드 레플리카셋(인증 켜짐)을 띄운다. 포트·비밀번호는 무작위이고 공유 컨테이너는 건드리지 않는다:
  `eval "$(python scripts/mongo_temp_rs.py start)"` → 같은 셸에서 위 명령·`python manage.py test tests.test_event_store` → `python scripts/mongo_temp_rs.py stop $MONGO_TEMP_CONTAINER`
- 앱(웹 프로세스)은 MongoDB를 호출하지 않는다. 요청은 MySQL의 outbox에 이벤트를 쓰기만 하고, MongoDB로 옮기는 일은 상시 중계(`relay_events`, 아래)가 한다. MongoDB가 끊기면 이벤트는 outbox에 쌓였다가 복구 뒤 옮겨진다(짧은 재시작 시험에서 요청 503 0, 장기 장애는 확인하지 않음 — 설계 §10 "MongoDB 장애와 요청").

## 상시 프로세스와 이벤트 운영

웹 프로세스 말고 두 프로세스를 **상시로** 띄운다. 둘 다 여러 개를 동시에 돌려도 안전하고, DB나 MongoDB가 잠시 끊겨도 죽지 않고 다시 시도하며, SIGTERM에 정상 종료한다.

```bash
python manage.py process_reactions           # 반응 판정·과금(보류 해소 포함). 멈추면 반응이 RECEIVED 로 남는다
python manage.py relay_events                # outbox → MongoDB ad_events. 멈추면 이벤트가 outbox 에 쌓인다
python manage.py relay_events --status       # 미전송 건수와 가장 오래된 것의 나이(초). 계속 늘면 중계가 멈췄거나 MongoDB 가 끊긴 것
python manage.py purge_sent_events           # 보낸 지 7일(EVENTS_OUTBOX_RETENTION_DAYS) 지난 outbox 행 삭제. 미전송은 지우지 않는다. 하루 한 번처럼 주기적으로
python manage.py export_integrity --out DIR  # 원장·이벤트 정합성 점검(한 읽기 스냅샷). 결과는 NDJSON + manifest, 문제가 있으면 비정상 종료
python manage.py verify_ndjson DIR/event_gaps.manifest.json   # 게시된 결과가 manifest 와 맞는지 확인
python manage.py backfill_events --input DIR/event_gaps.manifest.json --out OUT          # 백필 미리보기(dry-run, 쓰지 않음)
python manage.py backfill_events --input DIR/event_gaps.manifest.json --out OUT --apply  # 원본 행에서 이벤트를 다시 만들어 outbox 에 씀(중계가 보냄)
python manage.py export_hop_manifests --out HOPS   # 원본 기대·outbox·MongoDB 세 구간의 창별 manifest(창이 닫힌 뒤, 주기적으로)
python manage.py verify_hops --dir HOPS            # 구간 대조. 확정 불일치·사슬 오류·고정점 불일치면 비정상 종료, 중계 지연 후보만 있으면 보고
```

- **중계가 충돌로 멈출 때**: `relay_events`가 "충돌로 중계를 멈춥니다"와 이벤트 ID를 남기고 비정상 종료하면, MongoDB에 같은 이벤트 ID로 **다른 내용**이 이미 있다는 뜻이다(이벤트 ID가 원천 행에서 결정적으로 정해지므로 정상 운영에서는 일어나지 않는다). 덮어쓰지 않는 것이 의도다. 충돌하지 않은 이벤트는 이미 보낸 것으로 표시됐고, 충돌한 행은 미전송으로 남아 있어 **원인을 해결하기 전에는 다시 띄워도 같은 배치에서 다시 멈춘다**. 로그의 이벤트 ID로 outbox 행(`events_outbox`)과 MongoDB 문서를 비교해 원인(수동 수정, 직렬화 변경 등)을 찾는다. outbox가 맞다고 확인되면 MongoDB의 그 문서를 지우고 다시 띄우면 중계가 다시 저장한다.
- **백필**은 이벤트가 빠진 원본 행이 있을 때(Step 4 이전 행, 장애 복구 뒤 보정) 운영자가 돌린다. 순서: `export_integrity` → `verify_ndjson` → `backfill_events`(dry-run으로 건수 확인) → `--apply` → `relay_events`가 보냄 → `export_integrity`로 누락 0 확인. 목록의 값은 쓰지 않고 원본 행에서 다시 만들며, 해석 불가가 있으면 비정상 종료한다. 실행은 감사 로그(`events.backfilled`)에 남는다.
- **구간 manifest**는 창(UTC 하루)이 끝나고 2분(`EVENTS_HOP_GRACE_SECONDS`) 뒤에 닫힌다. `verify_hops`는 감사 로그의 고정점과 대조하므로 같은 환경의 폴더를 쓴다(다른 환경에서 받은 폴더는 `--no-anchor`). 파이프라인 쪽 manifest는 `--pipeline`으로 MongoDB 구간과 대조한다.
- `export_integrity`의 결과는 이름에 내용 해시가 들어간 데이터 파일과 그것을 가리키는 manifest다. manifest가 가리키는 파일만 믿고, 옛 세대 파일은 자동으로 지우지 않는다. `checkpoint`는 점검 범위의 서술(스냅샷·시작 시각·훑은 행 수)이고 이어서 읽는 위치가 아니다.

## 테스트와 점검

```bash
python manage.py test                 # 전체 (경계 검사·보안 회귀 포함)
python manage.py test --tag security  # 보안 회귀 묶음만
./scripts/check.sh                    # 일괄 점검: check --deploy, 마이그레이션, 테스트, pip-audit, bandit
OFFLINE_OK=1 ./scripts/check.sh       # 네트워크가 없어 pip-audit 을 못 돌릴 때 건너뛰고 표시
```

`check.sh`는 하나라도 실패하면 비정상 종료한다. `pip-audit`이 네트워크 문제로 못 돌 때와 **실제 취약점이 발견됐을 때**를 구분해 알려준다.

부하·장애 시험(결과와 해석은 [`docs/ads-server/load-test.md`](../../docs/ads-server/load-test.md)):

```bash
python scripts/load_test.py --small           # 20 동시(몇 초). check.sh 가 실행한다
python scripts/load_test.py --json out.json   # 150 동시. 시험 컨테이너에 이 실행 전용 DB(ads_load_*)·MongoDB 데이터베이스(ads_events_load_*)를 만들고 끝나면 지운다
python scripts/failure_test.py                # 장애 시험: DB 재시작·강제 종료·처리 프로세스 강제 종료·MongoDB 재시작·중계 강제 종료(수 분)
python scripts/failure_test.py restart crash  # 시나리오를 골라서. --json out.json 으로 결과 저장
```

장애 시험은 Docker로 **임시 MySQL 8.4 컨테이너와 임시 MongoDB 8.0 단일 노드 레플리카셋(인증 켜짐)**을 따로 띄운다(이미지 `db-standalone/mysql:8.4-ubuntu24.04`·MongoDB 이미지, 무작위 포트·비밀번호, 끝나면 삭제). 공유 시험 DB나 다른 컨테이너는 건드리지 않는다. Docker나 이미지가 없으면 건너뛰지 않고 실패하며, 수 분 걸려 `check.sh`에는 넣지 않았다. 끊김 동안 500이 없고, 재시도가 모두 수신 확인되며, 유실 0·이중 과금 0·잔액=원장·소진액=원장이어야 한다. 또 상시 처리·중계 프로세스가 살아 있고, **복구 뒤 그 프로세스들만으로 대기열과 미전송 이벤트가 비워져야** 하며, 이벤트가 원본 행·MongoDB와 내용까지 같아야 종료 코드 0이다(시험은 접수 직후 처리를 끄고 별도 명령을 쓰지 않는다). 시나리오는 MySQL 재시작·강제 종료, 처리·중계 프로세스 강제 종료, MongoDB 재시작 다섯 가지다.

## `check --deploy`

0-4 이후 prod 설정의 경고는 **0**이다(`python -m django check --deploy --fail-level WARNING`, 테스트로 강제).
`security.W021`(HSTS 프리로드)만 **의도적으로 끈다**: 내부 서비스이고 프리로드 등록은 되돌리기 어렵다(`config/settings/prod.py`에 사유).

## 알려진 사항

- 관리자 화면(Django admin)에서 사용자 관리와 감사 로그 열람이 가능하다. 사용자 변경·비밀번호 초기화는 감사 로그에 남고, 감사 로그는 읽기 전용이다.
- 이미지는 업로드 시 내장 ICC로 sRGB 변환한 뒤 메타데이터를 모두 버린다. 조작된 ICC 프로필로 lcms2(Pillow 번들)를 공격하는 위험은 완전히 막을 수 없어 위협 모델 T27·잔여 위험으로 관리한다(Pillow 업데이트 시 `pip-audit` 확인).
- 아키텍처 경계(층·`api` 만 import)는 `tests/boundaries/`가 강제한다. 모듈을 추가하면 `test_layers.py`의 `LAYERS`에 등록한다.
- 정적 파일(CSS)은 DEBUG 에서만 `runserver` 가 서빙한다. 운영에서는 `python manage.py collectstatic --noinput`으로 `STATIC_ROOT`(prod 환경변수, 기본 `./staticfiles`)에 모은 파일을 웹서버(인프라)가 서빙한다. 웹서버 설정은 배포 단계의 일이다.

## 매체 키 (C1 인증)

매체 서버는 `X-Media-Key` 헤더로 키를 보낸다. 키는 관리자가 발급하며 **평문은 발급할 때 한 번만 출력**되고 저장되지 않는다.

```bash
python manage.py media_key issue  <매체 ID> --admin <관리자 아이디> --label 운영
python manage.py media_key rotate <매체 ID> --admin <관리자 아이디> --grace-hours 24   # 새 키 발급, 기존 키는 24시간 뒤 만료(그동안 둘 다 유효)
python manage.py media_key revoke <키 ID>   --admin <관리자 아이디>                  # 유출 시 즉시 폐기
```

요청 제한(`MEDIA_RATE_LIMITS`)은 프로세스 메모리 기반이라 워커가 여러 개면 한도가 그만큼 느슨해진다(설계 §10).
