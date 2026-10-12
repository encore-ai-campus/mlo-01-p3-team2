#!/usr/bin/env python
"""시험용 MySQL InnoDB Cluster(그룹 복제, 단일 primary, 자동 failover) 3노드 + MySQL Router 1대를 Docker 로 띄운다.

    python scripts/mysql_cluster.py start      클러스터를 만들고 접속 값을 셸 `export` 문으로 출력한다 → eval "$(python scripts/mysql_cluster.py start)"
    python scripts/mysql_cluster.py status ID  클러스터 상태(AdminAPI `cluster.status()`)
    python scripts/mysql_cluster.py stop ID    컨테이너·네트워크를 지운다(ID 는 start 가 출력하는 MYSQL_CLUSTER_ID)

운영과 비슷하게 맞춘 것: 서버 8.4.11 generic tarball(인프라의 이미지와 같은 방식), 노드 3개(GTID·ROW 바이너리 로그·`BEFORE_ON_PRIMARY_FAILOVER` 일관성), Router 는 클러스터 메타데이터로
읽기·쓰기 포트를 알아서 따라가고, 앱은 **Router 의 읽기·쓰기 포트로만** 접속한다. 계정도 나눈다: `root`(노드 안), `failover`(클러스터 관리), `router`(Router 가 부트스트랩이 만든 계정), `dev`(앱·시험, DML+DDL).
포트·비밀번호는 무작위이고 공유 컨테이너(db-standalone-*)는 건드리지 않는다. 이미지는 `docker/innodb-cluster/Dockerfile`(처음 한 번 빌드, 수 분).
"""
import json
import secrets
import socket
import sys
import time
import uuid
from functools import partial
from pathlib import Path

import docker_cli

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE = "ads-innodb-cluster:8.4"
CLUSTER_NAME = "ads"
NODES = 3


docker = partial(docker_cli.docker, timeout=300)  # 이 스크립트의 시간 제한(R5)


