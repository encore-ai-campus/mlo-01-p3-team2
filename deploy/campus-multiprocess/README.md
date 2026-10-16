# 메타버스 백엔드 여러 프로세스 배포 (game-server)

계획·측정: [docs/metaverse-multiprocess-plan.md](../../docs/metaverse-multiprocess-plan.md) M7.
지금의 `playdata-backend`(run-campus.py 하나, :8000)를 **daphne N개 + nginx(:8000, 세션 고정) + Redis + 작업 하나**로 바꾼다.
front-a 의 프론트 중계가 붙는 주소(game-server :8000)와 방화벽은 그대로다.

| 파일 | 설치 위치 |
|---|---|
| `playdata-backend@.service` | `/etc/systemd/system/` — 소켓 프로세스(%i = 포트 9101~) |
| `playdata-campus-jobs.service` | `/etc/systemd/system/` — 식단 사진·만료 세션 정리·Kafka outbox(하나만) |
| `nginx-campus-backend.conf` | `/etc/nginx/sites-available/campus-backend` → `sites-enabled/` |
| `redis-campus.conf` | `/etc/redis/redis.conf` 에 같은 값 |

프로세스 수는 **4개**로 시작한다(100명 모두 계속 움직여도 가장 바쁜 프로세스 46.5%, 로컬 운영 조건 측정). 늘리려면 nginx upstream 에 포트를 더하고 서비스를 하나 더 켠다.

## 0. 먼저 확인

- 새 코드에는 Redis 를 쓰는 판(`channels-redis`, `redis`)이 들어간다: `.venv/bin/pip install -r requirements.txt`(ad-server 와 달리 game-server 는 PyPI 에 닿는지 확인).
- 인프라: t3.2xlarge 의 CPU 크레딧 방식(`unlimited`/`standard`). 측정상 100명 모두 이동일 때 백엔드 전체가 운영 코어 약 2개분으로 기준 성능(3.2개분) 아래지만, `standard` 면 크레딧이 떨어진 뒤 더 낮게 묶인다.
- 8000 포트를 넘겨받는 순간 접속자가 모두 한 번 다시 연결된다(브라우저는 흩어진 간격으로 다시 붙는다). 사람이 적은 시간에 한다.

## 1. 설치 (서비스는 아직 켜지 않는다)

```bash
sudo apt-get install -y redis-server nginx
sudo tee -a /etc/redis/redis.conf < deploy/campus-multiprocess/redis-campus.conf   # 같은 키가 이미 있으면 그 줄을 고친다
sudo systemctl restart redis-server && redis-cli ping                              # PONG
sudo install -m 644 deploy/campus-multiprocess/playdata-backend@.service deploy/campus-multiprocess/playdata-campus-jobs.service /etc/systemd/system/
sudo install -m 644 deploy/campus-multiprocess/nginx-campus-backend.conf /etc/nginx/sites-available/campus-backend
sudo systemctl daemon-reload
```

## 2. 새 코드 (먼저 지금 방식 그대로)

`playdata-backend`(run-campus.py) 로 새 코드를 **Redis 주소 없이** 올린다. 코드는 지금과 똑같이 한 프로세스로 돈다(메모리 채널 계층).
여기서 문제가 없는지 본 뒤 다음으로 넘어간다. `migrate` 는 할 일이 없다(새 마이그레이션 없음).

## 3. 여러 프로세스로 바꾸기

```bash
sudo systemctl stop playdata-backend && sudo systemctl disable playdata-backend
sudo systemctl enable --now playdata-backend@9101 playdata-backend@9102 playdata-backend@9103 playdata-backend@9104 playdata-campus-jobs
sudo ln -s /etc/nginx/sites-available/campus-backend /etc/nginx/sites-enabled/campus-backend
sudo nginx -t && sudo systemctl reload nginx
```

확인:
- `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/` 가 응답한다(로그인 화면 302 등).
- `journalctl -u 'playdata-backend@*' -f` 에 오류가 없다. `redis-cli client list | wc -l` 이 프로세스 수만큼 늘어난다.
- 브라우저 둘로 접속해 서로 보이고 움직임·채팅이 오간다(같은 프로세스에 붙었는지는 상관없다).
- 작업 서비스 하나만 outbox 를 보낸다: `ps -eo args | grep -c '[c]ampus_jobs'` 가 1.

## 4. 되돌리기

```bash
sudo rm /etc/nginx/sites-enabled/campus-backend && sudo systemctl reload nginx
sudo systemctl disable --now playdata-backend@9101 playdata-backend@9102 playdata-backend@9103 playdata-backend@9104 playdata-campus-jobs
sudo systemctl enable --now playdata-backend
```

코드는 그대로 둬도 된다: Redis 주소가 없으면(옛 서비스는 넣지 않는다) 지금처럼 한 프로세스로 돈다. Redis 에는 다시 만들 수 있는 값(최신 위치)만 있어 지워도 된다.

## 5. 다음 천장: front-a 의 프론트 중계

모든 WebSocket 메시지는 front-a 의 파이썬 프로세스 하나(`frontend/pages/sockets.py`)를 지난다.
측정(계획 M6, 운영 코어 하나로 제한)상 100명이 모두 움직이면 이 중계가 **65.6%**(조절 23%)다. 실사용은 행동이 더 많아 70% 를 넘는다.
front-a nginx 는 인프라(Ansible `edge`)가 관리하므로 둘 중 하나를 요청한다.

- **WebSocket 만 nginx 가 game-server 로 바로 넘기기(권장):** `location /ws/campus/ { proxy_pass http://<game-server>:8000; … Upgrade 전달 … }`.
  파이썬 중계를 거치지 않아 CPU·지연이 준다. 백엔드 `DJANGO_ALLOWED_HOSTS` 에 브라우저가 쓰는 주소(공인 IP)가 있어야 한다(지금 HTTP 중계도 같은 Host 를 넘긴다).
- **중계 여러 개:** front-a 에 프론트 프로세스를 더 띄우고 `upstream edge_frontends`(이미 `least_conn`)에 서버를 더한다. 코드 변경이 없다.
