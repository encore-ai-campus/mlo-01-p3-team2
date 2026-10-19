#!/bin/bash
# game-server 를 한 프로세스(playdata-backend, :8000) → 소켓 프로세스 4개 + 작업 하나 + nginx(:8000) 로 바꾼다(README §3).
# 먼저 Redis·nginx·서비스 파일·사이트 파일이 설치돼 있어야 한다(README §1). 중간 확인 하나라도 실패하면 한 프로세스로 되돌린다.
# 사용(dev/ 에서): bash deploy/campus-multiprocess/switch-to-multiprocess.sh
ssh -o BatchMode=yes game-server "bash -s" <<'EOF'
set -uo pipefail
PORTS="9101 9102 9103 9104"
UNITS="$(for p in $PORTS; do printf 'playdata-backend@%s ' "$p"; done)playdata-campus-jobs"
rollback() {
  echo "!! 실패: 한 프로세스로 되돌린다"
  sudo rm -f /etc/nginx/sites-enabled/campus-backend; sudo systemctl reload nginx
  sudo systemctl disable --now $UNITS
  sudo systemctl enable --now playdata-backend; sleep 4; echo "playdata-backend $(systemctl is-active playdata-backend)"; exit 1
}
for need in /etc/systemd/system/playdata-backend@.service /etc/systemd/system/playdata-campus-jobs.service /etc/nginx/sites-available/campus-backend; do
  [ -f "$need" ] || { echo "없음: $need (README §1 먼저)"; exit 1; }
done
redis-cli ping >/dev/null || { echo "Redis 가 응답하지 않는다"; exit 1; }
echo "## :8000 접속 수 $(ss -Htn state established '( sport = :8000 )' | wc -l)"
sudo systemctl stop playdata-backend && sudo systemctl disable playdata-backend 2>&1 | tail -1
sudo systemctl enable --now $UNITS 2>&1 | tail -1
for port in $PORTS; do
  for _ in $(seq 30); do ss -Htln | grep -q "127.0.0.1:$port " && break; sleep 1; done
  ss -Htln | grep -q "127.0.0.1:$port " || { echo "port $port 안 뜸"; journalctl -u "playdata-backend@$port" --since "-1min" --no-pager | tail -5; rollback; }
done
echo "## 소켓 프로세스 4개 듣는 중"
sudo ln -sf /etc/nginx/sites-available/campus-backend /etc/nginx/sites-enabled/campus-backend
sudo nginx -t 2>&1 | tail -1 || rollback
sudo systemctl reload nginx || rollback
sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: 43.203.25.153' http://127.0.0.1:8000/accounts/login/)
echo "## nginx :8000 → 로그인 화면 $code"
[ "$code" = "200" ] || rollback
echo "## 상태: $(systemctl is-active $UNITS nginx redis-server | tr '\n' ' ')"
ss -Htlnp | grep -E ':8000|:910[1-4]|:6379' | awk '{print $4, $6}'
echo "## redis 연결 수 $(redis-cli client list | wc -l)"
journalctl -u 'playdata-backend@*' -u playdata-campus-jobs --since "-2min" --no-pager | grep -iE 'error|traceback|exception' | tail -5 || true
echo "## 끝. 되돌리기: README §4"
EOF
