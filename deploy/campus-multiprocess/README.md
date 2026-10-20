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

먼저 `bash deploy/campus-multiprocess/preflight.sh`(로컬, 읽기만)로 두 서버의 서비스·경로·판·포트·접속 수를 본다.

game-server 의 바깥 접속은 프록시(10.10.0.152:3128)뿐인데, **이 프록시는 HTTPS 만 넘기고 HTTP 는 넘기지 않는다**(10/17 확인).
apt 소스가 `http://` 라 그대로는 받지 못한다 — 인프라에 요청하거나, 시스템 설정은 두고 이번 설치에만 https 미러를 쓴다:

```bash
A=/tmp/apt-https; mkdir -p $A/parts $A/lists/partial
sed -E 's#^URIs: http://(ap-northeast-2\.ec2\.archive\.ubuntu\.com|security\.ubuntu\.com)/ubuntu/?#URIs: https://ap-northeast-2.ec2.archive.ubuntu.com/ubuntu/#' \
  /etc/apt/sources.list.d/ubuntu.sources > $A/parts/ubuntu-https.sources
OPT="-o Dir::Etc::SourceList=/dev/null -o Dir::Etc::SourceParts=$A/parts -o Dir::State::Lists=$A/lists"
sudo apt-get $OPT update && sudo apt-get $OPT install -y redis-server nginx
sudo rm -f /etc/nginx/sites-enabled/default   # 기본 사이트(:80)는 쓰지 않는다
```

```bash
sudo tee -a /etc/redis/redis.conf < deploy/campus-multiprocess/redis-campus.conf   # 같은 키가 이미 있으면 그 줄을 고친다
sudo systemctl restart redis-server && redis-cli ping                              # PONG
sudo install -m 644 deploy/campus-multiprocess/playdata-backend@.service deploy/campus-multiprocess/playdata-campus-jobs.service /etc/systemd/system/
sudo install -m 644 deploy/campus-multiprocess/nginx-campus-backend.conf /etc/nginx/sites-available/campus-backend
sudo systemctl daemon-reload
```

## 2. 새 코드 (먼저 지금 방식 그대로)

`playdata-backend`(run-campus.py) 로 새 코드를 **Redis 주소 없이** 올린다. 코드는 지금과 똑같이 한 프로세스로 돈다(메모리 채널 계층).
프론트도 같이 올린다: 점프·찌르기가 0.1초 위치 묶음에 실려 오므로(`presence.js`) 옛 탭은 새로고침해야 그것을 본다(채팅·이동은 옛 탭도 받는다).
여기서 문제가 없는지 본 뒤 다음으로 넘어간다. `migrate` 는 할 일이 없다(새 마이그레이션 없음).

## 3. 여러 프로세스로 바꾸기

`bash deploy/campus-multiprocess/switch-to-multiprocess.sh`(로컬에서) 가 아래를 한 번에 하고, 중간 확인이 실패하면 한 프로세스로 되돌린다. 손으로 할 때:

```bash
sudo systemctl stop playdata-backend && sudo systemctl disable playdata-backend
sudo systemctl enable --now playdata-backend@9101 playdata-backend@9102 playdata-backend@9103 playdata-backend@9104 playdata-campus-jobs
sudo ln -s /etc/nginx/sites-available/campus-backend /etc/nginx/sites-enabled/campus-backend
sudo nginx -t && sudo systemctl reload nginx
```

확인:
- `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/` 가 응답한다(로그인 화면 302 등).
- `journalctl -u 'playdata-backend@*' -f` 에 오류가 없다. `redis-cli client list | wc -l` 이 프로세스 수만큼 늘어난다.
- 브라우저 둘로 접속해 서로 보이고 움직임·채팅·점프가 오간다(같은 프로세스에 붙었는지는 상관없다).
- 웹소켓이 고르게 붙는다(`least_conn`): `for p in 9101 9102 9103 9104; do ss -Htn state established "( sport = :$p )" | wc -l; done` 가 비슷하다. HTTP 는 세션 고정(쿠키 해시) 그대로다.
- 작업 서비스 하나만 outbox 를 보낸다: `ps -eo args | grep -c '[c]ampus_jobs'` 가 1.

## 4. 되돌리기

```bash
sudo rm /etc/nginx/sites-enabled/campus-backend && sudo systemctl reload nginx
sudo systemctl disable --now playdata-backend@9101 playdata-backend@9102 playdata-backend@9103 playdata-backend@9104 playdata-campus-jobs
sudo systemctl enable --now playdata-backend
```

