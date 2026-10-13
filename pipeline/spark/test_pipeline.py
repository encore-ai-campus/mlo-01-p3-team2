"""Real Sinker + Spark 4.2.0 + MySQL end-to-end test, with isolated resources."""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
STD = ROOT.parent / "std_and_sinker"
sys.path.insert(0, str(STD))

import pymysql
from confluent_kafka import Producer, TopicPartition
from confluent_kafka.admin import AdminClient
from pymongo import MongoClient

from sinker.config import Settings as RawSettings
from sinker.worker import run_worker
from spark_pipeline.contracts import COMMON_FACT_FIELDS, compile_contracts
from spark_pipeline.mysql_sink import connect
from spark_pipeline.validation import fingerprint, utc_time

COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.test.yml")]
ARTIFACTS = ROOT / "artifacts"
CONTAINER_ARTIFACTS = "/opt/pipeline/artifacts"
NATIVE = False


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def write_env(path, values):
    path.write_text("".join(f"{name}={json.dumps(str(value))}\n" for name, value in values.items()))


def execute(command, log, timeout=360, expected_success=True, env=None):
    with Path(log).open("w") as output:
        process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    check((process.returncode == 0) == expected_success,
          f"Unexpected command status {process.returncode}; see {Path(log).name}")
    return process.returncode


def spark_command(script, args):
    if NATIVE:
        lock = json.loads((ROOT / "runtime_lock.json").read_text())
        return [str(ROOT / ".venv/bin/spark-submit"), "--master", "spark://127.0.0.1:37077",
            "--deploy-mode", "client", "--driver-memory", "768m", "--executor-memory", "512m",
            "--jars", ",".join(str(ROOT / "jars" / Path(item["path"]).name) for item in lock["spark_connector_jars"]),
            "--conf", "spark.executor.cores=1", "--conf", "spark.cores.max=3",
            "--conf", "spark.driver.host=127.0.0.1", "--conf", "spark.driver.bindAddress=127.0.0.1",
            "--conf", "spark.task.maxFailures=1", str(ROOT / script)] + args
    return COMPOSE + ["exec", "-T", "spark-driver", "/opt/spark/bin/spark-submit",
        "--master", "spark://spark-master:7077", "--deploy-mode", "client",
        "--driver-memory", "768m", "--executor-memory", "512m",
        "--conf", "spark.executor.cores=1", "--conf", "spark.cores.max=3",
        "--conf", "spark.driver.host=spark-driver", "--conf", "spark.driver.bindAddress=0.0.0.0",
        "--conf", "spark.task.maxFailures=1", f"/opt/pipeline/srcs/spark/{script}"] + args


def publish(producer, topic, envelope, user, headers=None):
    if headers is None:
        headers = [("event_type", envelope["std_manifest"]["event_type"].encode()),
                   ("std_schema_version", envelope["std_manifest"]["std_schema_version"].encode())]
    reports = []
    value = envelope if isinstance(envelope, bytes) else json.dumps(envelope).encode()
    producer.produce(topic, key=user.encode(), value=value, headers=headers,
                     on_delivery=lambda error, message: reports.append((error, message)))
    check(producer.flush(15) == 0 and len(reports) == 1 and reports[0][0] is None, "Test Std publication failed")
    return reports[0][1].offset()


def fetch_facts(config, registry):
    result = {}
    with connect(config) as connection:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            for table in registry["fact_tables"]:
                cursor.execute(f"SELECT * FROM `{table}` ORDER BY event_uuid")
                result[table] = list(cursor.fetchall())
    return result


