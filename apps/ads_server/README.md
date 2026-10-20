# ads_server

Django 광고 백엔드 서버.

**프론트·백 분리(6-15, 설계 §6.6 "6-15 분리")**: 이 폴더는 **백엔드**다 — DB·검증·CSRF·세션·권한·서비스·매체 API(C1)를 맡고, 우리 화면은 HTML 대신 화면 데이터(JSON)를 돌려준다.
사람이 보는 화면은 **프론트**([../ads_frontend](../ads_frontend/README.md), DB 없음)가 같은 경로로 받아 그리고, 입력·쿠키는 그대로 이 백엔드로 넘긴다.
브라우저는 프론트만 연다. Django admin 자체·이미지·클릭 이동은 프론트가 통과시키고, 매체 API 는 공개하지 않는다(게임 백엔드가 백 서버로 직접).

## 실행

```bash
cd apps/ads_server
python3.14 -m venv .venv          # 처음 한 번. 프로젝트 전용 가상환경(Python 3.14)
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 값을 채운다(DB_USER·DB_PASSWORD 필수). .env 는 커밋하지 않는다
# MySQL 8.4 가 떠 있어야 한다 — 아래 "데이터베이스"
python manage.py migrate
python tools/run_split.py         # 백엔드 127.0.0.1:8000 + 프론트 127.0.0.1:8001 → 브라우저는 http://127.0.0.1:8001/
```

- **두 서버를 따로 띄울 때**: 백엔드는 `python manage.py runserver 127.0.0.1:8000`, 프론트는 `../ads_frontend` 에서 `FRONTEND_DEBUG=1 BACKEND_URL=http://127.0.0.1:8000 python manage.py runserver 127.0.0.1:8001`(관리 사이트 경로 `ADMIN_URL_PATH`·업로드 상한 `ASSET_MAX_BYTES` 는 두 쪽이 같아야 한다 — `run_split.py` 는 이 `.env` 에서 받아 넘긴다). 백엔드 주소를 브라우저로 열면 화면 대신 화면 데이터(JSON)가 보인다.
- **광고주 화면 검토(6-21)**: `python tools/demo_data.py`(개발 설정에서만 — 개발 DB 에 시연 광고주·캠페인 넷·최근 7일 성과, 계정은 그 파일) → `run_split.py` → `python tools/screens.py OUT --design <시안 폴더>`(headless Chrome 으로 광고주 화면을 찍어 `OUT/<화면>.png`, 시안과 나란히 `OUT/compare-<화면>.png`).

- **실행 환경은 `apps/ads_server/.venv`** 하나다. 의존성은 `requirements.txt`가 전부이고(직접 의존성은 패치 버전까지 고정), `.venv`는 커밋하지 않는다. 다시 만들 때는 `.venv`를 지우고 위 세 줄을 그대로 실행한다. `mysqlclient` 빌드에는 MySQL 클라이언트 개발 파일과 `pkg-config`가 필요하다(macOS: `brew install mysql-client pkg-config`, `requirements.txt` 주석). 이후 명령(`python manage.py …`, `tools/run_split.py`)은 모두 이 환경을 활성화한 셸에서 실행한다.
- `.env`는 python-dotenv가 읽고, **실제 환경변수가 `.env`보다 우선**한다.
- 설정은 `config/settings/{dev,prod}.py`. `manage.py`는 기본 dev다. `wsgi/asgi`는 `.env`의 설정 모듈을 따르지 않고 실제 환경변수가 없으면 prod다(아래 "운영 배포").
- prod는 `SECRET_KEY`(50자 이상)·`ALLOWED_HOSTS`·`DB_NAME`·`DB_USER`·`DB_PASSWORD`·`DB_HOST`·`ADMIN_URL_PATH`(기본값 `admin/` 금지)·`MEDIA_ROOT`·`ASSET_PUBLIC_BASE_URL`·`TRUSTED_PROXY_COUNT`(1 이상)·`CSRF_TRUSTED_ORIGINS`가 없으면 기동하지 않는다.
- 관리자 계정은 가입 화면이 없다: `python manage.py createsuperuser`.
- 정적 파일(CSS·JS)은 Django가 WhiteNoise로 서빙한다(설계 §10 "정적 파일 서빙"). 6-15 부터 콘솔·운영 화면과 Django admin 의 정적 파일은 **프론트가** 서빙하고, 이 백엔드에는 직접 오는 경우의 Django admin 것만 남는다. dev에서 `DJANGO_DEBUG=1`이면 `runserver`가 앱 폴더에서 바로 서빙하고, `DEBUG`가 꺼져 있으면(기본) `python manage.py collectstatic --noinput`을 한 번 돌린 뒤 다시 시작해야 화면에 CSS가 붙는다.

