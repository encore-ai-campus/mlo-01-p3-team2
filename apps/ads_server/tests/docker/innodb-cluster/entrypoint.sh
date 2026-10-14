#!/bin/sh
# 역할: node | router | shell
set -e
role="$1"; shift || true
case "$role" in
  node)
    # 최초 기동에서만 초기화한다. 초기화 SQL 은 **바이너리 로그에 남기지 않는다**(노드마다 GTID 가 달라져 그룹 합류를 막는 일을 피한다).
    if [ ! -d /var/lib/mysql/mysql ]; then
      pw=$(printf '%s' "$MYSQL_ROOT_PASSWORD" | sed "s/'/''/g")
      printf "SET sql_log_bin=0;\nALTER USER 'root'@'localhost' IDENTIFIED BY '%s';\nCREATE USER 'root'@'%%' IDENTIFIED BY '%s';\nGRANT ALL ON *.* TO 'root'@'%%' WITH GRANT OPTION;\n" "$pw" "$pw" > /tmp/init.sql
      mysqld --initialize-insecure --init-file=/tmp/init.sql
      rm /tmp/init.sql
    fi
    exec mysqld --server-id="$SERVER_ID" --report-host="$NODE_NAME" "$@"
    ;;
  router)
    # 클러스터 관리 계정으로 부트스트랩(라우터 계정이 자동으로 만들어진다)한 뒤 라우터를 앞에서 돌린다. 다른 컨테이너의 접속을 받도록 0.0.0.0.
    if [ ! -f /router/mysqlrouter.conf ]; then
      printf '%s' "$BOOTSTRAP_PASSWORD" | mysqlrouter --bootstrap "$BOOTSTRAP_URI" --directory /router --force --conf-bind-address 0.0.0.0 --report-host "$ROUTER_NAME" --user=mysql --name "$ROUTER_NAME" 1>&2 \
        || { echo "router bootstrap failed" >&2; exit 1; }
    fi
    exec mysqlrouter -c /router/mysqlrouter.conf
    ;;
  shell)
    exec mysqlsh "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
