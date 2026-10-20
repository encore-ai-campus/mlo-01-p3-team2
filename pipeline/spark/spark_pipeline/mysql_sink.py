import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pymysql

from .contracts import COMMON_FACT_FIELDS, FACT_TABLES
from .validation import source_reference

LOG = logging.getLogger(__name__)
META_FIELDS = ["parser_version", "parser_rank", "std_fingerprint"]


def connect(config):
    connection = pymysql.connect(**config)
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION time_zone = '+00:00'")
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
    return connection


def migrate(config, migration=None):
    migration = migration or Path(__file__).resolve().parents[1] / "migrations/001_facts.sql"
    with connect(config) as connection:
        with connection.cursor() as cursor:
            for statement in Path(migration).read_text().split(";"):
                if statement.strip():
                    cursor.execute(statement)
        connection.commit()


def error_values(row, code=None, detail=None):
    identifier = row.get("event_uuid")
    return (
        row["__topic"], row["__partition"], row["__offset"],
        identifier.replace("-", "") if identifier else None,
        code or row["error_code"], detail or row["error_detail"],
        source_reference(row["__topic"], row["__partition"], row["__offset"]),
    )


ERROR_SQL = """INSERT INTO stream_processing_error
    (`topic`,`partition`,`offset`,`event_uuid`,`error_code`,`error_detail`,`source_reference`)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE `topic`=VALUES(`topic`)"""


def write_chunk(connection, rows, table):
    with connection.cursor() as cursor:
        if table is None:
            cursor.executemany(ERROR_SQL, [error_values(row) for row in rows])
            return
        if table not in FACT_TABLES:
            raise ValueError("Unknown fact table")
        columns = COMMON_FACT_FIELDS + FACT_TABLES[table] + META_FIELDS
        escaped = ",".join(f"`{name}`" for name in columns)
        assignments = ",".join(f"`{name}`=VALUES(`{name}`)" for name in columns if name != "event_uuid")
        statement = f"INSERT INTO `{table}` ({escaped}) VALUES ({','.join(['%s'] * len(columns))}) ON DUPLICATE KEY UPDATE {assignments}"
        insert = f"INSERT INTO `{table}` ({escaped}) VALUES ({','.join(['%s'] * len(columns))})"
        for row in sorted(rows, key=lambda item: item["event_uuid"]):
            cursor.execute(f"SELECT parser_rank,std_fingerprint FROM `{table}` WHERE event_uuid=%s FOR UPDATE",
                           (row["event_uuid"],))
            existing = cursor.fetchone()
            if existing:
                old_rank, old_fingerprint = existing
                if row["parser_rank"] < old_rank:
                    continue
                if row["parser_rank"] == old_rank:
                    if row["std_fingerprint"] != old_fingerprint:
                        cursor.execute(ERROR_SQL, error_values(row, "RESULT_CONFLICT", "Different Std fingerprint for the same parser version"))
                        LOG.error("RESULT_CONFLICT topic=%s partition=%s offset=%s",
                                  row["__topic"], row["__partition"], row["__offset"])
                    continue
            # A concurrent insert must retry the transaction and re-check version/fingerprint.
            # Blind ON DUPLICATE KEY UPDATE on a missing row could otherwise downgrade it.
            cursor.execute(statement if existing else insert, tuple(row[name] for name in columns))


def write_partition(iterator, config, table, batch_size):
    """One reusable connection per Spark partition; bounded chunks and deadlock retries."""
    connection = None
    try:
        rows = []
        for item in iterator:
            rows.append(item.asDict(recursive=True) if hasattr(item, "asDict") else dict(item))
            if len(rows) >= batch_size:
                connection = commit_chunk(connection, config, rows, table)
                rows.clear()
        if rows:
            connection = commit_chunk(connection, config, rows, table)
    finally:
        if connection is not None:
            connection.close()


def commit_chunk(connection, config, rows, table):
    if connection is None:
        connection = connect(config)
    for attempt in range(3):
        try:
            connection.begin()
            write_chunk(connection, rows, table)
            connection.commit()
            return connection
        except pymysql.MySQLError as error:
            connection.rollback()
            if error.args[0] not in (1062, 1205, 1213) or attempt == 2:
                raise
            time.sleep(0.1 * (2**attempt))


class MySQLWriter:
    def __init__(self, config, batch_size):
        self.config = config
        self.batch_size = batch_size

    def write(self, dataframe, table):
        config, batch_size = self.config, self.batch_size
        dataframe.foreachPartition(lambda iterator: write_partition(iterator, config, table, batch_size))