## 데이터베이스

DB는 **MySQL 8.4**다. `.env`의 `DB_*` 값으로 접속한다.
데이터베이스는 대소문자·악센트를 구분하는 정렬로 만든다.

```sql
CREATE DATABASE ads_server CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
```

`check --deploy`와 `makemigrations --check`도 DB 연결이 필요하다.
MySQL에서는 모델 검사가 서버 정보를 읽는다.

이벤트 로그는 **MongoDB 8.0**의 `ad_events` 컬렉션에 저장한다.
접속 값은 `.env`의 `MONGO_*`로 지정한다(`.env.example`).

```bash
python manage.py ensure_event_store    # 컬렉션 검증과 색인 생성(배포 때 한 번)
python manage.py check_event_store     # 연결·버전·레플리카셋·쓰기 권한·컬렉션·색인 확인
```

웹 요청은 MySQL의 outbox에 이벤트를 기록한다.
상시 중계 `relay_events`가 MongoDB로 옮긴다.
MongoDB가 끊기면 이벤트는 outbox에서 기다린다.

## 운영 배포

- **설정 모듈**: 운영 호스트에서 `manage.py`로 실행하는 모든 명령(`migrate`·`process_reactions`·`relay_events` 등)은 `DJANGO_SETTINGS_MODULE=config.settings.prod`를 **실제 환경변수로** 지정한다. `manage.py`의 기본은 dev다. 웹 진입점(`wsgi`·`asgi`)은 **`.env`의 설정 모듈을 따르지 않는다** — 실제 환경변수에 있으면 그 값, 없으면 prod다(`.env`의 다른 값은 그대로 읽는다, Step 6-3a). 그래서 `.env`에 dev가 남아 있어도 웹은 dev로 뜨지 않는다.
- **두 서버(6-15)**: **프론트 서버**(80·443 공개)에 nginx + 프론트 Django(`../ads_frontend`, 127.0.0.1 바인딩), **백 서버**(내부망)에 이 백엔드와 상시 프로세스를 둔다. 백엔드는 내부망 주소로 열고 인프라 방화벽이 프론트 서버와 게임 백엔드(그리고 상대 Kafka·MySQL 주소)만 허용한다. 브라우저 경로는 nginx → 프론트 → 백의 두 단계라 **`TRUSTED_PROXY_COUNT=2`** 이고, `ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS`·`ASSET_PUBLIC_BASE_URL` 은 브라우저가 여는 공개 주소(프론트가 `Host` 를 그대로 넘긴다) — 게임 백엔드가 부르는 내부 주소도 `ALLOWED_HOSTS` 에 둔다. 프론트의 `ADMIN_URL_PATH`·`ASSET_MAX_BYTES` 는 이 백엔드와 같게, nginx 의 업로드 크기는 `ASSET_MAX_BYTES` + 64KiB 이상. 아래 nginx 문장의 "Django"는 프론트 Django 다.
- **배포 구성**(설계 §10 "배포 구성"): 광고 서버 앞 nginx(certbot)가 TLS·80→443 리다이렉트·HSTS·관리자 경로(`ADMIN_URL_PATH` 아래 — 관리 사이트·운영 화면)의 접속 허용 목록(우리 강의실 라우터 IP 하나, 6-20 — 사이트의 나머지는 모두에 연다)을 맡고, 요청을 같은 호스트의 Django로 HTTP로 넘기기만 한다. Django는 HTTPS 리다이렉트·HSTS를 하지 않고 `X-Forwarded-Proto`도 읽지 않는다. 세션·CSRF 쿠키는 Secure라 nginx가 HTTP로 열면 로그인이 되지 않는다. `CSRF_TRUSTED_ORIGINS`에는 브라우저가 여는 https 주소를 적는다(Django가 요청을 HTTP로 알아 브라우저의 출처와 맞지 않으므로 필수 — 없으면 기동하지 않는다). nginx 쪽 요구사항(허용 목록과 certbot 검증 경로, 넘길 헤더, 업로드 크기, 바인딩)은 계획 §7.3.4 #9.
- **올릴 묶음**: 개발 로컬에서 `python tools/build_release.py OUT`을 실행한다. `OUT/ads_server-<커밋>.tar.gz`와 `OUT/ads_frontend-<커밋>.tar.gz`가 만들어진다. 저장소 HEAD에 커밋된 파일만 들어간다. `tools/`·README·`.gitignore`·개발 설정·상대 앱은 제외된다. `requirements.txt`는 운영 의존성만 담는다. 운영 호스트의 모든 관리 명령에는 `DJANGO_SETTINGS_MODULE=config.settings.prod`를 지정한다.
- **배포 순서**: `migrate` → `collectstatic --noinput` → `ensure_event_store` → 웹과 상시 프로세스(아래). 웹은 `collectstatic` 뒤에 (다시) 시작한다 — WhiteNoise가 시작할 때 `STATIC_ROOT`를 읽는다. 중계를 먼저 띄우면 MongoDB가 봉투 검증 없는 `ad_events` 컬렉션을 자동으로 만든다(나중에 `ensure_event_store`가 검증을 맞추기는 한다).
- **서버 실행**(설계 §10 "운영 서버 실행 환경", 계획서 §8.4.21): venv 는 **Python 3.14**(모델 PK 기본값 `uuid.uuid7` 이 3.14 부터 — Ubuntu 24.04 의 시스템 3.12 로는 뜨지 않는다, deadsnakes `python3.14`). 웹은 gunicorn `gunicorn config.wsgi --bind <백 서버 내부 주소>:8000 --workers <2×CPU+1>`. 웹·`process_reactions`·`relay_events` 를 systemd 서비스 셋으로 띄우고(`Restart=on-failure`), 셋 모두 `Environment=DJANGO_SETTINGS_MODULE=config.settings.prod`·`WorkingDirectory=` 이 폴더. 백 서버는 외부로 나가지 못해 `pip install --proxy http://<배스천>:3128/ -r requirements.txt`.
- **마이그레이션**: 앱마다 `0001_initial` 하나다(운영 시작 전에 합침, 설계 §10 "마이그레이션"). 운영 DB 는 빈 DB 에 `migrate` 로 만든다. **운영이 시작된 뒤에는 적용한 마이그레이션을 지우거나 합치지 않고** 새 마이그레이션을 쌓는다.
- **배포 후 점검 `ops_check`**: 배포 순서를 마친 뒤 `python manage.py ops_check`(prod 설정). ① **설정·파일 저장소** — `check --deploy`, `MEDIA_ROOT` 쓰기 가능 ② **의존성** — 설치된 패키지가 `requirements.txt` 의 운영 묶음(`~=`)과 맞다 ③ **MySQL** — 적용 안 된 마이그레이션 0(`migrate --check`, 접속도 본다)·원장 대조(`check_ledger`) ④ **MongoDB** — 이벤트 저장소(`check_event_store`) ⑤ **상시 처리** — 반응 처리 stuck 0, 반응·outbox 의 가장 오래 기다린 것 ≤ `OPS_CHECK_MAX_WAIT_SECONDS`(600초). 한 줄씩 `OK`/`FAIL` 로 보이고 **하나라도 실패하면 종료 코드 1**이다. 하나가 실패해도 나머지를 모두 본다(한 항목 안의 여러 점검도 모두 보고 이유를 모은다). 운영 데이터는 바꾸지 않는다(MongoDB 점검은 점검용 컬렉션에 문서 하나를 쓰고 지운다). 주기 감시에 써도 된다. 프론트 서버에는 프론트의 `ops_check` 가 있다(설정·의존성·정적 파일·백엔드 닿음·화면 한 장).
- **배포 점검 — 신뢰할 프록시 수 `TRUSTED_PROXY_COUNT`는 prod 필수이고 1 이상이다**(6-15 부터 nginx + 프론트 2단 = `2`, 설계 §10 "배포 구성"). 없거나 0 이하면 기동하지 않는다. 앱은 `X-Forwarded-For`의 오른쪽에서 이 수만큼째 값을 클라이언트 IP로 쓴다. 실제 프록시 수보다 적으면 모든 요청이 프록시 IP 하나로 보여 로그인 잠금(아이디 + IP 기준)이 아이디만 보는 것과 같아지고(남이 계정을 잠글 수 있다) 감사 로그의 IP가 모두 프록시 IP가 된다. 많으면 `X-Forwarded-For` 앞쪽의 위조 값을 믿게 된다. **백엔드 포트는 프론트 서버와 인프라가 정한 내부 서버(게임 백엔드 등) 밖에 열지 않는다**(내부망 바인딩 + 방화벽) — 열려 있으면 프론트를 거치지 않고 `X-Forwarded-For`를 위조해 IP를 고를 수 있다.
- **로그**: 시각은 UTC ISO 8601 `Z`(예: `2026-10-12T14:30:01.958Z`)이고 줄마다 `[요청 ID]`가 붙는다(요청 밖의 줄은 `[-]`). 응답 헤더 `X-Request-ID`로 그 요청의 로그를 Django 요약 줄(4xx·5xx)까지 찾을 수 있다. 화면·클릭(`/c/…`)의 503은 원인(오류 종류·MySQL 오류 번호)을 트레이스백 없이 한 줄로 남긴다. 두 상시 명령의 시작·처리·장애 줄 앞에도 같은 형식의 시각이 붙는다(일회성 `--status`는 붙지 않는다).