코드는 그대로 둬도 된다: Redis 주소가 없으면(옛 서비스는 넣지 않는다) 지금처럼 한 프로세스로 돈다. Redis 에는 다시 만들 수 있는 값(최신 위치)만 있어 지워도 된다.

## 5. front-a: WebSocket 을 game-server 로 바로 넘기기 (인프라 요청)

지금은 모든 WebSocket 메시지가 front-a 의 파이썬 프로세스 하나(`frontend/pages/sockets.py`)를 지난다. 이 중계가 다음 천장이다.
front-a nginx 는 인프라(Ansible `edge` 역할)가 관리하므로 아래 변경을 요청한다. 앱 코드와 브라우저는 바꿀 것이 없다(주소 `/ws/campus/` 그대로).

측정(계획 M6, 로컬에 같은 edge 설정을 두고 100명·소켓 프로세스 4개, 중계는 운영 코어 하나):

| 100명 모두 계속 이동 | 프론트(중계) | edge nginx | 키 → 움직임 상위 5% | 다른 사람 위치 간격 상위 5% |
|---|---|---|---|---|
| 지금(edge → 중계 → game-server) | **69.4~70.2%**(조절 20%) | 15.8% | 38.8ms | 123ms |
| 바로 넘기기(edge → game-server) | **4.3%**(HTTP 만) | 18.5% | 36.0ms | 128ms |

`aws-platform/platform/roles/edge/templates/nginx.conf.j2` 의 443 server, `location /` 앞에 더한다(변수가 없으면 지금과 같다):

```nginx
{% if edge_campus_ws_backend | default('') %}
        # 메타버스 WebSocket 은 프론트 중계를 거치지 않고 game-server nginx(:8000, 세션 고정)로 바로 보낸다.
        location /ws/campus/ {
            proxy_pass http://{{ edge_campus_ws_backend }};
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $edge_connection_upgrade;
            proxy_connect_timeout 5s;
            proxy_read_timeout 3600s;
            proxy_next_upstream error timeout;
        }
{% endif %}
```

- front-a 인벤토리: `edge_campus_ws_backend: <game-server 사설 IP>:8000` — 프론트 `BACKEND_URL` 과 같은 주소다. 방화벽은 지금 중계가 쓰는 길(front-a → game-server :8000)과 같다.
- 백엔드는 바꿀 것이 없다: 중계도 브라우저의 `Origin`·쿠키를 그대로 넘기므로 `DJANGO_ALLOWED_HOSTS` 에 공인 주소가 이미 있다. game-server 의 세션 고정(쿠키 해시)도 같다.
- 여러 프로세스(§3)와 따로 할 수 있다(지금의 한 프로세스 :8000 에도 그대로 붙는다).
- 확인: 게임 화면에서 서로 보이고 움직이면 된다. front-a 의 프론트 로그에 `/ws/campus/` 가 더는 찍히지 않고, nginx access log 에 `GET /ws/campus/… 101` 이 남는다.
- 되돌리기: 변수를 지우고 edge 를 다시 적용한다. `reload` 때 이미 열린 연결은 끊기지 않고, 새 연결부터 바뀐다.
- 다른 길(중계 여러 개, `upstream edge_frontends` 에 서버 추가)은 중계 CPU 를 나눌 뿐 홉이 그대로라 권하지 않는다.

## 6. 운영 반영 기록 (10/17, 운영 전 시험)

- 백업: 두 서버 `~/deploy-backups/metaverse-multiprocess-20261017-1559/`(코드 전체·`.venv`·`.env`·서비스 파일·front-a `nginx.conf`·`/var/www/playdata-campus`).
- 운영 코드는 `origin/dev` 에 서버에서 직접 올린 옥상 사진 순환(광고 스크립트 끔)이 더해진 것이었다(파일은 CRLF — 견줄 때 CR 을 뺀다). 코드에 반영해 배포했다.
- game-server: 새 코드(한 프로세스로 먼저 확인) → Redis 7.0.15·nginx 1.24.0(https 미러) → 소켓 프로세스 4개·작업 하나·nginx `:8000`. 옛 `playdata-backend` 는 꺼 두었다(disabled).
- front-a: 새 프론트 + `collectstatic` → `/var/www/playdata-campus/static`(root:www-data), nginx `location /ws/campus/` → `10.10.10.166:8000`
  (이전 설정 `/etc/nginx/nginx.conf.before-ws-direct-20261017-1559`). nginx 는 Ansible `edge` 관리라 인프라에 알린다.
