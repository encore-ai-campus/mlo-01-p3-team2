#!/bin/bash
# 리소스 한 줄(키=값)을 출력한다. 읽기 전용이며 Monitoring이 SSH로 실행한다 (roles/monitoring).
# CPU와 네트워크는 누적 값이므로 비율은 수집된 샘플 사이의 차이로 계산한다.
read -r _ u n s i w q sq st _ < /proc/stat
cpu_total=$((u + n + s + i + w + q + sq + st))
cpu_busy=$((cpu_total - i - w))
read -r l1 l5 l15 _ < /proc/loadavg
mem_total=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
read -r disk_total disk_used < <(df -Pk / | awk 'NR==2 {print $2, $3}')
read -r rx tx < <(awk -F'[: ]+' 'NR>2 && $2!="lo" {rx+=$3; tx+=$11} END {print rx+0, tx+0}' /proc/net/dev)
uptime_s=$(cut -d. -f1 /proc/uptime)
echo "cpu_busy=$cpu_busy cpu_total=$cpu_total load1=$l1 load5=$l5 load15=$l15 mem_total_kb=$mem_total mem_avail_kb=$mem_avail disk_root_total_kb=$disk_total disk_root_used_kb=$disk_used net_rx_bytes=$rx net_tx_bytes=$tx uptime_s=$uptime_s"
