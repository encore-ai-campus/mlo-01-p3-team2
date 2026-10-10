#!/bin/bash
# Monitoring 서버의 수집 루프 (roles/monitoring). Monitoring이 SSH로 각 서버에서 가져온다(pull).
#   매 주기(기본 10초): 리소스(하트비트 겸용), 시스템 로그(journald), 서비스 로그(rsync)
#   N주기마다(기본 3 = 30초): 서비스 상태
# 서버별로 병렬 실행하고, SSH 연결은 ControlMaster로 재사용한다.
# 저장: metrics/<서버>/{resource,service}-<날짜>.log (한 줄에 한 샘플, 키=값), logs/<서버>/...
# 설정: /etc/infra-monitor/{monitor.conf,hosts.conf,secrets}
CONF=/etc/infra-monitor
. "$CONF/monitor.conf"   # DATA_DIR KEY REMOTE_DIR RESOURCE_INTERVAL SERVICE_EVERY FAIL_LIMIT

SSH=(ssh -i "$KEY" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
     -o UserKnownHostsFile="$DATA_DIR/state/known_hosts" -o ConnectTimeout=5
     -o ServerAliveInterval=2 -o ServerAliveCountMax=2
     -o ControlMaster=auto -o ControlPersist=120 -o ControlPath="$DATA_DIR/state/ssh-%C")
RSH=$(printf '%q ' "${SSH[@]}")

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
today() { date -u +%F; }

# 리소스: 접속에 성공하면 up, 실패하면 연속 실패 수를 올리고 FAIL_LIMIT번째부터 down. down 뒤에도 계속 시도한다.
one_resource() {
  local name=$1 ip=$2 f="$DATA_DIR/state/$1.fails" fails out state
  fails=$(cat "$f" 2>/dev/null || echo 0)
  if out=$(timeout 9 "${SSH[@]}" "monitor@$ip" "$REMOTE_DIR/resource.sh" 2>/dev/null) && [ -n "$out" ]; then
    echo 0 > "$f"
    echo "ts=$(now) host=$name reach=ok state=up fails=0 $out" >> "$DATA_DIR/metrics/$name/resource-$(today).log"
    return 0
  fi
  fails=$((fails + 1))
  echo "$fails" > "$f"
  state=up
  [ "$fails" -ge "$FAIL_LIMIT" ] && state=down
  echo "ts=$(now) host=$name reach=fail state=$state fails=$fails" >> "$DATA_DIR/metrics/$name/resource-$(today).log"
  return 1
}

# 시스템 로그: 마지막으로 받은 cursor 이후 항목만 가져온다. 전부 받은 경우에만(마지막 줄이 cursor) 저장하고 cursor를 갱신한다.
one_journal() {
  local name=$1 ip=$2 cf="$DATA_DIR/state/$1.journal-cursor" cmd tmp rc last
  tmp=$(mktemp "$DATA_DIR/state/journal.XXXXXX")
  if [ -s "$cf" ]; then
    printf -v cmd 'journalctl --no-pager -q -o short-iso --show-cursor --after-cursor=%q' "$(<"$cf")"
  else
    cmd='journalctl --no-pager -q -o short-iso --show-cursor --since=today'
  fi
  timeout 9 "${SSH[@]}" "monitor@$ip" "$cmd" > "$tmp" 2>/dev/null
  rc=$?
  if [ $rc -ne 0 ]; then
    # 연결 문제(255, 시간 초과)가 아니면 cursor가 더 이상 유효하지 않은 것이므로 버리고 다음 주기에 처음부터 시작한다.
    [ $rc -ne 255 ] && [ $rc -ne 124 ] && rm -f "$cf"
    rm -f "$tmp"; return 1
  fi
  last=$(tail -n 1 "$tmp")
  if [[ $last == "-- cursor: "* ]]; then
    sed '$d' "$tmp" >> "$DATA_DIR/logs/$name/journal/journal-$(today).log"
    echo "${last#-- cursor: }" > "$cf"
  fi
  rm -f "$tmp"
}

# 서비스 로그: rsync로 새로 붙은 부분만 가져온다. 삭제 옵션은 쓰지 않는다.
one_logs() {
  local name=$1 ip=$2 paths=$3 p dest
  local IFS=,
  for p in $paths; do
    if [[ $p == */ ]]; then
      dest="$DATA_DIR/logs/$name/$(basename "$p")/"
    else
      dest="$DATA_DIR/logs/$name/"
    fi
    mkdir -p "$dest"
    timeout 20 rsync -rt --ignore-missing-args -e "$RSH" "monitor@$ip:$p" "$dest" 2>/dev/null
  done
}

# 서비스 상태: 표준입력으로 DB monitor 비밀번호를 넘긴다.
one_service() {
  local name=$1 ip=$2 secret=$3 pw="" out
  [ "$secret" != none ] && pw=$(grep "^$secret=" "$CONF/secrets" | cut -d= -f2-)
  out=$(printf '%s\n' "$pw" | timeout 15 "${SSH[@]}" "monitor@$ip" "$REMOTE_DIR/service.sh" 2>/dev/null)
  [ -n "$out" ] && echo "ts=$(now) host=$name $out" >> "$DATA_DIR/metrics/$name/service-$(today).log"
}

tick=0
while true; do
  start=$(date +%s)
  while IFS='|' read -r name ip paths secret; do
    [ -z "$name" ] || [[ $name == \#* ]] && continue
    (
      mkdir -p "$DATA_DIR/metrics/$name" "$DATA_DIR/logs/$name/journal"
      if one_resource "$name" "$ip"; then
        one_journal "$name" "$ip"
        one_logs "$name" "$ip" "$paths"
        [ $((tick % SERVICE_EVERY)) -eq 0 ] && one_service "$name" "$ip" "$secret"
      fi
    ) &
  done < "$CONF/hosts.conf"
  wait
  tick=$((tick + 1))
  elapsed=$(($(date +%s) - start))
  [ "$elapsed" -lt "$RESOURCE_INTERVAL" ] && sleep $((RESOURCE_INTERVAL - elapsed))
done