## 상시·주기 작업

이 목록이 상시·주기 작업의 원본이다(설계 §10 "운영 작업 목록"). 주기와 스케줄러는 인프라와 정한다(설계 §7-9).

| 작업 | 언제 | 하지 않으면 |
|---|---|---|
| `process_reactions` | 상시 | 반응이 `RECEIVED`로 남는다(판정·과금이 멈춘다). 한가할 때도 시작 직후·stuck 건수가 바뀔 때·60초마다 `idle {현황}` 줄을 찍으므로 **출력이 끊기면 멈춘 것**이다 |
| `relay_events` | 상시 | 이벤트가 outbox에 쌓인다 |
| `process_reactions --status` | 감시 | 처리하지 않고 현황만 본다: 대기(`received`, 아래 둘 포함)·보류(`held`)·`stuck`·가장 오래된 대기(`oldest_age_seconds`, 초, stuck 제외). `stuck`이 0보다 크면 과금되지 않은 반응이 있다(같은 결정의 뒤 반응도 그것을 기다리며 묶일 수 있다 → 원인을 고친 뒤 `--retry-stuck`). 대기 시간이 계속 늘면 처리기가 멈춘 것이다. 같은 값을 관리자 첫 화면 카드에서도 본다(화면을 연 때의 값) |
| `relay_events --status` | 감시 | 미전송 건수와 가장 오래된 것의 나이(초). 계속 늘면 중계가 멈췄거나 MongoDB가 끊긴 것 |
| `purge_sent_events` | 매일 | 보낸 outbox 행이 쌓인다(보낸 지 7일 지난 것만 지운다, `EVENTS_OUTBOX_RETENTION_DAYS`) |
| `clearsessions` | 매일 | 만료된 로그인 세션 행이 DB에 쌓인다(세션은 DB에 저장되고 지우는 곳이 따로 없다) |
| `axes_reset_logs --age 30` | 매주 | 로그인 접속 기록(django-axes)이 계속 쌓인다(30일 넘은 것만 지운다) |
| `end_expired_campaigns` | 주기 | 기간이 지난 캠페인의 저장 상태가 `ENDED`로 바뀌지 않는다(노출은 기간 판정이 막는다) |
| `check_ledger` | 주기 | 잔액과 원장의 불일치를 모른다(불일치면 비정상 종료) |
| `ops_check` | 배포 뒤·감시 | 설정·DB 마이그레이션·MongoDB·반응 처리·outbox·원장·파일 저장소 중 깨진 것을 한 번에 모른다(위 "배포 후 점검", 실패하면 종료 코드 1) |
| `export_hop_manifests` → `verify_hops` | 주기(창이 닫힌 뒤) | 구간(원본·outbox·MongoDB) 대조를 하지 않는다 |
| `export_integrity` | 수시 | 원장·이벤트 정합성 점검 |
| `process_reactions --retry-stuck` | 필요할 때 | 실패가 반복돼 자동 처리에서 빠진(stuck) 반응을 원인을 고친 뒤 다시 처리 대상으로 돌린다 |
| `backfill_events` | 필요할 때(아래 "백필") | 이벤트가 빠진 원본 행이 그대로 남는다 |

