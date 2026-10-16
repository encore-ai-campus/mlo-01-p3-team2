"""Run frontend and backend together in one terminal; Ctrl+C stops both."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-port", type=int, default=8004)
    parser.add_argument("--backend-port", type=int, default=9003)
    parser.add_argument("--bind", default="0.0.0.0")
    options = parser.parse_args()
    ports = (options.frontend_port, options.backend_port)
    if len(set(ports)) != 2 or any(not 1 <= port <= 65535 for port in ports):
        parser.error("Choose two different ports between 1 and 65535")
    for port in ports:
        with socket.socket() as listener:
            listener.bind(("0.0.0.0", port))
    root = Path(__file__).resolve().parent
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
    env = os.environ.copy()
    if (root / "db.sqlite3").is_file():
        env.setdefault("CAMPUS_DATA_DIR", str(root))
    env["BACKEND_URL"] = f"http://127.0.0.1:{options.backend_port}"
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"],
                   cwd=root / "backend", env=env, check=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, "run-campus.py", "--port",
            str(options.backend_port), "--bind", "127.0.0.1", "--noreload"],
            cwd=root / "backend", env=env))
        processes.append(subprocess.Popen([sys.executable, "manage.py", "runserver",
            f"{options.bind}:{options.frontend_port}", "--noreload"],
            cwd=root / "frontend", env=env))
        print(f"Campus: http://127.0.0.1:{options.frontend_port}/", flush=True)
        print("Ctrl+C stops both services.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.2)
        return next((process.returncode for process in processes if process.returncode), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
