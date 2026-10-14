#!/usr/bin/env python
"""임시 MongoDB 8.0 **단일 노드 레플리카셋** 컨테이너(DB-2 시험용). 인증(keyfile)을 켜서 운영과 같은 연결 방식을 쓴다.

    python tests/tools/mongo_temp_rs.py start      컨테이너를 띄우고 접속 값을 셸 `export` 문으로 출력한다 → eval "$(python tests/tools/mongo_temp_rs.py start)"
    python tests/tools/mongo_temp_rs.py stop NAME  지운다(이름은 start 가 출력하는 MONGO_TEMP_CONTAINER)

이미지는 `intake/db-standalone` 이 만든 `db-standalone/mongodb:8.0-ubuntu24.04`(Standalone·인증 켜짐)이고, 여기서는 진입점만 바꿔 `--replSet` 으로 띄운다.
포트·비밀번호는 무작위, 공유 컨테이너는 건드리지 않는다. 구성원 주소를 `127.0.0.1:<포트>` 로 정해 호스트에서 레플리카셋으로 접속할 수 있다.
"""
import secrets
import sys
import time
import uuid
from functools import partial

import docker_cli

IMAGE = "db-standalone/mongodb:8.0-ubuntu24.04"
REPLICA_SET = "rs0"


docker = partial(docker_cli.docker, timeout=120)  # 이 스크립트의 시간 제한(R5)


def start():
    if docker("image", "inspect", IMAGE, check=False).returncode != 0:
        raise SystemExit(f"이미지 {IMAGE} 가 없다. intake/db-standalone 에서 `docker compose build mongodb` 로 만든다.")
    port = docker_cli.free_port()
    name, password = f"ads-mongo-rs-{uuid.uuid4().hex[:10]}", secrets.token_urlsafe(24)
    # 컨테이너 안 포트도 같은 값으로 맞춘다 — 레플리카셋 구성원 주소가 호스트에서도 그대로 닿아야 한다.
    script = (f"rm -f /tmp/keyfile && openssl rand -base64 48 > /tmp/keyfile && chmod 400 /tmp/keyfile && "  # 재시작 때 읽기 전용 키 파일 위에 다시 쓰지 못해 죽지 않게 먼저 지운다
              f"exec mongod --dbpath /data/db --bind_ip_all --port {port} --replSet {REPLICA_SET} --keyFile /tmp/keyfile")
    docker("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{port}", "--entrypoint", "sh", IMAGE, "-c", script)
    try:
        mongosh = ["exec", name, "mongosh", "--quiet", "--port", str(port)]
        deadline = time.time() + 60  # 횟수가 아니라 시간으로(R25 — 횟수면 시도마다 docker 시간 제한까지 걸려 한없이 길어질 수 있었다)
        while docker(*mongosh, "--eval", "db.hello().ok", check=False).returncode != 0:
            if time.time() > deadline:
                raise SystemExit("mongod 가 60초 안에 기동하지 않았다")
            time.sleep(1)
        docker(*mongosh, "--eval", f'rs.initiate({{_id: "{REPLICA_SET}", members: [{{_id: 0, host: "127.0.0.1:{port}"}}]}})')
        wait_primary(name, port)
        docker(*mongosh, "admin", "--eval",
               'db.createUser({user: "root", pwd: "%s", roles: ["root"]})' % password)  # keyfile 인증 하의 localhost 예외로 첫 계정을 만든다
    except BaseException:
        docker("rm", "-f", name, check=False)
        raise
    return name, port, password


def wait_primary(name, port, timeout=120):
    """레플리카셋 primary 가 설 때까지 기다린다 — 처음 띄울 때와 재시작 뒤가 같은 제한을 쓴다(6-13g)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = docker("exec", name, "mongosh", "--quiet", "--port", str(port), "--eval", "db.hello().isWritablePrimary", check=False)
        if probe.stdout.strip() == "true":
            return
        time.sleep(1)
    raise SystemExit(f"{name} 의 primary 가 {timeout}초 안에 서지 않았다")


def restart(name, port):
    """컨테이너를 재시작하고 레플리카셋 primary 가 다시 설 때까지 기다린다(장애 시험의 '계획된 재시작')."""
    docker("restart", "-t", "20", name)
    wait_primary(name, port)


def stop(name):
    docker("rm", "-f", name, check=False)


if __name__ == "__main__":
    if sys.argv[1:2] == ["start"]:
        n, p, pw = start()
        print(f"export MONGO_TEMP_CONTAINER={n} MONGO_HOSTS=127.0.0.1:{p} MONGO_USER=root MONGO_PASSWORD='{pw}' MONGO_AUTH_SOURCE=admin MONGO_REPLICA_SET={REPLICA_SET}")
    elif sys.argv[1:2] == ["stop"] and len(sys.argv) == 3:
        stop(sys.argv[2])
    else:
        raise SystemExit(__doc__)