두 상시 프로세스는 여러 개를 동시에 돌려도 안전하고, DB나 MongoDB가 잠시 끊겨도 죽지 않고 다시 시도하며, SIGTERM에 정상 종료한다. 예외: 중계는 **MongoDB 설정(`MONGO_HOSTS`)이 없으면 다시 시도하지 않고 바로 멈춘다**(종료 코드 1, "이벤트 저장소 설정이 없어 중계를 멈춥니다"). 보낼 이벤트가 있을 때 드러나므로, 재시작해도 밀린 이벤트 때문에 바로 다시 멈춘다(재시작 반복으로 보인다). 웹은 MongoDB를 쓰지 않아 웹 노드에는 설정이 없어도 된다.

```bash
python manage.py process_reactions           # 반응 판정·과금(보류 해소 포함)
python manage.py relay_events                # outbox → MongoDB ad_events
python manage.py export_integrity --out DIR  # 원장·이벤트 정합성 점검(한 읽기 스냅샷). 결과는 NDJSON + manifest, 문제가 있으면 비정상 종료
python manage.py verify_ndjson DIR/event_gaps.manifest.json   # 게시된 결과가 manifest 와 맞는지 확인
python manage.py backfill_events --input DIR/event_gaps.manifest.json --out OUT          # 백필 미리보기(dry-run, 쓰지 않음)
python manage.py backfill_events --input DIR/event_gaps.manifest.json --out OUT --apply  # 원본 행에서 이벤트를 다시 만들어 outbox 에 씀(중계가 보냄)
python manage.py export_hop_manifests --out HOPS   # 원본 기대·outbox·MongoDB 세 구간의 창별 manifest
python manage.py verify_hops --dir HOPS            # 구간 대조. 확정 불일치·사슬 오류·고정점 불일치면 비정상 종료, 중계 지연 후보만 있으면 보고
```

