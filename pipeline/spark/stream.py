import argparse

from spark_pipeline.config import ROOT, Settings
from spark_pipeline.mysql_sink import migrate
from spark_pipeline.streaming import run_stream


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--available-now", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    settings = Settings.from_env(args.env_file)
    if args.migrate:
        migrate(settings.mysql_config())
    run_stream(settings, args.available_now, report=args.report)
