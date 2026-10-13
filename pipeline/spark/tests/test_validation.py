import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STD = ROOT.parent / "std_and_sinker"
sys.path.insert(0, str(STD))

from sinker.contracts import ContractRegistry
from sinker.dummy import load_cases
from spark_pipeline.contracts import compile_contracts, load_registry
from spark_pipeline.validation import canonical_bytes, fingerprint, validate_std


def std_message(case, raw_registry):
    raw = json.loads(case["value"])
    contract, topic = raw_registry.select(raw["raw_manifest"]["event_type"], raw["raw_manifest"]["schema_version"], case["topic"])
    data = raw_registry.standardize(raw, contract)
    return {"topic": topic, "key": case["key"].encode(),
            "envelope": {"std_manifest": {"event_type": data["event_type"], "std_schema_version": "1.0",
                "status": "SUCCESS", "processed_at": "2026-10-11T00:00:00.000Z", "parser_version": "1.0.0",
                "fingerprint_algorithm": "xxh3_64", "fingerprint": fingerprint(data), "error_code": None},
                "std_data": data},
            "headers": [{"key": "event_type", "value": data["event_type"].encode()},
                        {"key": "std_schema_version", "value": b"1.0"}]}


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = compile_contracts(STD / "contracts")
        raw = ContractRegistry(STD / "contracts")
        cls.messages = {case["case"]: std_message(case, raw)
                        for case in load_cases(STD / "fixtures/raw_cases.jsonl") if case["expected"] == "SUCCESS"}

    def check_message(self, message):
        return validate_std(message["topic"], message["key"], json.dumps(message["envelope"]).encode(),
                            message["headers"], self.registry)

    def test_all_fifteen_events_map_to_nine_tables(self):
        outcomes = [self.check_message(message) for message in self.messages.values()]
        self.assertTrue(all(outcome["error_code"] is None for outcome in outcomes))
        self.assertEqual(len({outcome["event_type"] for outcome in outcomes}), 15)
        self.assertEqual(len({outcome["table"] for outcome in outcomes}), 9)

    def test_committed_contract_artifact_matches_upstream(self):
        self.assertEqual(load_registry(ROOT / "contracts/registry.json"), self.registry)

    def test_missing_duplicate_and_invalid_utf8_headers(self):
        for headers in ([], [{"key": "event_type", "value": b"CHAT_SENT"}],
                        [{"key": "event_type", "value": b"CHAT_SENT"}] * 2,
                        [{"key": "event_type", "value": b"\xff"}, {"key": "std_schema_version", "value": b"1.0"}]):
            message = deepcopy(self.messages["success_chat_sent"])
            message["headers"] = headers
            self.assertEqual(self.check_message(message)["error_code"], "INVALID_HEADER")

    def test_topic_and_version_are_selected_before_body_parsing(self):
        message = self.messages["success_chat_sent"]
        self.assertEqual(validate_std("standardized.account", message["key"], b"not-json", message["headers"], self.registry)["error_code"], "UNSUPPORTED_SCHEMA")
        headers = [{"key": "event_type", "value": b"CHAT_SENT"}, {"key": "std_schema_version", "value": b"9.0"}]
        self.assertEqual(validate_std(message["topic"], message["key"], b"not-json", headers, self.registry)["error_code"], "UNSUPPORTED_SCHEMA")

    def test_malformed_json_duplicate_keys_and_nonfinite(self):
        message = self.messages["success_chat_sent"]
        for value in (None, b"{", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"):
            self.assertEqual(validate_std(message["topic"], message["key"], value, message["headers"], self.registry)["error_code"], "PARSE_ERROR")

    def test_fingerprint_checked_on_original_numbers(self):
        message = deepcopy(self.messages["success_movement_observed"])
        message["envelope"]["std_data"]["x"] = 123.5
        self.assertEqual(self.check_message(message)["error_code"], "STD_CHECKSUM_MISMATCH")
        self.assertNotEqual(fingerprint({"x": 1}), fingerprint({"x": 1.0}))

    def test_strict_integer_boolean_and_numeric_types(self):
        for case, name, values in (
            ("success_post_read", "revision", ["3", 3.0, True, 2**63]),
            ("success_quiz_answered", "is_correct", ["true", 1, 0]),
            ("success_movement_observed", "x", ["1.5", True]),
        ):
            for value in values:
                message = deepcopy(self.messages[case])
                message["envelope"]["std_data"][name] = value
                message["envelope"]["std_manifest"]["fingerprint"] = fingerprint(message["envelope"]["std_data"])
                self.assertEqual(self.check_message(message)["error_code"], "INVALID_VALUE")

    def test_required_missing_and_nullable_are_different(self):
        message = deepcopy(self.messages["success_chat_sent"])
        message["envelope"]["std_data"]["floor_uuid"] = None
        message["envelope"]["std_manifest"]["fingerprint"] = fingerprint(message["envelope"]["std_data"])
        self.assertIsNone(self.check_message(message)["error_code"])
        del message["envelope"]["std_data"]["floor_uuid"]
        message["envelope"]["std_manifest"]["fingerprint"] = fingerprint(message["envelope"]["std_data"])
        self.assertEqual(self.check_message(message)["error_code"], "MISSING_FIELD")

    def test_header_body_key_and_success_status(self):
        for field, value, expected in (
            ("event_type", "POST_READ", "HEADER_BODY_MISMATCH"),
            ("status", "FAIL", "INVALID_VALUE"),
            ("parser_version", "2.0.0", "UNSUPPORTED_PARSER"),
            ("processed_at", "2026-10-11T09:00:00+09:00", "INVALID_VALUE"),
        ):
            message = deepcopy(self.messages["success_chat_sent"])
            message["envelope"]["std_manifest"][field] = value
            self.assertEqual(self.check_message(message)["error_code"], expected)
        message = deepcopy(self.messages["success_chat_sent"])
        message["key"] = b"other-user"
        self.assertEqual(self.check_message(message)["error_code"], "KEY_MISMATCH")

    def test_std_constants_uuid_and_extra_fields(self):
        for name, value in (("action", "DELETE"), ("event_uuid", "not-a-uuid"), ("extra", "unused")):
            message = deepcopy(self.messages["success_post_read"])
            message["envelope"]["std_data"][name] = value
            message["envelope"]["std_manifest"]["fingerprint"] = fingerprint(message["envelope"]["std_data"])
            self.assertEqual(self.check_message(message)["error_code"], "INVALID_VALUE")

    def test_shared_fingerprint_vectors(self):
        vectors = json.loads((STD / "contracts/fingerprint_vectors.json").read_text())
        for vector in vectors:
            self.assertEqual(canonical_bytes(vector["data"]).decode(), vector["canonical_json"])
            self.assertEqual(fingerprint(vector["data"]), vector["xxh3_64"])


if __name__ == "__main__":
    unittest.main()