- **중계가 충돌로 멈출 때**: `relay_events`가 "충돌로 중계를 멈춥니다"와 이벤트 ID를 남기고 비정상 종료하면, MongoDB에 같은 이벤트 ID로 **다른 내용**이 이미 있다는 뜻이다(이벤트 ID가 원천 행에서 결정적으로 정해지므로 정상 운영에서는 일어나지 않는다). 덮어쓰지 않는 것이 의도다. 충돌하지 않은 이벤트는 이미 보낸 것으로 표시됐고, 충돌한 행은 미전송으로 남아 있어 **원인을 해결하기 전에는 다시 띄워도 같은 배치에서 다시 멈춘다**. 로그의 이벤트 ID로 outbox 행(`events_outbox`)과 MongoDB 문서를 비교해 원인(수동 수정, 직렬화 변경 등)을 찾는다. outbox가 맞다고 확인되면 MongoDB의 그 문서를 지우고 다시 띄우면 중계가 다시 저장한다.
- **백필**은 이벤트가 빠진 원본 행이 있을 때(Step 4 이전 행, 장애 복구 뒤 보정) 운영자가 돌린다. 순서: `export_integrity` → `verify_ndjson` → `backfill_events`(dry-run으로 건수 확인) → `--apply` → `relay_events`가 보냄 → `export_integrity`로 누락 0 확인. 목록의 값은 쓰지 않고 원본 행에서 다시 만들며, 해석 불가가 있으면 비정상 종료한다. 실행은 감사 로그(`events.backfilled`)에 남는다.
- **구간 manifest**는 창(UTC 하루)이 끝나고 2분(`EVENTS_HOP_GRACE_SECONDS`) 뒤에 닫힌다. `verify_hops`는 감사 로그의 고정점과 대조하므로 같은 환경의 폴더를 쓴다(다른 환경에서 받은 폴더는 `--no-anchor`). 파이프라인 쪽 manifest는 `--pipeline`으로 MongoDB 구간과 대조한다.
- `export_integrity`의 결과는 이름에 내용 해시가 들어간 데이터 파일과 그것을 가리키는 manifest다. manifest가 가리키는 파일만 믿고, 옛 세대 파일은 자동으로 지우지 않는다. `checkpoint`는 점검 범위의 서술(스냅샷·시작 시각·훑은 행 수)이고 이어서 읽는 위치가 아니다.

