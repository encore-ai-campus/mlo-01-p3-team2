#!/usr/bin/env python
"""로컬에서 백엔드와 프론트를 함께 띄운다(설계 §6.6 "6-15 분리", 팀 메타버스의 run-split.py 와 같은 방식). Ctrl+C 로 둘 다 끝난다.

    python scripts/run_split.py                       # 백엔드 127.0.0.1:8000, 프론트 127.0.0.1:8001 → 브라우저는 프론트 주소로
    python scripts/run_split.py --backend-port 8100 --frontend-port 8101

백엔드는 루프백에만 연다(운영에서는 백 서버의 내부망 주소 + 방화벽). 프론트는 백엔드의 `.env` 에서 관리 사이트 경로와 업로드 상한을 받아 같게 맞춘다.
시작 전에 백엔드 마이그레이션을 한다. 이미 쓰는 포트면 기존 서버를 끄지 않고 멈춘다.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "ads_frontend"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=8001)
    options = parser.parse_args()
    ports = (options.backend_port, options.frontend_port)
    if len(set(ports)) != 2:
        parser.error("두 포트는 달라야 한다")
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"포트 {port} 를 이미 쓰고 있다")
    backend_env = {**dotenv_values(BACKEND / ".env"), **os.environ}  # 실제 환경변수가 .env 보다 우선(백엔드와 같다)
    frontend_env = {**os.environ, "BACKEND_URL": f"http://127.0.0.1:{options.backend_port}", "FRONTEND_DEBUG": os.environ.get("FRONTEND_DEBUG", "1"),
                    "ADMIN_URL_PATH": backend_env.get("ADMIN_URL_PATH") or "dev-admin/"}
    if backend_env.get("ASSET_MAX_BYTES"):
        frontend_env["ASSET_MAX_BYTES"] = backend_env["ASSET_MAX_BYTES"]
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=BACKEND, check=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{options.backend_port}", "--noreload"], cwd=BACKEND))
        processes.append(subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{options.frontend_port}", "--noreload"],
                                          cwd=FRONTEND, env=frontend_env))
        print(f"광고 서버: http://127.0.0.1:{options.frontend_port}/ (백엔드 {options.backend_port} 는 프론트만 부른다)", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.2)
        return next((p.returncode for p in processes if p.returncode), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


if __name__ == "__main__":
    raise SystemExit(main())
