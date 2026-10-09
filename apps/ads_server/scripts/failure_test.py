#!/usr/bin/env python
"""DB-1d 장애 시험(로컬): 지속 유입 중에 DB 를 재시작·강제 종료하거나 처리 프로세스를 강제 종료하고, **약속이 지켜지는지** 확인한다.

    python scripts/failure_test.py                       # 세 시나리오 모두
    python scripts/failure_test.py restart crash         # 골라서
    python scripts/failure_test.py --json out.json

환경: **임시 MySQL 8.4 컨테이너**를 따로 띄운다(이미지는 `intake/db-standalone` 이 만든 `db-standalone/mysql:8.4-ubuntu24.04`, 포트·비밀번호는 무작위).
공유 시험 DB(`ads_server`)나 다른 사람이 쓰는 컨테이너는 건드리지 않는다. 끝나면 컨테이너를 지운다. Docker 가 없거나 이미지가 없으면 **건너뛰지 않고 실패**한다.
check.sh 에는 넣지 않는다(Docker 가 필요하고 수 분 걸린다).

시나리오(모두 지속 유입 중 — 결정을 받고 노출을 보고하는 클라이언트 여러 개가 계약의 재시도 규칙대로 움직인다):
  restart          `docker restart`(정상 종료 → 기동): 계획된 재시작·전환에 가까운 끊김
  crash            `docker kill`(SIGKILL) → 기동: 강제 종료. InnoDB 충돌 복구. **수신 확인(2xx)한 것은 전부 살아 있어야 한다**(커밋마다 디스크 동기화 설정 하에서)
  processor-kill   처리 프로세스 하나를 SIGKILL 하고 새로 띄운다(DB 는 그대로): 처리 도중 죽어도 이중 과금·유실이 없다

확인하는 것(종료 코드 0 = 모두 충족):
  1. 끊김 동안 API 는 503(또는 연결 실패)으로 답하고 **500 은 없다**. 시험이 공회전이 아니다(끊김을 실제로 겪은 요청이 있다).
  2. 클라이언트의 재시도가 모두 끝내 수신 확인된다(복구 뒤 정상).
  3. 수신 확인한 결정·반응은 전부 저장돼 있다(유실 0), 이중 과금 0, 잔액 = 원장 합계, 일 소진액 = 원장 합계(`load_test.verify_invariants`).
  4. 상시 처리 프로세스는 DB 가 끊겼다 돌아와도 죽지 않고 이어서 처리한다.

한계: 단일 노드다. ReplicaSet 의 **강제 failover**(비동기 복제 지연분 유실)와 Router 경유 전환은 인프라 서버에서 확인할 일이다(계획 7.3.4 #6).
"""
import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

IMAGE = "db-standalone/mysql:8.4-ubuntu24.04"
SCENARIOS = ("restart", "crash", "processor-kill")


def docker(*args, check=True, timeout=180):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


