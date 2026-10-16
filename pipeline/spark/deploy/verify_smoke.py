#!/usr/bin/env python3
"""Compare an isolated smoke database to fixture rows without exposing payloads."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re


TABLES = (
    "account_activity_fact", "chat_activity_fact", "post_activity_fact", "comment_activity_fact",
    "content_activity_fact", "quiz_attempt_fact", "movement_fact", "floor_transfer_fact",
    "point_grant_fact", "stream_processing_error",
)


def normalize_value(value, expected=None):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(sep=" ", timespec="microseconds")
    if type(expected) is bool and type(value) in (int, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, Decimal):
        if type(expected) is float:
            return float(value)
        if type(expected) is int and value == value.to_integral_value():
            return int(value)
        return str(value)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def compare_rows(table, expected_rows, actual_rows):
    """Pure multiset comparison; reports only counts and differing column names."""
    primary_key = ("topic", "partition", "offset") if table == "stream_processing_error" else ("event_uuid",)
    columns = set(expected_rows[0]) if expected_rows else set()
    if any(set(row) != columns for row in expected_rows):
        raise ValueError("Expected rows have inconsistent columns")
    if columns and not set(primary_key).issubset(columns):
        raise ValueError("Expected rows omit primary key columns")
    expected_index = {tuple(row[name] for name in primary_key): row for row in expected_rows}
    if len(expected_index) != len(expected_rows):
        raise ValueError("Expected rows have repeated primary keys")
    template = {name: next((row[name] for row in expected_rows if row[name] is not None), None)
                for name in columns}
    normalized_actual, differences = [], set()
    expected_identities = set(expected_index)
    actual_identities = set()
    for row in actual_rows:
        identity = tuple(row.get(name) for name in primary_key)
        actual_identities.add(identity)
        reference = expected_index.get(identity, template)
        normalized = {name: normalize_value(row.get(name), reference.get(name)) for name in columns}
        normalized_actual.append(normalized)
        if set(row) != columns:
            differences.update(set(row) ^ columns)
        if identity in expected_index:
            differences.update(name for name in columns
                               if canonical(normalized[name]) != canonical(expected_index[identity][name]))
    if actual_identities != expected_identities:
        differences.update(primary_key)
    expected_counter = Counter(canonical(row) for row in expected_rows)
    actual_counter = Counter(canonical(row) for row in normalized_actual)
    missing = sum((expected_counter - actual_counter).values())
    unexpected = sum((actual_counter - expected_counter).values())
    passed = expected_counter == actual_counter and not differences and len(expected_rows) == len(actual_rows)
    return {"table": table, "pass": passed, "expected_count": len(expected_rows), "actual_count": len(actual_rows),
            "missing_row_count": missing, "unexpected_row_count": unexpected,
            "differing_columns": sorted(differences)}


def verify(env_file, expected_path):
    import pymysql
    from dotenv import dotenv_values

    expected = json.loads(Path(expected_path).read_text())
    if type(expected) is not dict or set(expected) != set(TABLES):
        raise ValueError("Expected fixture must contain exactly the ten smoke tables")
    for table in TABLES:
        rows = expected[table]
        if type(rows) is not list or any(type(row) is not dict for row in rows):
            raise ValueError("Expected fixture rows must be objects")
        if rows:
            columns = set(rows[0])
            if not columns or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in columns):
                raise ValueError("Invalid expected column identifier")
            if table == "stream_processing_error" and "observed_at" in columns:
                raise ValueError("Smoke expected rows must exclude observed_at")
            if any(set(row) != columns for row in rows):
                raise ValueError("Expected rows have inconsistent columns")
    values = dotenv_values(env_file)
    if "MYSQL_PASSWORD" in values:
        raise ValueError("MySQL password must come from the RAM credential")
    environment = {**os.environ, **values}
    database = environment.get("MYSQL_DATABASE", "")
    if not re.fullmatch(r"spark_smoke_[A-Za-z0-9_]{1,52}", database):
        raise ValueError("Verification requires an isolated spark_smoke_ database")
    credential_directory = environment.get("CREDENTIALS_DIRECTORY")
    if not credential_directory:
        raise ValueError("Missing systemd credential directory")
    password = (Path(credential_directory) / "mysql-password").read_text().rstrip("\r\n")
    if not password or "\x00" in password:
        raise ValueError("Empty or invalid MySQL credential")
    configuration = {
        "host": environment.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(environment.get("MYSQL_PORT", "6446")),
        "user": environment.get("MYSQL_USER", "dev"), "password": password,
        "database": database, "charset": "utf8mb4", "autocommit": False,
        "connect_timeout": 10, "read_timeout": 30, "write_timeout": 30,
        "cursorclass": pymysql.cursors.DictCursor,
    }
    if environment.get("MYSQL_SSL_CA"):
        configuration.update(ssl_ca=environment["MYSQL_SSL_CA"], ssl_verify_cert=True, ssl_verify_identity=True)
    results = []
    with pymysql.connect(**configuration) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION time_zone = '+00:00'")
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            connection.begin()
            for table in TABLES:
                rows = expected[table]
                if not rows:
                    cursor.execute(f"SELECT COUNT(*) AS row_count FROM `{table}`")
                    count = cursor.fetchone()["row_count"]
                    results.append({"table": table, "pass": count == 0, "expected_count": 0,
                                    "actual_count": count, "missing_row_count": 0,
                                    "unexpected_row_count": count, "differing_columns": []})
                    continue
                columns = ",".join(f"`{name}`" for name in rows[0])
                cursor.execute(f"SELECT {columns} FROM `{table}`")
                results.append(compare_rows(table, rows, list(cursor.fetchall())))
        connection.rollback()
    passed = all(table["pass"] for table in results)
    return {"result": "PASS" if passed else "FAIL", "pass": passed, "tables": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = verify(args.env_file, args.expected)
    except Exception as error:
        # MySQL and OS exception text may contain connection details or values.
        report = {"result": "FAIL", "pass": False, "tables": [], "error_type": type(error).__name__}
        if error.args and type(error.args[0]) is int:
            report["error_code"] = error.args[0]
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    try:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload)
    except OSError:
        report.update(result="FAIL", **{"pass": False}, output_write_failed=True)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
