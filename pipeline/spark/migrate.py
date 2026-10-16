import argparse
from pathlib import Path

from spark_pipeline.config import ROOT, Settings
from spark_pipeline.mysql_sink import migrate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--migration", type=Path, help="Explicit SQL migration; omitted means initial CREATE TABLE only")
    args = parser.parse_args()
    migrate(Settings.from_env(args.env_file).mysql_config(), args.migration)
    print("Migration applied: " + (args.migration.name if args.migration else "001_facts.sql"))