def assert_exact_facts(config, registry, messages):
    expected = {}
    for message in messages:
        envelope = message["value"]
        data, manifest = envelope["std_data"], envelope["std_manifest"]
        spec = registry["schemas"][f"{manifest['event_type']}|{manifest['std_schema_version']}"]
        target = {}
        for name in COMMON_FACT_FIELDS + registry["fact_tables"][spec["table"]]:
            value = data.get(name)
            if name.endswith("_uuid") and value is not None:
                value = uuid.UUID(value).hex
            elif name == "occurred_at":
                value = utc_time(value)
            target[name] = value
        target.update(parser_version=manifest["parser_version"], parser_rank=registry["parser_versions"].index(manifest["parser_version"]),
                      std_fingerprint=manifest["fingerprint"])
        expected[(spec["table"], target["event_uuid"])] = target
    actual = fetch_facts(config, registry)
    check(sum(map(len, actual.values())) == len(expected), "MySQL unique fact count mismatch")
    for table, rows in actual.items():
        for row in rows:
            target = expected[(table, row["event_uuid"])]
            differences = [name for name in row if row[name] != target.get(name)]
            check(not differences, f"MySQL field mapping mismatch: {table}/{row['event_uuid']} fields={differences}")
    return actual


def main():
    global NATIVE
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-data", action="store_true")
    parser.add_argument("--native", action="store_true", help="Use the isolated native test services")
    args = parser.parse_args()
    NATIVE = args.native
    ARTIFACTS.mkdir(exist_ok=True)
    run = uuid.uuid4().hex[:12]
    folder = ARTIFACTS / run
    folder.mkdir()
    container_folder = str(folder) if NATIVE else f"{CONTAINER_ARTIFACTS}/{run}"
    with urlopen("http://127.0.0.1:38080/json/", timeout=10) as response:
        master = json.load(response)
    alive = [worker for worker in master["workers"] if worker["state"] == "ALIVE"]
    check(len(alive) == 3, "Expected three registered Spark workers")
    # No checkpoint mount exists on any worker.
    if not NATIVE:
        for worker in ("spark-worker-1", "spark-worker-2", "spark-worker-3"):
            checked = subprocess.run(COMPOSE + ["exec", "-T", worker, "test", "!", "-e", CONTAINER_ARTIFACTS], capture_output=True)
            check(checked.returncode == 0, "Checkpoint directory unexpectedly visible on worker")

    # Test services and contracts are explicit; a deployment .env is not a fixture.
    base = RawSettings(
        bootstrap_servers="127.0.0.1:39092",
        input_topics=tuple(json.loads((STD / "contracts/routes.json").read_text())),
        group_id="pipeline_test_unused",
        mongo_uri="mongodb://127.0.0.1:37028/?directConnection=true&replicaSet=rs0",
        mongo_database="pipeline_test_unused",
    )
    # Explicit test-only overrides; never derive target resources from deployment environment variables.
    raw_env = {"KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:39092", "MONGODB_URI": "mongodb://127.0.0.1:37028/?directConnection=true&replicaSet=rs0",
               "MONGODB_DATABASE": "pipeline_test_unused", "STD_SINKER_INPUT_TOPICS": ",".join(base.input_topics),
               "STD_SINKER_CONSUMER_GROUP_ID": "pipeline_test_unused", "STD_SINKER_CONTRACTS_DIR": str(STD / "contracts"),
               "STD_SINKER_ROUTES_FILE": str(STD / "contracts/routes.json"), "KAFKA_SECURITY_PROTOCOL": "PLAINTEXT",
               "KAFKA_AUTO_OFFSET_RESET": "earliest", "KAFKA_DELIVERY_TIMEOUT_SECONDS": "30"}
    raw_env_file = folder / "std.env"
    write_env(raw_env_file, raw_env)
    sinker_report = folder / "sinker_report.json"
    execute([sys.executable, str(STD / "test_flow.py"), "--env-file", str(raw_env_file), "--report", str(sinker_report), "--keep-data"],
            folder / "sinker.log", timeout=180, env={**os.environ, **raw_env})
    upstream = json.loads(sinker_report.read_text())
    database = upstream["test_database"]
    check(database.startswith("stds_test_"), "Unexpected test resource prefix")
    registry = compile_contracts(STD / "contracts")
    registry["routes"] = {database + "." + topic: keys for topic, keys in registry["routes"].items()}
    registry["parser_versions"].append("1.1.0")
    (folder / "registry.json").write_text(json.dumps(registry))
    mysql_host_config = {"host": "127.0.0.1", "port": 33306, "user": "pipeline", "password": "local-pipeline-test",
                         "database": database, "charset": "utf8mb4", "autocommit": False}
    admin_mysql = pymysql.connect(host="127.0.0.1", port=33306, user="root", password="local-root-test", autocommit=True)
    with admin_mysql.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{database}`")
        cursor.execute(f"GRANT ALL PRIVILEGES ON `{database}`.* TO 'pipeline'@'%'")
    spark_values = {"KAFKA_BOOTSTRAP_SERVERS": "kafka:19092", "KAFKA_SECURITY_PROTOCOL": "PLAINTEXT",
        "SPARK_INPUT_TOPICS": ",".join(registry["routes"]), "SPARK_MASTER": "spark://spark-master:7077",
        "SPARK_REGISTRY_FILE": container_folder + "/registry.json",
        "SPARK_CHECKPOINT_LOCATION": "file://" + container_folder + "/checkpoints",
        "SPARK_STARTING_OFFSETS": "earliest", "SPARK_WRITE_PARTITIONS": 3, "SPARK_MAX_OFFSETS_PER_TRIGGER": 1000,
        "MYSQL_HOST": "mysql", "MYSQL_PORT": 3306, "MYSQL_DATABASE": database, "MYSQL_USER": "pipeline",
        "MYSQL_PASSWORD": "local-pipeline-test", "MYSQL_WRITE_BATCH_SIZE": 100}
    if NATIVE:
        spark_values.update(KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:19092", SPARK_MASTER="spark://127.0.0.1:37077",
                            MYSQL_HOST="127.0.0.1", MYSQL_PORT=33306)
    write_env(folder / "spark.env", spark_values)
    spark_env = container_folder + "/spark.env"
    completed = False
    report = {"result": "RUNNING", "run_id": run, "test_database": database}
    try:
        initial_messages = list(upstream["kafka_std_examples"])
        seed = deepcopy(next(message for message in initial_messages if message["value"]["std_data"]["event_type"] == "POST_READ"))
        producer = Producer({"bootstrap.servers": "127.0.0.1:39092", "acks": "all", "enable.idempotence": True})
        # Corrupt Std input tests independent of Sinker (which normally emits only valid Std).
        bad = []
        for label in ("missing_header", "duplicate_header", "header_body", "checksum", "integer_string", "missing_field", "key", "json", "version", "wrong_topic"):
            envelope = deepcopy(seed["value"])
            envelope["std_data"]["event_uuid"] = str(uuid.uuid4())
            envelope["std_manifest"]["fingerprint"] = fingerprint(envelope["std_data"])
            topic, user, headers = seed["topic"], seed["key"], None
            if label == "missing_header": headers = []
            elif label == "duplicate_header": headers = [("event_type", b"POST_READ"), ("event_type", b"POST_READ"), ("std_schema_version", b"1.0")]
            elif label == "header_body": envelope["std_manifest"]["event_type"] = "POST_UPDATED"; headers = [("event_type", b"POST_READ"), ("std_schema_version", b"1.0")]
            elif label == "checksum": envelope["std_manifest"]["fingerprint"] = "0000000000000000"
            elif label == "integer_string": envelope["std_data"]["revision"] = "3"; envelope["std_manifest"]["fingerprint"] = fingerprint(envelope["std_data"])
            elif label == "missing_field": del envelope["std_data"]["revision"]; envelope["std_manifest"]["fingerprint"] = fingerprint(envelope["std_data"])
            elif label == "key": user = "wrong-user"
            elif label == "json": envelope = b"{"; headers = [("event_type", b"POST_READ"), ("std_schema_version", b"1.0")]
            elif label == "version": headers = [("event_type", b"POST_READ"), ("std_schema_version", b"9.0")]
            elif label == "wrong_topic": topic = database + ".standardized.chat"
            offset = publish(producer, topic, envelope, user, headers)
            bad.append({"case": label, "topic": topic, "partition": 0, "offset": offset})
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now", "--migrate", "--report", container_folder + "/initial.json"]), folder / "spark-initial.log")
        initial = json.loads((folder / "initial.json").read_text())
        check(initial["executor_count"] == 3, "Expected three live distributed Executors")
        actual = assert_exact_facts(mysql_host_config, registry, initial_messages)
        check(sum(map(len, actual.values())) == upstream["kafka_unique_success_ids"], "Sinker duplicates leaked into fact counts")
        expected_codes = {"missing_header":"INVALID_HEADER", "duplicate_header":"INVALID_HEADER", "header_body":"HEADER_BODY_MISMATCH",
            "checksum":"STD_CHECKSUM_MISMATCH", "integer_string":"INVALID_VALUE", "missing_field":"MISSING_FIELD", "key":"KEY_MISMATCH",
            "json":"PARSE_ERROR", "version":"UNSUPPORTED_SCHEMA", "wrong_topic":"UNSUPPORTED_SCHEMA"}
        with connect(mysql_host_config) as connection:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM stream_processing_error")
                errors = list(cursor.fetchall())
        check(len(errors) == len(bad), "Std error quarantine count mismatch")
        indexed_errors = {(row["topic"], row["offset"]):row for row in errors}
        for item in bad:
            check(indexed_errors[(item["topic"], item["offset"])]["error_code"] == expected_codes[item["case"]], "Incorrect Std error code")
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now", "--report", container_folder + "/restart.json"]), folder / "spark-restart.log")
        restart = json.loads((folder / "restart.json").read_text())
        check(restart["input_rows"] == 0 and restart["query_id"] == initial["query_id"], "Checkpoint restart did not resume progress")

        # Same-version conflict, higher-version update, lower-version late redelivery.
        conflict = deepcopy(seed["value"])
        conflict["std_data"]["revision"] += 10
        conflict["std_manifest"]["fingerprint"] = fingerprint(conflict["std_data"])
        conflict_offset = publish(producer, seed["topic"], conflict, seed["key"])
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now", "--report", container_folder + "/conflict.json"]), folder / "spark-conflict.log")
        assert_exact_facts(mysql_host_config, registry, initial_messages)
        higher = deepcopy(conflict)
        higher["std_manifest"]["parser_version"] = "1.1.0"
        publish(producer, seed["topic"], higher, seed["key"])
        publish(producer, seed["topic"], seed["value"], seed["key"])
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now", "--report", container_folder + "/versions.json"]), folder / "spark-versions.log")
        repaired_messages = [deepcopy(item) for item in initial_messages]
        for item in repaired_messages:
            if item["value"]["std_data"]["event_uuid"] == higher["std_data"]["event_uuid"]: item["value"] = higher
        assert_exact_facts(mysql_host_config, registry, repaired_messages)
        with connect(mysql_host_config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT error_code FROM stream_processing_error WHERE topic=%s AND `offset`=%s", (seed["topic"], conflict_offset))
                check(cursor.fetchone() == ("RESULT_CONFLICT",), "Same-version conflict was not quarantined")

        # Actual Sinker emits two new events; stop Spark after first table commit, then replay the batch.
        raw_examples = {doc["_id"]: doc for doc in upstream["mongo_examples"]["raw_logs"]}
        raw_seed_cases = []
        for event in ("CHAT_SENT", "POST_READ"):
            sample = next(item for item in initial_messages if item["value"]["std_data"]["event_type"] == event)
            raw = raw_examples[sample["value"]["std_data"]["event_uuid"]]
            envelope = {"event_uuid": str(uuid.uuid4()), "raw_manifest": raw["raw_manifest"], "raw_data": raw["raw_data"]}
            raw_producer = Producer({"bootstrap.servers": "127.0.0.1:39092", "acks": "all"})
            done = []
            raw_producer.produce(raw["kafka_origin"]["topic"], key=sample["key"].encode(), value=json.dumps(envelope).encode(),
                                 partition=0, on_delivery=lambda error, message: done.append(error))
            check(raw_producer.flush(15) == 0 and done == [None], "Additional Raw publication failed")
            raw_seed_cases.append((sample, envelope))
        from dataclasses import replace
        raw_routes = json.loads((STD / "contracts/routes.json").read_text())
        route_override = {database + "." + topic:{**route, "output_topic": database + "." + route["output_topic"]} for topic, route in raw_routes.items()}
        (folder / "raw-routes.json").write_text(json.dumps(route_override))
        raw_settings = replace(base, bootstrap_servers="127.0.0.1:39092", input_topics=tuple(route_override), group_id=database,
                               mongo_uri=raw_env["MONGODB_URI"], mongo_database=database, routes_file=folder / "raw-routes.json")
        resumed_raw = run_worker(raw_settings, max_messages=2, idle_timeout=30)
        check(resumed_raw["counts"] == {"SUCCESS":2}, "Additional Raw flow failed")
        execute(spark_command("test_driver.py", ["--env-file", spark_env, "--fail-after-table", "chat_activity_fact", "--marker", container_folder + "/fault.marker"]),
                folder / "spark-fault.log", expected_success=False)
        check((folder / "fault.marker").exists(), "Failure injection did not reach committed table write")
        interim = fetch_facts(mysql_host_config, registry)
        new_chat_id, new_post_id = [uuid.UUID(envelope["event_uuid"]).hex for _,envelope in raw_seed_cases]
        check(any(row["event_uuid"] == new_chat_id for row in interim["chat_activity_fact"]), "First table did not commit")
        check(not any(row["event_uuid"] == new_post_id for row in interim["post_activity_fact"]), "Second table unexpectedly committed")
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now", "--report", container_folder + "/recovery.json"]), folder / "spark-recovery.log")
        final = fetch_facts(mysql_host_config, registry)
        check(sum(map(len, final.values())) == upstream["kafka_unique_success_ids"] + 2, "Partial-batch replay duplicated or lost facts")
        check(sum(row["event_uuid"] == new_chat_id for row in final["chat_activity_fact"]) == 1, "Replayed chat was duplicated")
        check(sum(row["event_uuid"] == new_post_id for row in final["post_activity_fact"]) == 1, "Replayed post missing")
        recovery = json.loads((folder / "recovery.json").read_text())
        check(recovery["input_rows"] == 2, "Failed batch was not replayed from checkpoint")

        mongo_uri = raw_env["MONGODB_URI"] if NATIVE else "mongodb://mongo:27017/?directConnection=true&replicaSet=rs0"
        execute(spark_command("runtime_probe.py", ["--env-file", spark_env, "--mongo-database", database, "--mongo-uri", mongo_uri,
                                                   "--report", container_folder + "/runtime.json"]), folder / "runtime.log")
        runtime = json.loads((folder / "runtime.json").read_text())
        version_command = [str(ROOT / "artifacts/native-runtime/kafka_2.13-4.3.1/bin/kafka-topics.sh"), "--version"] if NATIVE else COMPOSE + ["exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--version"]
        broker_version = subprocess.check_output(version_command, text=True).strip()
        check(broker_version.startswith("4.3.1"), "Kafka broker distribution version mismatch")
        runtime["kafka_broker_version"] = broker_version
        check(runtime["spark_version"] == "4.2.0" and runtime["kafka_client_version"] == "3.9.2", "Runtime version mismatch")
        check(runtime["scala_version"].startswith("2.13.") and runtime["mysql_jdbc_version"] == "9.7", "Scala/JDBC version mismatch")
        check(runtime["mongo_connector_raw_count"] == upstream["mongo_counts"]["raw_logs"] + 2, "Mongo connector smoke read mismatch")
        with connect(mysql_host_config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM stream_processing_error")
                final_error_count = cursor.fetchone()[0]
        check(final_error_count == len(bad)+1, "Error quarantine replay was not idempotent")
        # Trim an unread event past the saved offset: failOnDataLoss must stop, never silently skip.
        expired = deepcopy(seed["value"])
        expired["std_data"]["event_uuid"] = str(uuid.uuid4())
        expired["std_manifest"]["fingerprint"] = fingerprint(expired["std_data"])
        expired_offset = publish(producer, seed["topic"], expired, seed["key"])
        retention_admin = AdminClient({"bootstrap.servers":"127.0.0.1:39092"})
        deleted = retention_admin.delete_records([TopicPartition(seed["topic"], 0, expired_offset+1)])
        for future in deleted.values(): future.result(timeout=30)
        commits_before = {path.name:path.read_bytes() for path in (folder / "checkpoints/commits").glob("*") if path.is_file()}
        execute(spark_command("stream.py", ["--env-file", spark_env, "--available-now"]), folder / "spark-retention.log", expected_success=False)
        diagnostic = (folder / "spark-retention.log").read_text().lower()
        check("data loss" in diagnostic or "data may have been lost" in diagnostic or "kafka_data_loss" in diagnostic,
              "Retention failure was not caused by missing Kafka offsets")
        commits_after = {path.name:path.read_bytes() for path in (folder / "checkpoints/commits").glob("*") if path.is_file()}
        check(commits_before == commits_after, "Data loss advanced completed checkpoint")
        check(fetch_facts(mysql_host_config, registry) == final, "Data loss changed completed facts")
        checkpoint_files = [str(path.relative_to(folder)) for path in (folder / "checkpoints").rglob("*") if path.is_file()]
        check(not (folder / "checkpoints/state").exists(), "Unexpected streaming state checkpoint")
        report.update(result="PASS", runtime=runtime, worker_count=len(alive), sinker=upstream,
                      initial_spark=initial, restart=restart, recovery=recovery,
                      initial_fact_counts={table:len(rows) for table,rows in actual.items()},
                      final_fact_counts={table:len(rows) for table,rows in final.items()},
                      final_error_count=final_error_count, malformed_std_cases=bad,
                      checkpoint_files=checkpoint_files, checkpoint_visible_only_to_driver=not NATIVE,
                      environment="native single host / three Worker processes" if NATIVE else "Docker / three isolated Worker containers",
                      retention_guard="missing Kafka offset stopped query without advancing completed checkpoint",
                      checks=["15 event types / nine tables / every mapped value", "Mongo original and failure storage",
                              "Std failure publication blocked", "Std header/body/key/types/fingerprint errors",
                              "duplicate facts absorbed by MySQL", "same checkpoint restart / zero reread",
                              "same parser conflict / higher parser update / lower parser ignored",
                              "partial table write / failed batch replay", "Kafka offset expiry / failOnDataLoss / no commit advance",
                              "three Workers / Driver progress checkpoint / no streaming state",
                              "Spark 4.2.0 / Scala 2.13 / Kafka client 3.9.2 / JDBC 9.7 / Mongo connector smoke"])
        completed = True
    except Exception as error:
        report.update(result="FAIL", failure=str(error))
        raise
    finally:
        path = folder / "integration_report.json"
        try:
            if completed and not args.keep_data:
                with admin_mysql.cursor() as cursor: cursor.execute(f"DROP DATABASE `{database}`")
                mongo = MongoClient(raw_env["MONGODB_URI"])
                mongo.drop_database(database)
                mongo.close()
                topics = list(upstream["offsets"]) + list(registry["routes"])
                # Keep the AdminClient alive until asynchronous delete futures complete.
                admin_kafka = AdminClient({"bootstrap.servers":"127.0.0.1:39092"})
                futures = admin_kafka.delete_topics(topics)
                for future in futures.values(): future.result(timeout=30)
                report["cleanup"] = "own topics and databases removed"
        except Exception as error:
            report.update(result="FAIL", cleanup_failure=str(error))
            raise
        finally:
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
            (ARTIFACTS / "latest.json").write_text(json.dumps({"report":str(path.relative_to(ROOT)), "result":report["result"]}) + "\n")
            admin_mysql.close()
    print(json.dumps({"result":report["result"], "worker_count":3, "initial_facts":sum(map(len,actual.values())),
                      "final_facts":sum(map(len,final.values())), "errors":report["final_error_count"], "report":str(path)}, indent=2))


if __name__ == "__main__":
    main()
