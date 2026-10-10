#!/usr/bin/env bash
# InnoDB Cluster(3노드 + Router, 자동 failover)에서 전체 점검과 150 동시 부하를 돌린다. 운영과 비슷한 환경에서의 시험이다(Docker 필요, 수 분).
#
#   scripts/cluster_check.sh            클러스터를 띄워 check.sh(전체 시험 977개·20 동시 부하·보안 점검)와 150 동시 부하를 돌리고 지운다
#   scripts/cluster_check.sh --failure  거기에 클러스터 장애 시험(primary 강제 종료·계획된 전환 등, 자체 클러스터를 따로 띄운다)까지
#   PYTHON=/path/to/python              사용할 파이썬(기본: python)
#
# 실패하면 비정상 종료한다. 클러스터는 어떤 경우에도 지운다. 구성은 scripts/mysql_cluster.py, 이미지는 docker/innodb-cluster/.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
failures=()

# 이전 실행의 값이 환경에 남아 있어도 이번 실행이 만든 클러스터만 다룬다: 먼저 비우고, 기동 명령의 **종료 코드**를 직접 확인한 뒤(eval 의 결과가 아니라),
# 이번에 출력된 클러스터 ID 가 있을 때만 정리 trap 을 설치한다. 기동이 실패하면 후속 시험도, 이전 ID 에 대한 정리 호출도 하지 않고 비정상 종료한다.
unset MYSQL_CLUSTER_ID DB_HOST DB_PORT DB_USER DB_PASSWORD
if ! start_output="$("$PY" scripts/mysql_cluster.py start)"; then
  echo "클러스터를 띄우지 못했다" >&2
  exit 1
fi
eval "$start_output"
if [ -z "${MYSQL_CLUSTER_ID:-}" ] || [ -z "${DB_PORT:-}" ]; then
  echo "클러스터 기동 출력에 클러스터 ID·접속 값이 없다" >&2
  exit 1
fi
trap '"$PY" scripts/mysql_cluster.py stop "$MYSQL_CLUSTER_ID"' EXIT
echo "InnoDB Cluster $MYSQL_CLUSTER_ID (Router 포트 $DB_PORT)"

scripts/check.sh || failures+=("check.sh")
"$PY" scripts/load_test.py || failures+=("load_test(150 동시)")
if [ "${1:-}" = "--failure" ]; then
  "$PY" scripts/failure_test.py --mysql cluster || failures+=("failure_test(cluster)")
fi

if [ ${#failures[@]} -gt 0 ]; then printf '\n실패: %s\n' "${failures[*]}"; exit 1; fi
echo "클러스터 점검 모두 통과"
