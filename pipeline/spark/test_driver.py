"""Integration-only driver: inject a failure after a real table write."""
import argparse
from pathlib import Path

from spark_pipeline.config import Settings
from spark_pipeline.mysql_sink import MySQLWriter
from spark_pipeline.streaming import run_stream


class FailAfterTable(MySQLWriter):
    def __init__(self, config, batch_size, table, marker):
        super().__init__(config, batch_size)
        self.table, self.marker = table, Path(marker)

    def write(self, dataframe, table):
        super().write(dataframe, table)
        if table == self.table and not self.marker.exists() and not dataframe.isEmpty():
            self.marker.write_text("Injected failure after committed MySQL table write\n")
            raise RuntimeError("Injected failure after committed MySQL table write")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--fail-after-table", required=True)
    parser.add_argument("--marker", required=True)
    args = parser.parse_args()
    settings = Settings.from_env(args.env_file)
    writer = FailAfterTable(settings.mysql_config(), settings.batch_size, args.fail_after_table, args.marker)
    run_stream(settings, available_now=True, writer=writer)
