import argparse

from spark_pipeline.config import ROOT, Settings
from spark_pipeline.mysql_sink import migrate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    args = parser.parse_args()
    migrate(Settings.from_env(args.env_file).mysql_config())
    print("Nine fact tables and stream_processing_error are ready")
