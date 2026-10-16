"""Exercise mixed quiz versions through actual Spark parsing and batch mapping."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from spark_pipeline.contracts import compile_contracts, envelope_schema
from spark_pipeline.package import package_code
from spark_pipeline.streaming import BatchProcessor
from spark_pipeline.validation import fingerprint


ROOT = Path(__file__).resolve().parents[1]
STD = ROOT.parent / "std_and_sinker"
sys.path.insert(0, str(STD))


class CapturingWriter:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def write(self, dataframe, table):
        rows = [row.asDict(recursive=True) for row in dataframe.collect()]
        self.rows.setdefault(table, []).extend(rows)
        self.calls.append((table, len(rows)))


@unittest.skipUnless(importlib.util.find_spec("pyspark"), "PySpark runtime is not installed")
class QuizStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pyspark.sql import SparkSession
        python_environment = patch.dict(os.environ, {"PYSPARK_PYTHON": sys.executable, "SPARK_LOCAL_IP": "127.0.0.1"})
        python_environment.start()
        cls.addClassCleanup(python_environment.stop)
        cls.registry = compile_contracts(STD / "contracts")
        cls.spark = (SparkSession.builder.master("local[2]").appName("quiz-schema-unit-check")
                     .config("spark.ui.enabled", "false")
                     .config("spark.driver.host", "127.0.0.1")
                     .config("spark.driver.bindAddress", "127.0.0.1")
                     .config("spark.pyspark.python", sys.executable)
                     .config("spark.sql.session.timeZone", "UTC")
                     .getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.code = tempfile.TemporaryDirectory(prefix="quiz-stream-unit-")
        archive = Path(cls.code.name) / "spark_pipeline.zip"
        package_code(archive)
        cls.spark.sparkContext.addPyFile(str(archive))

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()
        cls.code.cleanup()

    def test_mixed_legacy_and_new_quiz_versions_map_once_and_isolate_invalid_choices(self):
        from sinker.contracts import ContractRegistry
        from sinker.dummy import load_cases
        from pyspark.sql.types import ArrayType, BinaryType, IntegerType, LongType, StringType, StructField, StructType

        raw_registry = ContractRegistry(STD / "contracts")
        case = next(item for item in load_cases(STD / "fixtures/raw_cases.jsonl")
                    if item["case"] == "success_quiz_answered")
        raw = json.loads(case["value"])
        contract, topic = raw_registry.select(raw["raw_manifest"]["event_type"],
                                             raw["raw_manifest"]["schema_version"], case["topic"])
        seed = raw_registry.standardize(raw, contract)
        inputs, expected = [], {}
        variants = (("1.0", None, False, True), ("1.1", "MULTIPLE_CHOICE", False, False),
                    ("1.1", "FILL_BLANK", True, True), ("1.1", "MULTIPLE_CHOICE", True, True),
                    ("1.1", "FILL_BLANK", False, False))
        for offset, (version, question_type, null_choice, correct) in enumerate(variants):
            data = dict(seed, event_uuid=str(uuid.uuid4()), is_correct=correct)
            if version == "1.1":
                data["question_type"] = question_type
            if null_choice:
                data["choice_uuid"] = None
            manifest = {"event_type": "QUIZ_ANSWERED", "std_schema_version": version, "status": "SUCCESS",
                        "processed_at": "2026-10-15T00:00:00.000Z", "parser_version": "1.1.0",
                        "fingerprint_algorithm": "xxh3_64", "fingerprint": fingerprint(data), "error_code": None}
            envelope = {"std_manifest": manifest, "std_data": data}
            headers = [{"key": "event_type", "value": b"QUIZ_ANSWERED"},
                       {"key": "std_schema_version", "value": version.encode()}]
            inputs.append((topic, data["user_uuid"].encode(), json.dumps(envelope).encode(), headers, 0, offset))
            if offset < 3:
                expected[uuid.UUID(data["event_uuid"]).hex] = {
                    "question_type": question_type or "MULTIPLE_CHOICE",
                    "choice_uuid": uuid.UUID(data["choice_uuid"]).hex if data["choice_uuid"] else None,
                    "is_correct": correct, "std_fingerprint": manifest["fingerprint"],
                }
        schema = StructType([
            StructField("topic", StringType()), StructField("key", BinaryType()), StructField("value", BinaryType()),
            StructField("headers", ArrayType(StructType([StructField("key", StringType()),
                                                        StructField("value", BinaryType())]))),
            StructField("partition", IntegerType()), StructField("offset", LongType()),
        ])
        writer = CapturingWriter()
        BatchProcessor(self.registry, SimpleNamespace(write_partitions=1), writer)(
            self.spark.createDataFrame(inputs, schema), 0)
        facts = writer.rows["quiz_attempt_fact"]
        self.assertEqual(len(facts), 3)
        self.assertEqual(len({row["event_uuid"] for row in facts}), 3)
        self.assertEqual(sorted(count for table, count in writer.calls if table == "quiz_attempt_fact"), [1, 2])
        for row in facts:
            self.assertEqual({name: row[name] for name in expected[row["event_uuid"]]}, expected[row["event_uuid"]])
        self.assertEqual(len(writer.rows[None]), 2)
        self.assertEqual({row["error_code"] for row in writer.rows[None]}, {"INVALID_VALUE"})
        self.assertEqual({row["__offset"] for row in writer.rows[None]}, {3, 4})
        self.assertFalse(envelope_schema(self.registry["schemas"]["QUIZ_ANSWERED|1.0"],
                                         self.registry["domains"])["std_data"].dataType["choice_uuid"].nullable)
        current = envelope_schema(self.registry["schemas"]["QUIZ_ANSWERED|1.1"], self.registry["domains"])
        self.assertTrue(current["std_data"].dataType["choice_uuid"].nullable)
        self.assertFalse(current["std_data"].dataType["question_type"].nullable)


if __name__ == "__main__":
    unittest.main()
