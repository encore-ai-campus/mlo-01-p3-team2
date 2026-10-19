"""운영 실시간 점검(읽기만): game-server·front-a 를 주기마다 5초 재어 한 줄로 낸다 — 프로세스별 접속·CPU, Redis, nginx, 부하.

CPU 는 vCPU 하나 대비 %(소켓 프로세스는 하나가 한 vCPU 를 넘지 못한다). 사용(dev/ 에서): python loadtest/prod_watch.py [간격초]
"""
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

SAMPLER = r'''
import os, re, subprocess, time
tick = os.sysconf("SC_CLK_TCK")
def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout
def ticks(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            rest = f.read().rsplit(")", 1)[1].split()
        return int(rest[11]) + int(rest[12])
    except OSError:
        return 0
def pids(name):
    return [int(p) for p in sh("pgrep", "-x", name).split()]
def main_pid(unit):
    value = sh("systemctl", "show", "-p", "MainPID", "--value", unit).strip()
    return int(value) if value.isdigit() and value != "0" else None
def established(port):
    return len(sh("ss", "-Htn", "state", "established", f"( sport = :{port} )").splitlines())
groups = {}
if ROLE == "game":
    for port in (9101, 9102, 9103, 9104):
        groups[str(port)] = [main_pid(f"playdata-backend@{port}")]
    groups["jobs"] = [main_pid("playdata-campus-jobs")]
    groups["redis"] = pids("redis-server")
else:
    groups["front"] = [main_pid("playdata-frontend")]
groups["nginx"] = pids("nginx")
before = {k: sum(ticks(p) for p in v if p) for k, v in groups.items()}
t0 = time.monotonic(); time.sleep(5); dt = time.monotonic() - t0
cpu = {k: round(100 * (sum(ticks(p) for p in v if p) - before[k]) / tick / dt) for k, v in groups.items()}
load = open("/proc/loadavg").read().split()[0]
mem = next(int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemAvailable"))
if ROLE == "game":
    ws = "/".join(str(established(p)) for p in (9101, 9102, 9103, 9104))
    info = sh("redis-cli", "info")
    get = lambda key: (re.search(rf"^{key}:(\S+)", info, re.M) or [None, "?"])[1]
    sockets = "/".join(f"{cpu[str(p)]}" for p in (9101, 9102, 9103, 9104))
    print(f"game 접속 {ws} CPU {sockets}% 작업 {cpu['jobs']}% nginx {cpu['nginx']}% redis {cpu['redis']}% "
          f"{get('instantaneous_ops_per_sec')}ops/s {get('used_memory_human')} | 부하 {load} 여유 {mem}MB")
else:
    print(f"front 443접속 {established(443)} 프론트 {cpu['front']}% nginx {cpu['nginx']}% | 부하 {load} 여유 {mem}MB")
'''


def sample(host, role):
    code = f"ROLE = {role!r}\n" + SAMPLER
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, "python3", "-"], input=code,
                             capture_output=True, text=True, timeout=40)
        return (out.stdout.strip() or out.stderr.strip()[-120:]).replace("\n", " ")
    except subprocess.TimeoutExpired:
        return f"{host} 응답 없음"


if __name__ == "__main__":
    every = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    with ThreadPoolExecutor(2) as pool:
        while True:
            started = time.monotonic()
            game, front = pool.map(lambda args: sample(*args), [("game-server", "game"), ("front-a", "front")])
            print(time.strftime("%H:%M:%S"), game, "||", front, flush=True)
            time.sleep(max(0, every - (time.monotonic() - started)))
