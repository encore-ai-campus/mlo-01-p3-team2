#!/usr/bin/env python3
"""Run the foreground client Driver with a systemd RAM credential."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="/etc/spark-pipeline/pipeline.env")
    parser.add_argument("--credential-name", default="mysql-password")
    parser.add_argument("--available-now", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    if "MYSQL_PASSWORD" in values:
        raise RuntimeError("MYSQL_PASSWORD must come from the systemd credential")
    if any(value is None for value in values.values()):
        raise RuntimeError("Environment file contains a setting without a value")
    environment = {**os.environ, **values}
    credential_directory = environment.get("CREDENTIALS_DIRECTORY")
    if not credential_directory or Path(args.credential_name).name != args.credential_name:
        raise RuntimeError("Missing systemd credential directory or invalid credential name")
    password = (Path(credential_directory) / args.credential_name).read_text().rstrip("\r\n")
    if not password or "\x00" in password:
        raise RuntimeError("Empty or invalid MySQL credential")
    environment["MYSQL_PASSWORD"] = password
    root = Path(environment.get("SPARK_PIPELINE_ROOT", "/opt/pipeline/spark/current"))
    python = environment.get("SPARK_PIPELINE_PYTHON", "/opt/pipeline/spark/.venv/bin/python")
    spark_submit = environment.get("SPARK_SUBMIT", "/opt/spark/bin/spark-submit")
    local_directory = Path(environment.get("SPARK_PIPELINE_LOCAL_DIR", "/var/lib/spark-pipeline/local"))
    local_directory.mkdir(parents=True, exist_ok=True)
    jars = []
    lock = json.loads((root / "runtime_lock.json").read_text())
    for item in lock["spark_connector_jars"]:
        jar = root / "jars" / Path(item["path"]).name
        if hashlib.sha256(jar.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Pinned JAR checksum mismatch: " + jar.name)
        jars.append(str(jar))
    driver_host = environment.get("SPARK_DRIVER_HOST", "10.30.10.113")
    master = environment.get("SPARK_MASTER", "spark://10.30.10.113:7077,10.20.10.174:7077")
    environment.update(SPARK_MASTER=master, PYSPARK_PYTHON=python, PYSPARK_DRIVER_PYTHON=python,
                       PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    configuration = {
        "spark.cores.max": "3", "spark.executor.instances": "3", "spark.executor.cores": "1",
        "spark.executor.memory": "2g", "spark.executor.memoryOverhead": "512m",
        "spark.driver.memory": "1g", "spark.driver.host": driver_host,
        "spark.driver.bindAddress": driver_host, "spark.driver.port": "7078",
        "spark.driver.blockManager.port": "7080", "spark.blockManager.port": "7079",
        "spark.port.maxRetries": "0", "spark.dynamicAllocation.enabled": "false",
        "spark.pyspark.python": python, "spark.pyspark.driver.python": python,
        "spark.python.worker.reuse": "true", "spark.local.dir": str(local_directory),
        "spark.sql.shuffle.partitions": environment.get("SPARK_WRITE_PARTITIONS", "3"),
        "spark.ui.enabled": "true", "spark.ui.port": "4040",
        "spark.redaction.regex": "(?i)secret|password|token|access[.]?key",
        "spark.sql.redaction.options.regex": "(?i)secret|password|token|access[.]?key",
    }
    command = [spark_submit, "--master", master, "--deploy-mode", "client", "--driver-memory", "1g",
               "--executor-memory", "2g", "--executor-cores", "1", "--total-executor-cores", "3",
               "--jars", ",".join(jars)]
    for key, value in configuration.items():
        command.extend(("--conf", key + "=" + value))
    command.extend((str(root / "stream.py"), "--env-file", str(Path(args.env_file).resolve())))
    if args.available_now:
        command.append("--available-now")
    if args.migrate:
        command.append("--migrate")
    if args.report:
        command.extend(("--report", args.report))
    os.execvpe(spark_submit, command, environment)


if __name__ == "__main__":
    main()