## `check --deploy`

운영 설정은 `python -m django check --deploy --fail-level WARNING`으로 점검한다.
`security.W004`(HSTS 없음)·`security.W008`(HTTPS 리다이렉트 없음)을 **의도적으로 끈다**: HTTPS는 앞단 nginx가 맡고 Django는 HTTP로 받는다(6-5d, `config/settings/prod.py`에 사유). 6-5d 전에는 `security.W021`(HSTS 프리로드)만 껐는데, Django가 HSTS를 붙이지 않게 되어 그 경고는 더 나지 않는다.
직접 만든 경고는 없다. 6-3h의 프록시 설정 누락 경고(`foundation.W001`)는 6-5c에서 지웠다 — 신뢰할 프록시 수가 prod 필수값(1 이상)이 되어 빠뜨리면 기동하지 않는다.

## 알려진 사항

- 관리자 화면(Django admin)에서 사용자 관리와 감사 로그 열람이 가능하다. 사용자 변경·비밀번호 초기화는 감사 로그에 남고, 감사 로그는 읽기 전용이다. 첫 화면에는 반응 처리 현황 카드(대기·보류·stuck·가장 오래된 대기, stuck이 있으면 강조)가 있다.
- 이미지는 업로드 시 내장 ICC로 sRGB 변환한 뒤 메타데이터를 모두 버린다. 조작된 ICC 프로필로 lcms2(Pillow 번들)를 공격하는 위험은 완전히 막을 수 없어 위협 모델 T27·잔여 위험으로 관리한다(Pillow 업데이트 시 `pip-audit` 확인).
- 정적 파일(CSS·JS)은 운영에서도 Django가 서빙한다. **콘솔·운영 화면의 것은 프론트 서버**(`apps/ads_frontend`)가, 백 서버는 Django admin 의 것만 내준다(6-15 — 우리 화면은 프론트가 그린다). 백 서버도 `python manage.py collectstatic --noinput`으로 `STATIC_ROOT`(prod 환경변수, 기본 `./staticfiles`)에 모은 파일을 WhiteNoise가 내준다(시작할 때 읽으므로 모은 뒤 재시작). 앞단 nginx는 통로만 맡는다(설계 §10 "정적 파일 서빙"). 파일 이름에 해시를 붙이지 않아 캐시는 WhiteNoise 기본값(짧은 유효 시간)이다.

## 매체 키 (C1 인증)

매체 서버는 `X-Media-Key` 헤더로 키를 보낸다. 키는 관리자가 발급하며 **평문은 발급할 때 한 번만 출력**되고 저장되지 않는다.

```bash
python manage.py media_key issue  <매체 ID> --admin <관리자 아이디> --label 운영
python manage.py media_key rotate <매체 ID> --admin <관리자 아이디> --grace-hours 24   # 새 키 발급, 기존 키는 24시간 뒤 만료(그동안 둘 다 유효)
python manage.py media_key revoke <키 ID>   --admin <관리자 아이디>                  # 유출 시 즉시 폐기
```

요청 제한(`MEDIA_RATE_LIMITS`)은 프로세스 메모리 기반이라 워커가 여러 개면 한도가 그만큼 느슨해진다(설계 §10).

키 발급·교체(`issue`·`rotate`)와 매체 켜기·끄기는 매체 행을 잠근다. 그동안 그 매체의 결정 요청과 반응 판정이 잠시 기다린다(매체 생명주기 잠금, 설계 §10 "매체 비활성화와 판정·결정의 순서"). 키 폐기(`revoke`)는 매체 행을 잠그지 않는다.
