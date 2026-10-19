#!/bin/bash
# 배포 전 점검(읽기만): game-server·front-a 의 지금 구성 — 서비스·경로·코드 버전·판·포트·접속 수·디스크·바깥 접속.
# 아무것도 바꾸지 않는다. .env 는 키 이름만 보이고 값은 출력하지 않는다. 사용(dev/ 에서): bash deploy/campus-multiprocess/preflight.sh
set -u

remote() {
  ssh -o ConnectTimeout=20 -o BatchMode=yes "$1" 'bash -s' <<'EOF'
set -u
section() { printf '\n## %s\n' "$1"; }
section "호스트"; hostname; uptime; lsb_release -ds 2>/dev/null; python3 --version
section "서비스(이름에 playdata·campus·frontend·backend·nginx·redis)"
systemctl list-units --type=service --all --no-pager --plain 2>/dev/null | grep -iE 'playdata|campus|frontend|backend|daphne|gunicorn|nginx|redis|mysqlrouter' | awk '{print $1, $3, $4}'
section "서비스 파일(비밀이 있을 만한 줄은 뺀다)"
for unit in $(systemctl list-unit-files --type=service --no-pager --plain 2>/dev/null | awk '{print $1}' | grep -iE 'playdata|campus|frontend|backend'); do
  echo "--- $unit"; systemctl cat "$unit" 2>/dev/null | grep -vE '^\s*(#|$)' | grep -viE 'password|secret|token|passwd|key='
done
section "홈"; ls -la ~
for dir in ~/backend ~/frontend ~/app ~/campus; do
  [ -d "$dir" ] || continue
  section "$dir"; ls -la "$dir" | head -40; du -sh "$dir" 2>/dev/null
  (cd "$dir" && git rev-parse --short HEAD 2>/dev/null && git log -1 --format='%cd %s' 2>/dev/null && git status --short 2>/dev/null | head -20)
  [ -f "$dir/.env" ] && { echo "--- .env(키 이름만)"; stat -c '%a %U' "$dir/.env"; grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$dir/.env" | tr '\n' ' '; echo; }
  for venv in "$dir/.venv" "$dir/venv" ~/django-venv; do
    [ -x "$venv/bin/python" ] || continue
    echo "--- $venv"; "$venv/bin/python" -V
    "$venv/bin/pip" freeze 2>/dev/null | grep -iE '^(django|channels|channels-redis|daphne|redis|twisted|autobahn|mysqlclient|websockets)=='
  done
done
section "듣는 포트"; ss -Htlnp 2>/dev/null | awk '{print $4, $6}' | sort -u
section "접속 수(established)"; for port in 8000 8004 443 80; do printf ':%s %s\n' "$port" "$(ss -Htn state established "( sport = :$port )" 2>/dev/null | wc -l)"; done
section "nginx·redis 판"; dpkg -l 2>/dev/null | awk '/^ii/ && $2 ~ /^(nginx|nginx-common|redis-server|redis-tools)$/ {print $2, $3}'
apt-cache policy nginx redis-server 2>/dev/null | grep -E '^[a-z]|Candidate'
if command -v nginx >/dev/null; then
  section "nginx 설정(server·location·upstream·proxy_pass 줄만)"
  sudo -n nginx -T 2>/dev/null | grep -nE '^# configuration file|upstream|server |listen|location|proxy_pass|Ansible' | head -60
fi
section "디스크·메모리"; df -h ~ | tail -1; free -m | head -2; nproc
section "바깥 접속(PyPI·apt 프록시)"
curl -sS -m 6 -o /dev/null -w 'pypi 직접 %{http_code}\n' https://pypi.org/simple/redis/ 2>&1 | tail -1
curl -sS -m 6 -x http://10.10.0.152:3128 -o /dev/null -w 'pypi 프록시 %{http_code}\n' https://pypi.org/simple/redis/ 2>&1 | tail -1
grep -rhoiE 'proxy[^;]*' /etc/apt/apt.conf.d/ 2>/dev/null | head -3
EOF
}

for host in game-server front-a; do
  printf '\n==================== %s ====================\n' "$host"
  remote "$host"
done
