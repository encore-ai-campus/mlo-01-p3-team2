# InnoDB Cluster 시험용 이미지 하나(서버·Shell·Router). 서버는 인프라의 intake/db-standalone/mysql 과 같은 방식(공식 generic tarball, 8.4.11)이고,
# AdminAPI 용 MySQL Shell 과 MySQL Router 는 같은 8.4 LTS 의 generic tarball 이다(arm64/x86_64 모두).
# 역할은 첫 인자로 고른다: node(서버) · router · shell. 포트·비밀번호는 호출한 쪽(tests/tools/mysql_cluster.py)이 무작위로 정한다.
FROM ubuntu:24.04

ARG MYSQL_VERSION=8.4.11
ARG SHELL_VERSION=8.4.10
ARG ROUTER_VERSION=8.4.10
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl xz-utils libaio1t64 libnuma1 libncurses6 libssl3t64 \
 && ARCH=$(uname -m) \
 && ln -s /usr/lib/${ARCH}-linux-gnu/libaio.so.1t64 /usr/lib/${ARCH}-linux-gnu/libaio.so.1 \
 && case "$ARCH" in aarch64) SHELL_ARCH=arm-64bit ;; x86_64) SHELL_ARCH=x86-64bit ;; *) echo "unsupported $ARCH"; exit 1 ;; esac \
 && curl -fsSL https://cdn.mysql.com/Downloads/MySQL-8.4/mysql-${MYSQL_VERSION}-linux-glibc2.28-${ARCH}.tar.xz | tar -xJ -C /opt \
 && mv /opt/mysql-${MYSQL_VERSION}-* /opt/mysql && rm -rf /opt/mysql/lib/mysqlrouter /opt/mysql/bin/*debug* \
 && curl -fsSL https://cdn.mysql.com/Downloads/MySQL-Shell/mysql-shell-${SHELL_VERSION}-linux-glibc2.28-${SHELL_ARCH}.tar.gz | tar -xz -C /opt \
 && mv /opt/mysql-shell-* /opt/mysqlsh \
 && curl -fsSL https://cdn.mysql.com/Downloads/MySQL-Router/mysql-router-${ROUTER_VERSION}-linux-glibc2.28-${ARCH}.tar.xz | tar -xJ -C /opt \
 && mv /opt/mysql-router-* /opt/mysqlrouter \
 && apt-get purge -y curl xz-utils && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && groupadd -r mysql && useradd -r -g mysql -m -s /bin/bash mysql \
 && mkdir -p /var/lib/mysql /var/run/mysqld /router && chown -R mysql:mysql /var/lib/mysql /var/run/mysqld /router

# MySQL Shell 이 동적으로 링크하는 라이브러리(없으면 mysqlsh 가 실행되지 않는다)
RUN apt-get update && apt-get install -y --no-install-recommends libkeyutils1 libkrb5-3 libgssapi-krb5-2 && rm -rf /var/lib/apt/lists/*

ENV LC_ALL=C.UTF-8
ENV PATH=/opt/mysql/bin:/opt/mysqlsh/bin:/opt/mysqlrouter/bin:$PATH
COPY my.cnf /etc/my.cnf
COPY entrypoint.sh /entrypoint.sh
USER mysql
ENTRYPOINT ["/entrypoint.sh"]
