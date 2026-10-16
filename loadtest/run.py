"""부하 시험 한 번: 백엔드를 새로 띄우고(메모리 상태 초기화) N명 시드 → 생성기 실행 → 측정 구간의 서버 CPU·DB·로그를 함께 기록한다.

사용(호스트, dev/ 에서): python loadtest/run.py --users 100 --moving 0.2 --client current --label baseline --out <폴더>
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


def compose(*args, env=None, **kwargs):
    return subprocess.run([*COMPOSE, *args], check=True, text=True, env=env, **kwargs)


def cpu_stat():
    out = compose("exec", "-T", "backend", "cat", "/sys/fs/cgroup/cpu.stat", capture_output=True).stdout
    return {k: int(v) for k, v in (line.split() for line in out.splitlines())}


def db_status():
    names = ",".join(f"'{n}'" for n in STATUS + GAUGES)
    out = compose("exec", "-T", "mysql", "mysql", "-uroot", "-pload", "-N", "-e",
                  f"SHOW GLOBAL STATUS WHERE Variable_name IN ({names})", capture_output=True).stdout
    return {k: int(v) for k, v in (line.split("\t") for line in out.splitlines())}


def snapshot():
    return {"t": time.monotonic(), "cpu": cpu_stat(), "db": db_status()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--moving", type=float, default=0.2)
    parser.add_argument("--client", choices=("current", "new"), default="current")
    parser.add_argument("--polls", type=float, default=15)
    parser.add_argument("--ramp", type=float, default=30)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--measure", type=float, default=60)
    parser.add_argument("--quota", type=int, default=5000, help="cpu_quota/10000 (운영 코어 하나 = 5000)")
    parser.add_argument("--delay-us", type=int, default=250)
    parser.add_argument("--settings", default="config.settings", help="실험용 설정(loadtest/settings_*.py)")
    args = parser.parse_args()
    env = {**os.environ, "BACKEND_CPU_QUOTA": str(args.quota), "NET_DELAY_US": str(args.delay_us), "SETTINGS": args.settings}

    compose("up", "-d", "--wait", "--force-recreate", "backend", env=env, capture_output=True)
    compose("exec", "-T", "mysql", "mysql", "-uroot", "-pload", "-e", "FLUSH STATUS", capture_output=True)  # Max_used_connections 를 이번 실행부터 센다
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    print(compose("exec", "-T", "backend", "python", "/load/seed.py", str(args.users), capture_output=True).stdout.strip())

    generator = subprocess.Popen(
        [*COMPOSE, "run", "--rm", "-T", "load", "python", "campus_load.py", "--users", str(args.users), "--moving", str(args.moving),
         "--client", args.client, "--polls", str(args.polls), "--ramp", str(args.ramp), "--warmup", str(args.warmup), "--measure", str(args.measure)],
        stdout=subprocess.PIPE, text=True, env=env,
    )
    marks, summary = {}, None
    for line in generator.stdout:
        line = line.strip()
        if line in ("MEASURE_START", "MEASURE_END"):
            marks[line] = snapshot()
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
    logs = compose("logs", "--no-color", "--since", since, "backend", capture_output=True).stdout
    server["log"] = {name: logs.count(text) for name, text in
                     (("traceback", "Traceback"), ("channel_full", "ChannelFull"), ("db_error", "OperationalError"))}
    result = {"label": args.label, "quota": args.quota, "delay_us": args.delay_us, "settings": args.settings, "server": server, "client": summary}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
