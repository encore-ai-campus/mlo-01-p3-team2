#!/bin/bash
# 개발 서버를 운영에 올릴 구조로 띄운다(계획 M5·M6·§8):
#   브라우저 → edge nginx(:8080, 운영 front-a 자리) → HTTP 는 프론트, 웹소켓은 game-server nginx(least_conn) → 소켓 프로세스 4개 + 작업 하나 + Redis
# 사용(dev/ 에서): bash loadtest/dev-server.sh [LAN 주소]   — 주소를 빼면 이 맥의 en0. 봇은 README '개발 서버에 봇 붙이기'
set -euo pipefail
cd "$(dirname "$0")/.."
LAN=${1:-$(ipconfig getifaddr en0)}
export EDGE_BIND=0.0.0.0 EDGE_WS_UPSTREAM=nginx:8000 CAMPUS_REDIS_URL=redis://redis:6379/0 \
  BACKEND_RUN="daphne -b 0.0.0.0 -p 9003 config.asgi:application" FRONTEND_BACKEND_URL=http://nginx:8000 \
  BACKEND_HOSTS="backend,nginx,frontend,edge,localhost,127.0.0.1,$LAN" FRONTEND_HOSTS="frontend,edge,localhost,127.0.0.1,$LAN" \
  CSRF_ORIGINS="http://$LAN:8080,http://localhost:8080"
C="docker compose -f loadtest/compose.yaml --profile dev --profile multi --profile edge"
# nginx·edge 는 시작할 때 이름을 주소로 푼다: 소켓 프로세스·프론트를 먼저 띄우고, 그 뒤에 새로 띄운다
$C up -d --wait --force-recreate --scale backend=4 backend jobs nginx frontend
$C up -d --force-recreate --no-deps edge
for _ in $(seq 30); do curl -fsS -o /dev/null "http://127.0.0.1:8080/health/" && break; sleep 1; done
echo "개발 서버: http://$LAN:8080/  (끄기: $C stop)"
