"""부하 시험 한 번: 백엔드를 새로 띄우고(메모리 상태 초기화) N명 시드 → 생성기 실행 → 측정 구간의 서버 CPU·DB·로그를 함께 기록한다.

사용(호스트, dev/ 에서): python loadtest/run.py --users 100 --moving 0.2 --label baseline --out <폴더>
여러 프로세스(계획 M5): --backends 4 → daphne 4개(컨테이너마다 운영 코어 하나) + 작업 하나 + nginx(세션 고정) + Redis
CPU 는 운영 코어 하나 기준이다(BACKEND_CPU_QUOTA 5000/10000 = 운영 t3.2xlarge 코어 하나의 속도, corebench.py 로 맞춤).
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(HERE / "compose.yaml")]
STATUS = ("Questions", "Com_select", "Com_insert", "Com_update", "Com_delete", "Connections")
GAUGES = ("Threads_connected", "Max_used_connections")


def compose(*args, env=None, check=True, **kwargs):
    return subprocess.run([*COMPOSE, *args], check=check, text=True, env=env, **kwargs)


def cpu_stat(service="backend", index=1):
    out = compose("exec", "-T", "--index", str(index), service, "cat", "/sys/fs/cgroup/cpu.stat", capture_output=True).stdout
    return {k: int(v) for k, v in (line.split() for line in out.splitlines())}


def db_status():
    names = ",".join(f"'{n}'" for n in STATUS + GAUGES)
    out = compose("exec", "-T", "mysql", "mysql", "-uroot", "-pload", "-N", "-e",
                  f"SHOW GLOBAL STATUS WHERE Variable_name IN ({names})", capture_output=True).stdout
    return {k: int(v) for k, v in (line.split("\t") for line in out.splitlines())}


def redis_commands():
    out = compose("exec", "-T", "redis", "redis-cli", "INFO", "stats", capture_output=True).stdout
    return int(next(line.split(":")[1] for line in out.splitlines() if line.startswith("total_commands_processed:")))


def connections(index):
    """그 백엔드 컨테이너의 9003 에 붙은 연결 수(≈ 그 프로세스가 맡은 사람)."""
    out = compose("exec", "-T", "--index", str(index), "backend", "sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null", capture_output=True).stdout
    return sum(1 for line in out.splitlines() if (parts := line.split()) and len(parts) > 3 and parts[1].endswith(":232B") and parts[3] == "01")


def snapshot(redis=False, backends=0, frontend=False):
    extra = {}
    if redis:
        extra.update(redis_cpu=cpu_stat("redis"), redis_commands=redis_commands())
    if frontend:
        extra.update(frontend_cpu=cpu_stat("frontend"))
    if backends:
        extra.update(backend_cpu=[cpu_stat("backend", i) for i in range(1, backends + 1)], jobs_cpu=cpu_stat("jobs"), nginx_cpu=cpu_stat("nginx"))
    return {"t": time.monotonic(), "cpu": cpu_stat(), "db": db_status(), **extra}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--moving", type=float, default=0.2)
    parser.add_argument("--client", choices=("current", "new"), default="new", help="new = 지금 브라우저(1c: 키가 있을 때만 input). current = 1c 이전")
    parser.add_argument("--polls", type=float, default=15)
    parser.add_argument("--ramp", type=float, default=30)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--measure", type=float, default=60)
    parser.add_argument("--quota", type=int, default=5000, help="cpu_quota/10000 (운영 코어 하나 = 5000)")
    parser.add_argument("--delay-us", type=int, default=250)
    parser.add_argument("--settings", default="config.settings", help="실험용 설정(loadtest/settings_*.py)")
    parser.add_argument("--redis", action="store_true", help="Redis 채널 계층(계획 M2). 없으면 한 프로세스 메모리 계층")
    parser.add_argument("--backends", type=int, default=0, help="여러 프로세스(계획 M5): daphne 개수. 0 이면 지금처럼 run-campus.py 하나")
    parser.add_argument("--via-frontend", action="store_true", help="프론트 중계(운영 코어 하나)를 거쳐 붙는다(계획 M6)")
    args = parser.parse_args()
    args.redis = args.redis or args.backends > 0
    env = {**os.environ, "BACKEND_CPU_QUOTA": str(args.quota), "NET_DELAY_US": str(args.delay_us), "SETTINGS": args.settings,
           "CAMPUS_REDIS_URL": "redis://redis:6379/0" if args.redis else ""}
    hosts = "backend,localhost" + (",nginx" if args.backends else "") + (",frontend" if args.via_frontend else "")
    env.update(BACKEND_HOSTS=hosts)
    if args.backends:
        env.update(BACKEND_RUN="daphne -b 0.0.0.0 -p 9003 config.asgi:application", CAMPUS_HOST="nginx", CAMPUS_PORT="8000")
        # nginx 는 시작할 때 backend 이름을 모든 복제 주소로 푼다: 백엔드를 늘린 뒤 함께 새로 띄운다
        compose("--profile", "multi", "up", "-d", "--wait", "--force-recreate", "--scale", f"backend={args.backends}", "backend", "jobs", "nginx",
                env=env, capture_output=True)
    else:
        compose("--profile", "multi", "stop", "jobs", "nginx", env=env, capture_output=True)
        compose("up", "-d", "--wait", "--force-recreate", "--scale", "backend=1", "backend", env=env, capture_output=True)
    if args.via_frontend:
        # 브라우저 → 프론트 중계(Python 하나, 운영 코어 하나) → 백엔드(nginx 또는 하나). 운영 front-a 와 같다
        env.update(FRONTEND_CPU_QUOTA=str(args.quota), FRONTEND_HOSTS="frontend,localhost",
                   FRONTEND_BACKEND_URL="http://nginx:8000" if args.backends else "http://backend:9003")
        compose("--profile", "dev", "up", "-d", "--force-recreate", "--no-deps", "frontend", env=env, capture_output=True)
        for _ in range(60):  # 중계에는 healthcheck 가 없다: 응답할 때까지 기다린다
            if compose("exec", "-T", "frontend", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8004/health/')",
                       env=env, capture_output=True, check=False).returncode == 0:
                break
            time.sleep(1)
        env.update(CAMPUS_HOST="frontend", CAMPUS_PORT="8004")
    else:
        compose("--profile", "dev", "stop", "frontend", env=env, capture_output=True)
    compose("exec", "-T", "mysql", "mysql", "-uroot", "-pload", "-e", "FLUSH STATUS", capture_output=True)  # Max_used_connections 를 이번 실행부터 센다
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    print(compose("exec", "-T", "backend", "python", "/load/seed.py", str(args.users), capture_output=True).stdout.strip())

    generator = subprocess.Popen(
        [*COMPOSE, "run", "--rm", "--no-deps", "-T", "load", "python", "campus_load.py", "--users", str(args.users), "--moving", str(args.moving),
         "--client", args.client, "--polls", str(args.polls), "--ramp", str(args.ramp), "--warmup", str(args.warmup), "--measure", str(args.measure)],
        stdout=subprocess.PIPE, text=True, env=env,
    )
    marks, summary = {}, None
    for line in generator.stdout:
        line = line.strip()
        if line in ("MEASURE_START", "MEASURE_END"):
            marks[line] = snapshot(args.redis, args.backends, args.via_frontend)
            if line == "MEASURE_START" and args.backends:  # 끝에서는 생성기가 이미 연결을 닫고 있다
                marks["connections"] = [connections(i) for i in range(1, args.backends + 1)]
        elif line.startswith("{"):
            summary = json.loads(line)
    generator.wait()
    start, end = marks["MEASURE_START"], marks["MEASURE_END"]
    wall_us = (end["t"] - start["t"]) * 1e6
    used_us = end["cpu"]["usage_usec"] - start["cpu"]["usage_usec"]
    periods = end["cpu"]["nr_periods"] - start["cpu"]["nr_periods"]
    server = {
        "prod_core_pct": round(100 * used_us / (wall_us * args.quota / 10000), 1),  # 운영 코어 하나 대비 사용률(100 = 포화)
        "throttled_period_pct": round(100 * (end["cpu"]["nr_throttled"] - start["cpu"]["nr_throttled"]) / periods, 1) if periods else None,
        "db_per_s": {k: round((end["db"][k] - start["db"][k]) * 1e6 / wall_us, 1) for k in STATUS},
        "db_threads_connected_end": end["db"]["Threads_connected"], "db_max_used_connections": end["db"]["Max_used_connections"],
    }
    if args.redis:  # 맥 코어 하나 ≈ 운영 코어 둘(corebench.py): Redis 는 CPU 제한이 없어 운영 코어로 바꿔 적는다
        server["redis_prod_core_pct"] = round(100 * (end["redis_cpu"]["usage_usec"] - start["redis_cpu"]["usage_usec"]) / (wall_us * 5000 / 10000), 1)
        server["redis_commands_per_s"] = round((end["redis_commands"] - start["redis_commands"]) * 1e6 / wall_us, 1)
    if args.backends:  # 프로세스마다 운영 코어 하나(cpu_quota). 가장 바쁜 프로세스가 지연을 정한다
        per = [round(100 * (e["usage_usec"] - s["usage_usec"]) / (wall_us * args.quota / 10000), 1) for s, e in zip(start["backend_cpu"], end["backend_cpu"])]
        mac = lambda key: round(100 * (end[key]["usage_usec"] - start[key]["usage_usec"]) / (wall_us * 5000 / 10000), 1)  # noqa: E731 — 제한 없는 컨테이너: 운영 코어로 바꿔 적는다
        server.update(backends_prod_core_pct=per, busiest_prod_core_pct=max(per), backends_total_prod_cores=round(sum(per) / 100, 2),
                      jobs_prod_core_pct=mac("jobs_cpu"), nginx_prod_core_pct=mac("nginx_cpu"), connections_per_backend=marks["connections"])
    if args.via_frontend:
        server["frontend_prod_core_pct"] = round(100 * (end["frontend_cpu"]["usage_usec"] - start["frontend_cpu"]["usage_usec"]) / (wall_us * args.quota / 10000), 1)
        periods_f = end["frontend_cpu"]["nr_periods"] - start["frontend_cpu"]["nr_periods"]
        server["frontend_throttled_period_pct"] = round(100 * (end["frontend_cpu"]["nr_throttled"] - start["frontend_cpu"]["nr_throttled"]) / periods_f, 1) if periods_f else None
    logs = compose("logs", "--no-color", "--since", since, "backend", capture_output=True).stdout
    server["log"] = {name: logs.count(text) for name, text in
                     (("traceback", "Traceback"), ("channel_full", "ChannelFull"), ("db_error", "OperationalError"))}
    result = {"label": args.label, "quota": args.quota, "delay_us": args.delay_us, "settings": args.settings, "redis": args.redis, "backends": args.backends,
              "via_frontend": args.via_frontend,
              "server": server, "client": summary}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
