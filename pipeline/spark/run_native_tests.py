"""Run real isolated local services when Docker is unavailable; never use service data dirs."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pymysql
from pymongo import MongoClient
from pymongo.errors import OperationFailure

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "artifacts/native-runtime"


def wait_port(port, processes, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process, log in processes:
            if process.poll() is not None:
                raise RuntimeError(f"Service stopped ({process.returncode}); see {log}")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"Service port {port}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-data", action="store_true", help="Keep successful test topics and databases")
    parser.add_argument("--keep-mysql-running", action="store_true",
                        help="Keep test data and the isolated MySQL server running after a successful test")
    args = parser.parse_args()
    args.keep_data = args.keep_data or args.keep_mysql_running
    WORK.mkdir(parents=True, exist_ok=True)
    from prepare_jars import prepare
    prepare(ROOT / "jars", verify_only=True)
    for port in (33306, 37028, 39092, 19092, 39093, 37077, 38080, 38081, 38082, 38083):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Test port is already in use: {port}; no existing service was stopped")
    java_home = Path("/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
    if not java_home.exists():
        raise RuntimeError("Set up a Java 21 runtime before native testing")
    spark_home = ROOT / ".venv/lib/python3.14/site-packages/pyspark"
    if not spark_home.exists():
        raise RuntimeError("Install pyspark==4.2.0 in srcs/spark/.venv")
    kafka_home = WORK / "kafka_2.13-4.3.1"
    if not kafka_home.exists():
        raise RuntimeError("Download the official Kafka 4.3.1 distribution into artifacts/native-runtime")
    # Deployment settings must not override the generated, isolated test settings.
    inherited = {key: value for key, value in os.environ.items()
                 if not key.startswith(("KAFKA_", "MYSQL_", "MONGODB_", "SPARK_", "STD_SINKER_", "PYSPARK_"))}
    environment = {**inherited, "JAVA_HOME":str(java_home), "PATH":str(java_home / "bin") + os.pathsep + os.environ["PATH"],
                   "SPARK_HOME":str(spark_home), "PYSPARK_PYTHON":str(ROOT / ".venv/bin/python"),
                   "PYSPARK_DRIVER_PYTHON":str(ROOT / ".venv/bin/python"), "PYTHONPATH":str(ROOT),
                   "SPARK_LOCAL_IP":"127.0.0.1", "SPARK_DAEMON_MEMORY":"256m", "KAFKA_HEAP_OPTS":"-Xms256m -Xmx512m"}
    # Use the exact connector lock, replacing any bundled duplicate artifact versions.
    lock = json.loads((ROOT / "runtime_lock.json").read_text())
    for item in lock["spark_connector_jars"]:
        artifact = item["path"].split("/")[-3]
        for path in (spark_home / "jars").glob(artifact + "-*.jar"):
            path.unlink()
        shutil.copy2(ROOT / "jars" / Path(item["path"]).name, spark_home / "jars")
    properties = (ROOT / "kafka/node.properties").read_text().replace("kafka", "127.0.0.1")
    properties = properties.replace("0.0.0.0", "127.0.0.1").replace(":9093", ":39093")
    properties = properties.replace("/tmp/kraft-pipeline-logs", str(WORK / "kafka-data"))
    # The source comment uses the word Kafka; only endpoints and log path affect settings.
    kafka_properties = WORK / "node.properties"
    kafka_properties.write_text(properties)
    subprocess.run([str(kafka_home / "bin/kafka-storage.sh"), "format", "--ignore-formatted", "--standalone",
                    "--cluster-id", "MkU3OEVBNTcwNTJENDM2Qk", "--config", str(kafka_properties)], env=environment, check=True)
    mysql_data = WORK / "mysql-data"
    mysql_data.mkdir(exist_ok=True)
    mysqld = shutil.which("mysqld")
    if not mysqld or not shutil.which("mongod"):
        raise RuntimeError("Native MySQL and MongoDB binaries are required")
    mysql_base = Path(mysqld).resolve().parents[1]
    if not (mysql_data / "mysql").exists():
        with (WORK / "mysql-initialize.log").open("w") as log:
            subprocess.run([mysqld, "--no-defaults", "--initialize-insecure", "--basedir="+str(mysql_base),
                            "--datadir="+str(mysql_data)], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    mongo_data = WORK / "mongo-data"
    mongo_data.mkdir(exist_ok=True)
    processes, handles = [], []
    mysql_process = None
    completed = False
    retained_mysql = False

    def launch(name, command, extra=None, start_new_session=False):
        path = WORK / f"{name}.log"
        handle = path.open("w")
        handles.append(handle)
        process = subprocess.Popen(command, env={**environment, **(extra or {})}, stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=start_new_session)
        processes.append((process, path))
        return process

    try:
        mysql_process = launch("mysql", [mysqld, "--no-defaults", "--basedir="+str(mysql_base), "--datadir="+str(mysql_data),
                               "--port=33306", "--bind-address=127.0.0.1", "--socket="+str(WORK / "mysql.sock"),
                               "--mysqlx=OFF", "--innodb-buffer-pool-size=128M", "--max-connections=40"],
                               start_new_session=args.keep_mysql_running)
        wait_port(33306, processes)
        try:
            mysql = pymysql.connect(host="127.0.0.1", port=33306, user="root", password="", autocommit=True)
        except pymysql.MySQLError:
            mysql = pymysql.connect(host="127.0.0.1", port=33306, user="root", password="local-root-test", autocommit=True)
        with mysql.cursor() as cursor:
            cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY 'local-root-test'")
            cursor.execute("CREATE USER IF NOT EXISTS 'pipeline'@'%' IDENTIFIED BY 'local-pipeline-test'")
        mysql.close()
        launch("mongo", [shutil.which("mongod"), "--port", "37028", "--bind_ip", "127.0.0.1", "--replSet", "rs0",
                         "--dbpath", str(mongo_data), "--wiredTigerCacheSizeGB", "0.25"])
        wait_port(37028, processes)
        mongo = MongoClient("mongodb://127.0.0.1:37028/?directConnection=true", serverSelectionTimeoutMS=5000)
        try:
            mongo.admin.command("replSetGetStatus")
        except OperationFailure as error:
            if error.code != 94:
                raise
            mongo.admin.command("replSetInitiate", {"_id":"rs0", "members":[{"_id":0,"host":"127.0.0.1:37028"}]})
        deadline = time.monotonic()+30
        while not mongo.admin.command("hello").get("isWritablePrimary"):
            if time.monotonic() > deadline: raise TimeoutError("MongoDB primary election")
            time.sleep(0.2)
        mongo.close()
        launch("kafka", [str(kafka_home / "bin/kafka-server-start.sh"), str(kafka_properties)])
        wait_port(39092, processes)
        spark_class = str(spark_home / "bin/spark-class")
        launch("spark-master", [spark_class, "org.apache.spark.deploy.master.Master", "--host", "127.0.0.1",
                                "--port", "37077", "--webui-port", "38080"])
        wait_port(38080, processes)
        for number in range(1,4):
            directory = WORK / f"worker-{number}"
            directory.mkdir(exist_ok=True)
            launch(f"spark-worker-{number}", [spark_class, "org.apache.spark.deploy.worker.Worker", "--host", "127.0.0.1",
                    "--port",str(37080+number),"--webui-port",str(38080+number), "--cores","1","--memory","768M",
                    "--work-dir",str(directory),"spark://127.0.0.1:37077"])
        deadline = time.monotonic()+30
        while True:
            with urlopen("http://127.0.0.1:38080/json/", timeout=5) as response: master=json.load(response)
            if sum(worker["state"]=="ALIVE" for worker in master["workers"])==3:break
            if time.monotonic()>deadline:raise TimeoutError("Spark Worker registration")
            time.sleep(0.2)
        print("Native Kafka 4.3.1 / Spark 4.2.0 three Workers / isolated MySQL and MongoDB are ready", flush=True)
        command = [str(ROOT / ".venv/bin/python"), str(ROOT / "test_pipeline.py"), "--native"]
        if args.keep_data:
            command.append("--keep-data")
        subprocess.run(command, env=environment, check=True)
        completed = True
    finally:
        retained_mysql = (completed and args.keep_mysql_running and mysql_process is not None
                          and mysql_process.poll() is None)
        for process, _ in reversed(processes):
            if retained_mysql and process is mysql_process:
                continue
            if process.poll() is None: process.terminate()
        for process, _ in reversed(processes):
            if retained_mysql and process is mysql_process:
                continue
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
    if retained_mysql:
        print(f"Retained test MySQL: host=127.0.0.1 port=33306 pid={mysql_process.pid} data_directory={mysql_data}",
              flush=True)


if __name__ == "__main__":
    main()
