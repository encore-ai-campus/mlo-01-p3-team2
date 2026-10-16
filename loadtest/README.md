# 메타버스 백엔드 부하 시험 (로컬)

운영 game-server 와 같은 조건에서 N명이 접속했을 때 백엔드가 얼마나 버티는지 잰다. 계획: [docs/metaverse-optimization-plan.md](../docs/metaverse-optimization-plan.md) 0단계.

## 운영과 맞춘 것

| 항목 | 운영 (2026-10-16 확인) | 여기 |
|---|---|---|
| OS·Python | Ubuntu 24.04, Python 3.12.3 | 같은 이미지(`Dockerfile`) |
| 패키지 | game-server·front-a 의 `pip freeze` | `requirements-prod.txt`·`requirements-front.txt` (같은 버전) |
| 실행 방식 | `run-campus.py --noreload` (runserver/daphne 한 프로세스, 메모리 채널 계층) | 같음 |
| CPU | t3.2xlarge vCPU 8. 이 프로세스는 GIL 때문에 코어 하나 분량이 한계 | 컨테이너 `cpuset 0-7` + `cpu_quota 5000/10000` = 운영 코어 하나의 속도(`corebench.py`: 운영 0.451초, 여기 0.458초) |
| DB | MySQL 8.4 클러스터(라우터 경유), 주 서버 왕복 약 0.26ms | MySQL 8.4 컨테이너 하나 + 백엔드에서 나가는 패킷에 0.25ms 지연(`tc netem`) |
| Kafka | 주소는 있지만 닿지 않음(outbox 적체) | 닿지 않는 주소(같은 상태) |
| DM | 켜짐(`CAMPUS_DM_ENABLED=1`) | 켜짐 |

다른 점: 그룹 복제의 쓰기 인증 비용은 없다(운영의 쓰기가 조금 더 느리다). 프론트 중계(front-a)를 거치지 않고 백엔드에 바로 붙는다.

## 브라우저 흉내 (`campus_load.py`)

`frontend/dist` 의 실제 주기를 따른다.
- 5초마다 `ping`.
- `input` 은 키가 있을 때만 0.1초마다(`--client new`, 기본 — 지금 브라우저). `--client current` 는 계획 1c 이전(키를 안 눌러도 0.1초마다).
- 15초마다 HTTP 조회 둘(세션 상태·DM). 추첨 조회는 기능을 없애면서 빠졌다.
- 끊기면 1→10초 간격으로 다시 연결.
- 이동은 "쉬기 → 2~4초 이동"을 되풀이하고, `--moving` 이 이동 중인 시간의 비율이다(기본 0.2).

## 실행

```bash
# dev/ 에서. 처음 한 번 이미지가 만들어진다
python loadtest/run.py --label base-u100 --out /tmp/campus-load --users 100
```

결과 JSON 의 주요 값:
- `server.prod_core_pct`: 운영 코어 하나 대비 사용률. 100이면 포화.
- `server.db_per_s`: 초당 질의·새 연결 수(`Connections`).
- `client.own_state_gap_ms`: 움직이는 동안 본인 상태가 오는 간격. 정상은 약 33ms.
- `client.input_to_moving_ms`: 키를 누른 뒤 움직이기 시작할 때까지.
- `client.peer_move_gap_ms`: 다른 사람이 움직일 때 그 위치가 오는 간격. 정상은 약 100ms.
- `client.http_ms`: HTTP 조회 응답 시간.
- `client.closes`: 비정상 종료 코드.
- `client.generator_loop_lag_ms`: 생성기 자신의 지연. 이것이 크면 결과를 믿지 않는다.

실험용 설정(운영 설정이 아니다, `--settings` 로 고른다):
- `settings_reuse`: 모든 DB 연결을 재사용(`CONN_MAX_AGE`). ASGI 에서 소켓마다 연결을 붙잡아 100명에서 MySQL 상한을 넘는 것을 보였다.
- `settings_notls`: DB 연결에 TLS 를 쓰지 않음. 연결마다의 TLS 비용을 잴 때 썼다(계획 2.8 — 운영에는 쓰지 않는다).

`--polls 0` 은 HTTP 조회를 끈다(원인 나누기용).

## 여러 프로세스 (계획 docs/metaverse-multiprocess-plan.md M2~M6)

```bash
python loadtest/run.py --label pubsub-u100 --out <폴더> --users 100 --redis          # 한 프로세스 + Redis 채널 계층
python loadtest/run.py --label b4-u100 --out <폴더> --users 100 --moving 1.0 --backends 4               # daphne 4개 + 작업 하나 + nginx + Redis
python loadtest/run.py --label relay-b4 --out <폴더> --users 100 --moving 1.0 --backends 4 --via-frontend  # 프론트 중계(운영 코어 하나)를 거쳐
docker compose -f loadtest/compose.yaml --profile check run --rm cluster-check       # 두 프로세스 사이 기능 12가지 확인
```

- `--backends N`: 소켓 프로세스를 컨테이너 하나에 하나씩(각각 운영 코어 하나) 띄운다. 앞에서 nginx 가 세션 쿠키로 고정 배정한다(`nginx-backend.conf`, 운영 `deploy/campus-multiprocess` 와 같은 규칙).
- 결과 JSON 의 `backends_prod_core_pct`(프로세스별)·`busiest_prod_core_pct`(가장 바쁜 프로세스 — 지연을 정한다)·`backends_total_prod_cores`·`connections_per_backend`·`redis_*`·`nginx_prod_core_pct`·`frontend_prod_core_pct`.
- 지금까지의 결과: `results/`.
- 주의: 개발 서버를 띄운 채 손으로 `docker compose --profile load run load …` 를 하면 mysql·backend 가 다시 만들어져 DB 가 비워질 수 있다. 손으로 생성기를 돌릴 때는 `run --no-deps` 를 쓴다(run.py 는 그렇게 한다).

## 개발 서버로 띄우기 (사람이 접속해 보기)

같은 조건(운영 코어 하나·MySQL 8.4)의 백엔드에 프론트를 붙여 내부망에 연다. 프론트가 HTTP·WebSocket 을 백엔드로 중계한다(운영 front-a 와 같은 구조).

```bash
# dev/ 에서. LAN 은 이 컴퓨터의 내부 IP(맥: ipconfig getifaddr en0)
LAN=192.168.0.109
FRONTEND_BIND=0.0.0.0 FRONTEND_HOSTS=$LAN,localhost,127.0.0.1 BACKEND_HOSTS=backend,$LAN,localhost,127.0.0.1 \
CSRF_ORIGINS=http://$LAN:8004,http://localhost:8004 \
docker compose -f loadtest/compose.yaml --profile dev up -d --wait backend frontend
python loadtest/watch.py          # 실시간: 운영 코어·백엔드 연결(≈ 접속자)·DB
docker compose -f loadtest/compose.yaml logs -f backend | grep -E "closed by server|waited"   # 끊는 이유·느린 DB
```

접속: `http://<LAN>:8004/` (새 DB 라 회원가입부터 한다). `FRONTEND_BIND` 를 빼면 이 컴퓨터(127.0.0.1)에서만 열린다.
CPU 제한을 풀려면 `BACKEND_CPU_QUOTA=100000` 을 함께 준다.

끝나면 `docker compose -f loadtest/compose.yaml --profile dev down -v` 로 지운다(DB 도 지워진다).