def ensure_image():
    if docker("image", "inspect", IMAGE, check=False).returncode != 0:
        print(f"이미지 {IMAGE} 를 빌드한다(처음 한 번, 수 분)…", file=sys.stderr)
        docker("build", "-t", IMAGE, str(BASE_DIR / "docker" / "innodb-cluster"), timeout=1800)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Cluster:
    def __init__(self):
        self.id = uuid.uuid4().hex[:8]
        self.network = f"ads-ic-{self.id}"
        self.nodes = [f"ads-ic-{self.id}-n{i}" for i in range(1, NODES + 1)]
        self.router = f"ads-ic-{self.id}-router"
        self.root_password, self.admin_password, self.dev_password = (secrets.token_urlsafe(18) for _ in range(3))
        self.port = free_port()  # 호스트에서 본 Router 읽기·쓰기 포트

    # ------------------------------------------------------------------ 구성
    def start(self):
        ensure_image()
        docker("network", "create", self.network)
        try:
            for i, name in enumerate(self.nodes, 1):
                docker("run", "-d", "--name", name, "--hostname", name, "--network", self.network, "-e", f"MYSQL_ROOT_PASSWORD={self.root_password}",
                       "-e", f"SERVER_ID={i}", "-e", f"NODE_NAME={name}", IMAGE, "node")
            for name in self.nodes:
                self.wait_ready(name)
            self.bootstrap()
            docker("run", "-d", "--name", self.router, "--hostname", self.router, "--network", self.network, "-p", f"127.0.0.1:{self.port}:6446",
                   "-e", f"BOOTSTRAP_URI=failover@{self.nodes[0]}:3306", "-e", f"BOOTSTRAP_PASSWORD={self.admin_password}", "-e", f"ROUTER_NAME={self.router}", IMAGE, "router")
            self.wait_router()
        except BaseException:
            self.stop()
            raise

    def wait_ready(self, name, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            probe = docker("exec", "-e", f"MYSQL_PWD={self.root_password}", name, "mysqladmin", "--socket=/var/run/mysqld/mysqld.sock", "ping", "-uroot", "--silent", check=False)
            if probe.returncode == 0:
                return
            time.sleep(1)
        raise SystemExit(f"노드 {name} 가 {timeout}초 안에 준비되지 않았다:\n" + docker("logs", "--tail", "20", name, check=False).stderr)

    def shell(self, script, node=None, timeout=300):
        """노드 안의 MySQL Shell(JS)로 AdminAPI 스크립트를 실행한다. 반환: 표준 출력."""
        node = node or self.live_node()
        # (mysqlsh 는 표준 입력으로 읽은 스크립트에서 죽는다 — 파일로 넣고 실행한다)
        docker("exec", "-i", node, "sh", "-c", "cat > /tmp/script.js", input=script)
        out = docker("exec", "-e", "LC_ALL=C.UTF-8", "-e", "LANG=C.UTF-8", node, "mysqlsh", "--js", "--no-wizard", "-f", "/tmp/script.js", check=False, timeout=timeout)
        if out.returncode != 0:
            raise RuntimeError(f"mysqlsh 실패 ({node}):\n{out.stdout[-1500:]}\n{out.stderr[-1500:]}")
        return out.stdout

    def bootstrap(self):
        n1, n2, n3 = self.nodes
        root, admin = self.root_password, self.admin_password
        grants = "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, TRIGGER, LOCK TABLES, CREATE TEMPORARY TABLES, CREATE VIEW, SHOW VIEW, EXECUTE, SHOW DATABASES"
        script = f"""
for (const host of {json.dumps([n1, n2, n3])}) {{
  dba.configureInstance('root:{root}@' + host + ':3306', {{clusterAdmin: 'failover', clusterAdminPassword: '{admin}', restart: false}});
}}
shell.connect('failover:{admin}@{n1}:3306');
var cluster = dba.createCluster('{CLUSTER_NAME}', {{gtidSetIsComplete: true, consistency: 'BEFORE_ON_PRIMARY_FAILOVER', expelTimeout: 5, autoRejoinTries: 3, exitStateAction: 'READ_ONLY'}});
cluster.addInstance('failover:{admin}@{n2}:3306', {{recoveryMethod: 'incremental'}});
cluster.addInstance('failover:{admin}@{n3}:3306', {{recoveryMethod: 'incremental'}});
shell.connect('root:{root}@{n1}:3306');  // 앱 계정은 root 로 만든다(failover 는 클러스터 관리 전용이라 CREATE USER 권한이 없다)
session.runSql("CREATE USER 'dev'@'%' IDENTIFIED BY '{self.dev_password}'");
session.runSql("GRANT {grants} ON *.* TO 'dev'@'%'");
session.runSql("CREATE DATABASE ads_server CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs");  // 개발용 데이터베이스(README: 정렬을 지정해 만든다)
shell.connect('failover:{admin}@{n1}:3306');
print(JSON.stringify(dba.getCluster('{CLUSTER_NAME}').status().defaultReplicaSet.status));
"""
        out = self.shell(script, node=n1, timeout=600)
        if "OK" not in out:
            raise RuntimeError("클러스터가 정상(OK)으로 구성되지 않았다:\n" + out[-800:])

    def wait_router(self, timeout=90):
        import MySQLdb

        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                conn = MySQLdb.connect(host="127.0.0.1", port=self.port, user="dev", passwd=self.dev_password, connect_timeout=3)
                cur = conn.cursor()
                cur.execute("SELECT @@report_host, @@read_only")
                row = cur.fetchone()
                conn.close()
                if row[1] == 0:
                    return
            except Exception as error:  # noqa: BLE001
                last = error
            time.sleep(1)
        raise SystemExit(f"Router 읽기·쓰기 포트가 {timeout}초 안에 쓸 수 있게 되지 않았다: {last}\n" + docker("logs", "--tail", "30", self.router, check=False).stderr)

    # ------------------------------------------------------------------ 상태·조작
    def running(self):
        out = docker("ps", "--filter", f"network={self.network}", "--format", "{{.Names}}", check=False).stdout.split()
        return [n for n in self.nodes if n in out]

    def live_node(self):
        alive = self.running()
        if not alive:
            raise RuntimeError("살아 있는 노드가 없다")
        return alive[0]

    def status(self):
        """AdminAPI 의 클러스터 상태(dict). 살아 있는 노드 하나를 통해 본다."""
        node = self.live_node()
        script = f"shell.connect('failover:{self.admin_password}@{node}:3306'); print(JSON.stringify(dba.getCluster('{CLUSTER_NAME}').status()));"
        out = self.shell(script, node=node)
        return json.loads(out[out.index("{"):])

    def primary(self):
        """현재 primary 노드의 컨테이너 이름(없으면 None)."""
        try:
            topology = self.status()["defaultReplicaSet"]["topology"]
        except Exception:  # noqa: BLE001 — 선출 중에는 상태를 못 읽을 수 있다
            return None
        for member in topology.values():
            if member.get("memberRole") == "PRIMARY" and member.get("status") == "ONLINE":
                return member["address"].split(":")[0]
        return None

    def wait_for_primary(self, different_from=None, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            primary = self.primary()
            if primary and primary != different_from:
                return primary
            time.sleep(1)
        raise RuntimeError(f"{timeout}초 안에 새 primary 가 서지 않았다 (이전 {different_from})")

    def wait_all_online(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                topology = self.status()["defaultReplicaSet"]["topology"]
                if len(topology) == NODES and all(m.get("status") == "ONLINE" for m in topology.values()):
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
        raise RuntimeError(f"{timeout}초 안에 모든 노드가 ONLINE 이 되지 않았다")

    def kill(self, node):
        docker("kill", node)

    def start_node(self, node):
        docker("start", node)
        self.wait_ready(node)  # 그룹 복제는 AdminAPI 가 영속화한 설정(start_on_boot)으로 스스로 다시 합류한다

    def restart_node(self, node):
        docker("restart", "-t", "20", node)
        self.wait_ready(node)

    def switchover(self, target):
        """계획된 primary 전환(`cluster.setPrimaryInstance`)."""
        node = self.live_node()
        self.shell(f"shell.connect('failover:{self.admin_password}@{node}:3306'); dba.getCluster('{CLUSTER_NAME}').setPrimaryInstance('failover:{self.admin_password}@{target}:3306');", node=node)

    def replica_report(self, database, tables, timeout=60):
        """모든 노드가 같은 데이터를 갖는지 본다: 실행한 GTID 집합과 표별 행 수. 복제가 따라잡을 때까지 기다린다. 반환: (같은가, 노드별 보고)."""
        def ask(node, sql):
            out = docker("exec", "-e", f"MYSQL_PWD={self.root_password}", node, "mysql", "--socket=/var/run/mysqld/mysqld.sock", "-uroot", "-N", "-B", "-e", sql, check=False)
            return out.stdout.strip() if out.returncode == 0 else f"ERR {out.stderr.strip()[:80]}"

        deadline, report = time.time() + timeout, {}
        while True:
            report = {}
            for node in self.running():
                counts = {t: ask(node, f"SELECT COUNT(*) FROM `{database}`.`{t}`") for t in tables}
                report[node] = {"gtid_executed": ask(node, "SELECT @@gtid_executed").replace("\n", ""), "counts": counts}
            reports = list(report.values())
            if reports and all(r == reports[0] for r in reports):
                return True, report
            if time.time() > deadline:
                return False, report
            time.sleep(1)

    def restart_router(self):
        docker("restart", "-t", "10", self.router)
        self.wait_router()

    def env(self):
        """앱·시험이 읽는 접속 값(Router 읽기·쓰기 포트, 앱 계정 dev)."""
        return {"DB_HOST": "127.0.0.1", "DB_PORT": str(self.port), "DB_USER": "dev", "DB_PASSWORD": self.dev_password}

    def stop(self):
        for name in [self.router, *self.nodes]:
            docker("rm", "-f", "-v", name, check=False)
        docker("network", "rm", self.network, check=False)

    remove = stop  # failure_test 의 DbContainer 와 같은 이름

    @classmethod
    def attach(cls, cluster_id, port=0):
        """이미 떠 있는 클러스터(ID 로 이름 규칙을 복원)를 다룬다 — stop·status 용. 비밀번호는 필요한 명령에서만 환경에서 읽는다."""
        self = cls.__new__(cls)
        self.id = cluster_id
        self.network = f"ads-ic-{cluster_id}"
        self.nodes = [f"ads-ic-{cluster_id}-n{i}" for i in range(1, NODES + 1)]
        self.router = f"ads-ic-{cluster_id}-router"
        self.port = port
        return self


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "start":
        cluster = Cluster()
        cluster.start()
        env = cluster.env()
        print(f"export MYSQL_CLUSTER_ID={cluster.id} DB_HOST={env['DB_HOST']} DB_PORT={env['DB_PORT']} DB_USER=dev DB_PASSWORD='{env['DB_PASSWORD']}'")
    elif command == "stop" and len(sys.argv) == 3:
        Cluster.attach(sys.argv[2]).stop()
    else:
        raise SystemExit(__doc__)
