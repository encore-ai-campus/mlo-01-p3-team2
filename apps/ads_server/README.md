# ads_server

Django 광고 서버. 설계·계획·계약은 [docs/ads-server/](../../docs/ads-server/ads-server-design.md)에 있다.

## 실행

```bash
mamba activate claude
cd apps/ads_server
pip install -r requirements.txt
cp .env.example .env        # 값을 채운다(DB_USER·DB_PASSWORD 필수). .env 는 커밋하지 않는다
# MySQL 8.4 가 떠 있어야 한다 — 아래 "MySQL 시험 환경"
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

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
python scripts/load_test.py --json out.json   # 150 동시. 시험 컨테이너에 이 실행 전용 DB(ads_load_*)를 만들고 끝나면 지운다
python scripts/failure_test.py                # 장애 시험: DB 재시작·강제 종료·처리 프로세스 강제 종료(수 분)
python scripts/failure_test.py restart crash  # 시나리오를 골라서. --json out.json 으로 결과 저장
```

장애 시험은 Docker로 **임시 MySQL 8.4 컨테이너**를 따로 띄운다(이미지 `db-standalone/mysql:8.4-ubuntu24.04`, 무작위 포트·비밀번호, 끝나면 삭제). 공유 시험 DB나 다른 컨테이너는 건드리지 않는다. Docker나 이미지가 없으면 건너뛰지 않고 실패하며, 수 분 걸려 `check.sh`에는 넣지 않았다. 끊김 동안 500이 없고, 재시도가 모두 수신 확인되며, 유실 0·이중 과금 0·잔액=원장·소진액=원장이어야 한다. 또 상시 처리 프로세스가 살아 있고, **복구 뒤 그 프로세스만으로 대기열이 비워져야** 종료 코드 0이다(시험은 접수 직후 처리를 끄고 별도 처리 명령을 쓰지 않는다).

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
