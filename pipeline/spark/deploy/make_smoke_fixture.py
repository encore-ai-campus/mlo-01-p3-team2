#!/usr/bin/env python3
"""Generate isolated Std inputs; this program never connects to a service."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
STD = ROOT.parent / "std_and_sinker"
sys.path[:0] = [str(ROOT), str(STD)]

from sinker.contracts import ContractRegistry
from sinker.dummy import load_cases
from spark_pipeline.contracts import COMMON_FACT_FIELDS, FACT_TABLES, compile_contracts, fact_defaults, validate_registry
from spark_pipeline.validation import canonical_bytes, fingerprint, utc_time, uuid4, validate_std


def make_fixture(output, topic, database, runtime_directory):
    if not re.fullmatch(r"spark_smoke_[A-Za-z0-9_-]{1,220}", topic):
        raise ValueError("Smoke topic must start with spark_smoke_ and contain only letters, numbers, _ and -")
    if not re.fullmatch(r"spark_smoke_[A-Za-z0-9_]{1,52}", database):
        raise ValueError("Smoke database must start with spark_smoke_ and be at most 64 characters")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    runtime_directory = Path(runtime_directory)
    if not runtime_directory.is_absolute():
        raise ValueError("Runtime directory must be absolute")
    raw_registry = ContractRegistry(STD / "contracts")
    registry = compile_contracts(STD / "contracts")
    registry["routes"] = {topic: sorted(registry["schemas"])}
    validate_registry(registry)
    randomized = {}
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    messages, rows = [], {table: [] for table in FACT_TABLES}
    cases = [case for case in load_cases(STD / "fixtures/raw_cases.jsonl")
             if case["case"].startswith("success_") and case["expected"] == "SUCCESS"]
    if len(cases) != 15:
        raise ValueError("Expected exactly 15 successful event-type fixtures")
    for case in cases:
        raw = json.loads(case["value"])
        contract, _ = raw_registry.select(raw["raw_manifest"]["event_type"],
                                          raw["raw_manifest"]["schema_version"], case["topic"])
        data = raw_registry.standardize(raw, contract)
        for name, value in data.items():
            if uuid4(value):
                data[name] = randomized.setdefault(value, str(uuid.uuid4()))
        data["occurred_at"] = now
        event = data["event_type"]
        manifest = {"event_type": event, "std_schema_version": "1.0", "status": "SUCCESS",
                    "processed_at": now, "parser_version": raw_registry.parser_version,
                    "fingerprint_algorithm": "xxh3_64", "fingerprint": fingerprint(data), "error_code": None}
        envelope = {"std_manifest": manifest, "std_data": data}
        message = {"case": case["case"], "topic": topic, "partition": 0, "offset": len(messages),
                   "key": data["user_uuid"], "headers": [
                       {"key": "event_type", "value": event}, {"key": "std_schema_version", "value": "1.0"}],
                   "value": canonical_bytes(envelope).decode(), "expected_error": None}
        messages.append(message)
        spec = registry["schemas"][event + "|1.0"]
        defaults = fact_defaults(spec)
        row = {name: defaults[name] if name in defaults else data.get(name)
               for name in COMMON_FACT_FIELDS + FACT_TABLES[spec["table"]]}
        for name, value in row.items():
            if name.endswith("_uuid") and value is not None:
                row[name] = value.replace("-", "")
            elif name == "occurred_at":
                row[name] = utc_time(value).isoformat(sep=" ", timespec="microseconds")
        row.update(parser_version=manifest["parser_version"],
                   parser_rank=registry["parser_versions"].index(manifest["parser_version"]),
                   std_fingerprint=manifest["fingerprint"])
        rows[spec["table"]].append(row)
    seed = next(message for message in messages if message["case"] == "success_post_read")
    duplicate = deepcopy(seed)
    duplicate.update(case="identical_redelivery", offset=len(messages))
    messages.append(duplicate)
    corrupted = deepcopy(seed)
    envelope = json.loads(corrupted["value"])
    envelope["std_data"]["event_uuid"] = str(uuid.uuid4())
    original = fingerprint(envelope["std_data"])
    envelope["std_manifest"]["fingerprint"] = ("0" if original[0] != "0" else "1") + original[1:]
    corrupted.update(case="bad_fingerprint", offset=len(messages), value=canonical_bytes(envelope).decode(),
                     expected_error="STD_CHECKSUM_MISMATCH")
    messages.append(corrupted)
    malformed = deepcopy(seed)
    malformed.update(case="malformed_json", offset=len(messages), value="{", expected_error="PARSE_ERROR")
    messages.append(malformed)
    errors = []
    for message in messages:
        headers = [{"key": item["key"], "value": item["value"].encode()} for item in message["headers"]]
        verdict = validate_std(topic, message["key"].encode(), message["value"].encode(), headers, registry)
        if verdict["error_code"] != message["expected_error"]:
            raise RuntimeError("Unexpected validation result for " + message["case"])
        if verdict["error_code"]:
            errors.append({"topic": topic, "partition": 0, "offset": message["offset"],
                           "event_uuid": verdict["event_uuid"].replace("-", "") if verdict["event_uuid"] else None,
                           "error_code": verdict["error_code"], "error_detail": verdict["error_detail"],
                           "source_reference": f"kafka://{topic}/0/{message['offset']}"})
    rows = {table: sorted(items, key=lambda item: item["event_uuid"]) for table, items in rows.items()}
    rows["stream_processing_error"] = errors
    counts = {table: len(items) for table, items in rows.items()}
    if sum(counts.values()) != 17 or len(messages) != 18:
        raise RuntimeError("Unexpected fixture cardinality")
    manifest = {"topic": topic, "partitions": 1, "database": database, "runtime_directory": str(runtime_directory),
                "message_count": 18, "unique_valid_event_count": 15, "expected_counts": counts,
                "validation_results": dict(Counter(message["expected_error"] or "SUCCESS" for message in messages)),
                "offset_assumption": "New, empty, single-partition topic; publish producer.lines exactly once"}
    for name, data in (("registry.json", registry), ("expected_rows.json", rows), ("manifest.json", manifest)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    (output / "records.jsonl").write_text("".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages))
    (output / "producer.lines").write_text("".join(
        ",".join(item["key"] + ":" + item["value"] for item in message["headers"]) + "\t" +
        message["key"] + "\t" + message["value"] + "\n" for message in messages))
    (output / "smoke.env.fragment").write_text(
        f"SPARK_INPUT_TOPICS={topic}\nMYSQL_DATABASE={database}\n"
        f"SPARK_REGISTRY_FILE={runtime_directory}/registry.json\n"
        f"SPARK_CHECKPOINT_LOCATION={runtime_directory}/checkpoint\nSPARK_STARTING_OFFSETS=earliest\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--runtime-directory", required=True)
    args = parser.parse_args()
    print(json.dumps(make_fixture(args.output, args.topic, args.database, args.runtime_directory), ensure_ascii=False))
