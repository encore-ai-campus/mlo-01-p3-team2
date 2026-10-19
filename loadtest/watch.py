"""개발 서버로 띄운 백엔드를 실시간으로 본다(사람이 접속해 볼 때). Ctrl+C 로 끝낸다.

사용(dev/ 에서): python loadtest/watch.py [--every 5] [--quota 5000]
- 운영 코어: 운영 game-server 코어 하나 대비 사용률(100 = 포화). 조절된 시간(throttled)이 크면 밀리고 있다.
- 백엔드 연결: 백엔드 포트(9003)에 붙은 연결 수. 대부분 접속한 사람의 소켓이다(프론트가 한 사람에 하나씩 중계한다).
- DB: 초당 질의·새 연결.
"""
import argparse
import time

from run import STATUS, compose, cpu_stat, db_status

BACKEND_PORT_HEX = ":232B"  # 9003


def connections():
    out = compose("exec", "-T", "backend", "sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null", capture_output=True).stdout
    return sum(1 for line in out.splitlines() if (parts := line.split()) and len(parts) > 3 and parts[1].endswith(BACKEND_PORT_HEX) and parts[3] == "01")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--every", type=float, default=5)
    parser.add_argument("--quota", type=int, default=5000, help="백엔드 cpu_quota/10000 (운영 코어 하나 = 5000)")
    args = parser.parse_args()
    before, at = (cpu_stat(), db_status()), time.monotonic()
    print("시각      운영 코어  조절됨  백엔드 연결  DB 질의/s  새 DB 연결/s")
    while True:
        time.sleep(args.every)
        now, after = time.monotonic(), (cpu_stat(), db_status())
        wall = (now - at) * 1e6
        used = after[0]["usage_usec"] - before[0]["usage_usec"]
        periods = after[0]["nr_periods"] - before[0]["nr_periods"]
        throttled = 100 * (after[0]["nr_throttled"] - before[0]["nr_throttled"]) / periods if periods else 0
        per_s = {k: (after[1][k] - before[1][k]) * 1e6 / wall for k in STATUS}
        print(f"{time.strftime('%H:%M:%S')}  {100 * used / (wall * args.quota / 10000):7.1f}%  {throttled:5.1f}%  {connections():10d}  "
              f"{per_s['Questions']:9.1f}  {per_s['Connections']:11.1f}", flush=True)
        before, at = after, now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
