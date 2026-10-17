#!/bin/bash
# 운영(https://43.203.25.153)에 실사용 모방 봇을 붙인다 — 시드한 세션(load000~, 비밀번호 로그인 불가)으로. 세션은 미리 data 볼륨의 /data/sessions.json 에 둔다.
# 사용(dev/ 에서): bash loadtest/prod-bots.sh start [사람 수=50] | status | stop
#   start: 뒤에서 돌기 시작한다(멈출 때까지 잰다).  stop: 멈추고 그때까지의 결과(JSON)를 loadtest/results/prod-real-u<N>-<시각>.json 에 남긴다.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=campus-prod-bots
C="docker compose -f loadtest/compose.yaml --profile load"
case "${1:-}" in
  start)
    USERS=${2:-50}
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    $C run -d --no-deps --name "$NAME" -e CAMPUS_HOST=43.203.25.153 -e CAMPUS_PORT=443 -e CAMPUS_SCHEME=https \
      load python campus_load.py --behavior real --client new --users "$USERS" --ramp 30 --warmup 10 --measure 86400 --polls 15 >/dev/null
    echo "봇 ${USERS}명 시작 $(date +%H:%M:%S) — 멈추기: bash loadtest/prod-bots.sh stop"
    ;;
  status)
    docker ps --filter "name=$NAME" --format '{{.Names}} {{.Status}}'
    ;;
  stop)
    docker kill --signal=TERM "$NAME" >/dev/null
    docker wait "$NAME" >/dev/null
    out="loadtest/results/prod-real-$(date +%Y%m%d-%H%M).json"
    docker logs "$NAME" 2>/dev/null | grep '^{' | tail -1 > "$out"
    docker rm "$NAME" >/dev/null
    echo "멈춤 $(date +%H:%M:%S) — 결과 $out"
    ;;
  *) echo "사용: bash loadtest/prod-bots.sh start [사람 수] | status | stop"; exit 1 ;;
esac
