import json
import tempfile
from pathlib import Path

from .contracts import COMMON_FACT_FIELDS, FACT_TABLES, envelope_schema, fact_defaults, load_registry
from .mysql_sink import MySQLWriter
from .package import package_code
from .validation import validate_std


def verdict_schema():
    from pyspark.sql.types import StringType, StructField, StructType
    return StructType([StructField(name, StringType()) for name in (
        "event_type", "version", "table", "event_uuid", "error_code", "error_detail")])


class BatchProcessor:
    def __init__(self, registry, settings, writer=None):
        self.registry = registry
        self.settings = settings
        self.writer = writer or MySQLWriter(settings.mysql_config(), settings.batch_size)

    def __call__(self, batch, batch_id):
        from pyspark import StorageLevel
        from pyspark.sql import functions as F
        registry = self.registry
        validator = F.udf(lambda topic, key, value, headers: validate_std(topic, key, value, headers, registry), verdict_schema(), useArrow=False)
        checked = batch.withColumn("verdict", validator("topic", "key", "value", "headers"))
        checked.persist(StorageLevel.MEMORY_AND_DISK)
        try:
            errors = checked.where(F.col("verdict.error_code").isNotNull()).select(
                F.col("topic").alias("__topic"), F.col("partition").alias("__partition"), F.col("offset").alias("__offset"),
                F.col("verdict.event_uuid").alias("event_uuid"), F.col("verdict.error_code").alias("error_code"),
                F.col("verdict.error_detail").alias("error_detail"),
            ).repartition(self.settings.write_partitions, "__topic", "__partition")
            self.writer.write(errors, None)
            valid = checked.where(F.col("verdict.error_code").isNull())
            # Only collect the bounded schema-key set, never event payloads.
            active = {(row[0], row[1]) for row in valid.select("verdict.event_type", "verdict.version").distinct().collect()}
            # Separate schemas per event/version; no giant union schema and no cross-batch state.
            for spec in registry["schemas"].values():
                if (spec["event_type"], spec["version"]) not in active:
                    continue
                selected = valid.where((F.col("verdict.event_type") == spec["event_type"]) &
                                       (F.col("verdict.version") == spec["version"]))
                parsed = selected.withColumn("parsed", F.from_json(F.col("value").cast("string"),
                                                                   envelope_schema(spec, registry["domains"]),
                                                                   {"mode": "FAILFAST"}))
                table = spec["table"]
                columns = []
                defaults = fact_defaults(spec)
                for name in COMMON_FACT_FIELDS + FACT_TABLES[table]:
                    if name in defaults:
                        value = F.lit(defaults[name]).cast("string")
                    else:
                        value = F.col("parsed.std_data." + name)
                    if name.endswith("_uuid"):
                        value = F.regexp_replace(value, "-", "")
                    elif name == "occurred_at":
                        # TimestampType -> Python datetime uses the worker OS timezone.
                        # Format in the UTC Spark session before crossing into Python DB-API.
                        value = F.date_format(F.to_timestamp(value), "yyyy-MM-dd HH:mm:ss.SSSSSS")
                    columns.append(value.alias(name))
                rank_map = F.create_map(*[item for rank, version in enumerate(registry["parser_versions"])
                                          for item in (F.lit(version), F.lit(rank))])
                columns.extend([
                    F.col("parsed.std_manifest.parser_version").alias("parser_version"),
                    F.element_at(rank_map, F.col("parsed.std_manifest.parser_version")).alias("parser_rank"),
                    F.col("parsed.std_manifest.fingerprint").alias("std_fingerprint"),
                    F.col("topic").alias("__topic"), F.col("partition").alias("__partition"), F.col("offset").alias("__offset"),
                ])
                mapped = parsed.select(*columns).repartition(self.settings.write_partitions, "event_uuid").sortWithinPartitions("event_uuid")
                self.writer.write(mapped, table)
        finally:
            checked.unpersist()


def run_stream(settings, available_now=False, writer=None, report=None):
    from pyspark.sql import SparkSession
    registry = load_registry(settings.registry_path)
    if any(topic not in registry["routes"] for topic in settings.input_topics):
        raise ValueError("Missing subscribed topic in Spark registry")
    spark = (SparkSession.builder.appName("std-to-mysql").master(settings.master)
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", settings.write_partitions)
             .config("spark.sql.streaming.statefulOperator.checkCorrectness.enabled", "true")
             .getOrCreate())
    code_directory = None
    try:
        if spark.version != "4.2.0":
            raise RuntimeError(f"Expected Spark 4.2.0, got {spark.version}")
        spark.sparkContext.setLogLevel("WARN")
        code_directory = tempfile.TemporaryDirectory(prefix="spark-pipeline-code-")
        code_path = Path(code_directory.name) / "spark_pipeline.zip"
        code_sha256 = package_code(code_path)
        spark.sparkContext.addPyFile(str(code_path))
        source = spark.readStream.format("kafka").options(**settings.kafka_options()).load()
        stream = (source.writeStream.foreachBatch(BatchProcessor(registry, settings, writer))
                  .option("checkpointLocation", settings.checkpoint))
        stream = stream.trigger(availableNow=True) if available_now else stream.trigger(processingTime=f"{settings.trigger_seconds} seconds")
        query = stream.start()
        query.awaitTermination()
        progress = [json.loads(json.dumps(item, default=str)) for item in query.recentProgress]
        result = {"result": "PASS", "spark_version": spark.version, "query_id": str(query.id),
                  "run_id": str(query.runId), "input_rows": sum(item["numInputRows"] for item in progress),
                  "progress": progress, "checkpoint": settings.checkpoint,
                  "executor_hosts": [f"{info.host()}:{info.port()}" for info in spark.sparkContext._jsc.sc().statusTracker().getExecutorInfos()],
                  "executor_count": spark.sparkContext._jsc.sc().getExecutorMemoryStatus().size() - 1,
                  "python_code_sha256": code_sha256}
        if any(item.get("stateOperators") for item in progress):
            raise RuntimeError("Unexpected stateful streaming operation")
        if report:
            path = Path(report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: result[key] for key in ("result", "spark_version", "query_id", "input_rows")}))
        return result
    finally:
        try:
            spark.stop()
        finally:
            if code_directory is not None:
                code_directory.cleanup()
