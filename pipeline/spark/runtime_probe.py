"""Integration smoke checks for the pinned Scala/JVM connectors."""
import argparse
import json
from pathlib import Path

from pyspark.sql import SparkSession

from spark_pipeline.config import Settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--mongo-database", required=True)
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    settings = Settings.from_env(args.env_file)
    spark = SparkSession.builder.appName("connector-probe").master(settings.master).getOrCreate()
    try:
        spark.sparkContext.setLogLevel("WARN")
        jvm = spark._jvm
        driver = jvm.com.mysql.cj.jdbc.Driver()
        properties = jvm.java.util.Properties()
        properties.setProperty("user", settings.mysql_user)
        properties.setProperty("password", settings.mysql_password)
        # Local test only; deployment TLS configuration is separate.
        jdbc = driver.connect(f"jdbc:mysql://{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?sslMode=DISABLED&allowPublicKeyRetrieval=true", properties)
        try:
            statement = jdbc.createStatement()
            result = statement.executeQuery("SELECT VERSION()")
            result.next()
            mysql_version = result.getString(1)
            result.close()
            statement.close()
        finally:
            jdbc.close()
        count = (spark.read.format("mongodb")
                 .option("connection.uri", args.mongo_uri)
                 .option("database", args.mongo_database).option("collection", "raw_logs").load().count())
        report = {"spark_version": spark.version, "java_version": jvm.java.lang.System.getProperty("java.version"),
                  "scala_version": jvm.scala.util.Properties.versionNumberString(),
                  "kafka_client_version": jvm.org.apache.kafka.common.utils.AppInfoParser.getVersion(),
                  "mysql_jdbc_version": f"{driver.getMajorVersion()}.{driver.getMinorVersion()}",
                  "mysql_server_version": mysql_version, "mongo_connector_raw_count": count}
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        spark.stop()
