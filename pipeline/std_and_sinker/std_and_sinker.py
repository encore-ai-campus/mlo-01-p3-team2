"""Run from repository root: python pipeline/std_and_sinker/std_and_sinker.py.

Connection settings come from environment variables or a local --env-file.
"""
import argparse
import json
import logging

from sinker.config import Settings, SRC
from sinker.worker import run_worker


def main():
    parser = argparse.ArgumentParser(description="Raw -> Std + MongoDB sink")
    parser.add_argument("--env-file", default=str(SRC / ".env"))
    parser.add_argument("--max-messages", type=int)
    parser.add_argument("--idle-timeout", type=float)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.max_messages is not None and args.max_messages < 1:
        parser.error("--max-messages must be positive")
    try:
        report = run_worker(
            Settings.from_env(args.env_file), args.max_messages, args.idle_timeout,
        )
    except KeyboardInterrupt:
        return
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.max_messages is not None and report["processed"] != args.max_messages:
        raise SystemExit("Stopped before requested number of records was processed")


if __name__ == "__main__":
    main()