class DbContainer:
    """임시 MySQL 컨테이너. 비밀번호는 환경변수로만 넘기고 출력하지 않는다."""

    def __init__(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.name = f"ads-failure-{uuid.uuid4().hex[:10]}"
        self.password = secrets.token_urlsafe(24)

    def start(self):
        docker("run", "-d", "--name", self.name, "-p", f"127.0.0.1:{self.port}:3306", "-e", f"MYSQL_ROOT_PASSWORD={self.password}", IMAGE)
        self.wait_ready()

    def wait_ready(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            probe = subprocess.run(
                ["docker", "exec", "-e", f"MYSQL_PWD={self.password}", self.name, "mysqladmin", "ping", "--protocol=tcp", "-h127.0.0.1", "-uroot", "--silent"],
                capture_output=True, text=True,
            )
            if probe.returncode == 0:
                return
            time.sleep(1)
        raise SystemExit(f"컨테이너 {self.name} 의 MySQL 이 {timeout}초 안에 준비되지 않았다")

    def restart(self):
        docker("restart", "-t", "20", self.name)
        self.wait_ready()

    def kill_and_start(self):
        docker("kill", self.name)
        time.sleep(0.5)
        docker("start", self.name)
        self.wait_ready()

    def remove(self):
        docker("rm", "-f", self.name, check=False)


def start_processor(env, tmp, name):
    log = open(tmp / f"{name}.log", "w")
    proc = subprocess.Popen([sys.executable, "manage.py", "process_reactions", "--batch", "50", "--interval", "0.3"], cwd=BASE_DIR, env=env, stdout=log, stderr=log)
    proc.log_handle = log
    deadline = time.time() + 60
    while time.time() < deadline and "started" not in (tmp / f"{name}.log").read_text():
        time.sleep(0.1)
    return proc


def run_scenario(name, db, log):
    import load_test
    import mysql_admin

    tmp = Path(tempfile.mkdtemp(prefix="ads-failure-"))
    database = mysql_admin.create_database("ads_failure")
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings.dev", DB_NAME=database, MEDIA_ROOT=str(tmp / "media"))
    os.environ.pop("DJANGO_DEBUG", None)
    import django

    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.conf import settings
    from django.db import connections

    # 시나리오마다 새 데이터베이스다. 이 프로세스의 Django 설정은 첫 시나리오 때 굳어 있으므로 이름을 직접 바꾼다(처리 프로세스는 새 환경변수를 읽는다).
    connections.close_all()
    settings.DATABASES["default"]["NAME"] = database
    connections["default"].settings_dict["NAME"] = database
    result = {"scenario": name, "checks": []}

    def check(label, ok, detail=""):
        result["checks"].append({"check": label, "ok": bool(ok), "detail": detail})
        log(f"  {'OK  ' if ok else 'FAIL'} {label} {detail}")

    processors, server = [], None
    try:
        call_command("migrate", verbosity=0)
        ctx = load_test.seed()
        server = load_test.ThreadedServer(("127.0.0.1", 0), load_test.QuietHandler)
        server.set_app(get_wsgi_application())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        harness = load_test.Harness(server.server_address[1], ctx, 8, tmp, log, rest_scale=0.1)
        harness.quiescent = False
        env = dict(os.environ)
        processors = [start_processor(env, tmp, "p1"), start_processor(env, tmp, "p2")]

        stop, outcomes, lock, timeline = threading.Event(), [], threading.Lock(), {}

        def client():
            while not stop.is_set():
                decision = harness.post_decision()
                with lock:
                    outcomes.append(decision)
                if not decision.acked:
                    continue
                decision_id = decision.body["decision_id"]
                harness.acked_decisions.add(decision_id)
                reaction = harness.put_reaction(decision_id, "IMPRESSION")
                with lock:
                    outcomes.append(reaction)

        clients = [threading.Thread(target=client, daemon=True) for _ in range(8)]
        [t.start() for t in clients]
        time.sleep(4)
        timeline["injected_at"] = time.time()
        if name == "restart":
            db.restart()
        elif name == "crash":
            db.kill_and_start()
        else:
            processors[0].send_signal(signal.SIGKILL)
            processors[0].wait(timeout=10)
            processors[0] = start_processor(env, tmp, "p1b")
        timeline["recovered_at"] = time.time()
        time.sleep(8)
        stop.set()
        [t.join(timeout=120) for t in clients]

        statuses = [s for o in outcomes for s in o.attempts]
        unavailable = sum(1 for s in statuses if s in (0, 503))
        server_errors = sorted({s for s in statuses if s >= 500 and s != 503})
        unacked = sum(1 for o in outcomes if not o.acked)
        log(f"  요청 {len(outcomes)}건, 시도 {len(statuses)}회: 끊김(503·연결 실패) {unavailable}회, 최종 수신 확인 못 한 것 {unacked}건, "
            f"주입 {timeline['recovered_at'] - timeline['injected_at']:.1f}초")
        if name != "processor-kill":
            check("끊김을 실제로 겪은 요청이 있다(시험이 공회전이 아니다)", unavailable > 0, f"{unavailable}회")
        check("끊김 동안 500 이 없다(503·연결 실패만)", not server_errors, f"500대: {server_errors}")
        check("모든 요청이 끝내 수신 확인됐다(재시도로 복구)", unacked == 0, f"{unacked}건 실패")
        alive = [p.poll() is None for p in processors]
        check("상시 처리 프로세스가 죽지 않았다", all(alive), f"살아 있음 {alive}")

        for proc in processors:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=30)
            proc.log_handle.close()
        connections.close_all()  # 주입 전에 열었던 연결은 끊겼을 수 있다
        harness.drain_until(lambda: not _received_left(), "남은 반응 처리", limit_seconds=120)
        problems = load_test.verify_invariants(harness.acked_decisions, harness.acked_reactions, expect_drained=True)
        check("불변식: 유실 0·이중 과금 0·잔액=원장·소진액=원장·남은 대기열 없음", not problems, "; ".join(problems[:3]))
        result.update(requests=len(outcomes), attempts=len(statuses), unavailable=unavailable, acked_decisions=len(harness.acked_decisions), acked_reactions=len(harness.acked_reactions))
    finally:
        for proc in processors:
            if proc.poll() is None:
                proc.kill()
        if server is not None:
            server.shutdown()
            server.server_close()
        connections.close_all()
        try:
            mysql_admin.drop_database(database)
        except BaseException as error:  # noqa: BLE001
            print(f"정리 실패(임시 DB): {error!r}", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
    result["ok"] = all(c["ok"] for c in result["checks"])
    return result


def _received_left():
    from records.models import Reaction

    return Reaction.objects.filter(status="RECEIVED").exists()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", help=f"기본은 모두: {', '.join(SCENARIOS)}")
    parser.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    args = parser.parse_args(argv)
    chosen = args.scenarios or list(SCENARIOS)
    unknown = [name for name in chosen if name not in SCENARIOS]
    if unknown:
        raise SystemExit(f"알 수 없는 시나리오 {unknown}. 가능한 것: {', '.join(SCENARIOS)}")
    if shutil.which("docker") is None:
        raise SystemExit("docker 가 없다. 이 시험은 임시 MySQL 컨테이너가 필요하다.")
    if docker("image", "inspect", IMAGE, check=False).returncode != 0:
        raise SystemExit(f"이미지 {IMAGE} 가 없다. intake/db-standalone 에서 `docker compose build mysql` 로 만든다.")

    import mysql_admin  # noqa: F401 — 경로 설정

    db = DbContainer()
    results = []
    try:
        print(f"임시 MySQL 컨테이너 {db.name} (포트 {db.port}) 기동…")
        db.start()
        os.environ.update(DB_HOST="127.0.0.1", DB_PORT=str(db.port), DB_USER="root", DB_PASSWORD=db.password)
        for name in chosen:
            print(f"\n== 시나리오: {name}")
            results.append(run_scenario(name, db, print))
    finally:
        db.remove()
    ok = all(r["ok"] for r in results)
    print("\n결과: " + ("모든 시나리오 통과" if ok else "실패 있음 — " + ", ".join(r["scenario"] for r in results if not r["ok"])))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
