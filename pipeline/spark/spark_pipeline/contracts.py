import json
from pathlib import Path


FACT_TABLES = {
    "account_activity_fact": ["event_type", "end_reason"],
    "chat_activity_fact": ["message_uuid", "floor_uuid"],
    "post_activity_fact": ["post_uuid", "action", "revision", "zone_uuid"],
    "comment_activity_fact": ["comment_uuid", "post_uuid", "parent_comment_uuid", "action", "revision"],
    "content_activity_fact": ["content_uuid", "category_uuid", "domain", "content_kind", "action", "zone_uuid"],
    "quiz_attempt_fact": ["attempt_uuid", "question_uuid", "content_uuid", "question_type", "choice_uuid", "is_correct"],
    "movement_fact": ["floor_uuid", "zone_uuid", "x", "y", "input_kind"],
    "floor_transfer_fact": ["from_floor_uuid", "to_floor_uuid", "zone_uuid"],
    "point_grant_fact": ["ledger_uuid", "attempt_uuid", "delta", "balance_after"],
}
COMMON_FACT_FIELDS = ["event_uuid", "occurred_at", "user_uuid", "class_group_uuid", "session_uuid"]


def fact_defaults(spec):
    """Map fields absent from legacy Std without changing its fingerprinted data."""
    if spec["event_type"] == "SESSION_STARTED":
        return {"end_reason": None}
    if spec["event_type"] == "QUIZ_ANSWERED" and spec["version"] == "1.0":
        return {"question_type": "MULTIPLE_CHOICE"}
    return {}


def target_table(event):
    if event.startswith("SESSION_"):
        return "account_activity_fact"
    if event == "CHAT_SENT":
        return "chat_activity_fact"
    if event.startswith("POST_"):
        return "post_activity_fact"
    if event.startswith("COMMENT_"):
        return "comment_activity_fact"
    return {"CONTENT_OPEN_REQUESTED": "content_activity_fact", "QUIZ_ANSWERED": "quiz_attempt_fact",
            "MOVEMENT_OBSERVED": "movement_fact", "FLOOR_TRANSFERRED": "floor_transfer_fact",
            "POINT_GRANTED": "point_grant_fact"}[event]


def compile_contracts(source):
    """Build a self-contained Spark contract artifact; no runtime Sinker imports."""
    source = Path(source)
    terms = json.loads((source / "standard_terms.json").read_text())
    domains = json.loads((source / "domains.json").read_text())
    common = json.loads((source / "common.json").read_text())
    raw_routes = json.loads((source / "routes.json").read_text())
    result = {"parser_versions": common["parser_versions"], "domains": domains,
              "schemas": {}, "routes": {}, "fact_tables": FACT_TABLES}
    for path in sorted((source / "events").glob("*/*.json")):
        contract = json.loads(path.read_text())
        event = contract["constants"]["event_type"]
        key = f"{event}|{contract['std_schema_version']}"
        fields = [{"name": "event_uuid", "domain": "UUID_V4_JSON", "nullable": False},
                  {"name": "occurred_at", "domain": "UTC_INSTANT", "nullable": False}]
        for field in common["data_fields"] + contract["fields"]:
            name = field["name"]
            term = terms[name]
            fields.append({"name": name, "domain": term.get("std_domain", term["domain"]),
                           "nullable": field.get("nullable", False)})
        for name in contract["constants"]:
            if name not in {field["name"] for field in fields}:
                term = terms[name]
                fields.append({"name": name, "domain": term.get("std_domain", term["domain"]), "nullable": False})
        spec = {"event_type": event, "version": contract["std_schema_version"], "fields": fields,
                "constants": contract["constants"], "table": target_table(event)}
        if contract.get("conditional_rules"):
            spec["conditional_rules"] = contract["conditional_rules"]
        if key in result["schemas"] and result["schemas"][key] != spec:
            raise ValueError(f"Different contracts for the same Std version: {key}")
        result["schemas"][key] = spec
    for route in raw_routes.values():
        keys = [key for key, spec in result["schemas"].items()
                if spec["event_type"].lower() in route["event_types"]]
        result["routes"].setdefault(route["output_topic"], [])
        result["routes"][route["output_topic"]] = list(dict.fromkeys(result["routes"][route["output_topic"]] + keys))
    validate_registry(result)
    return result


def validate_registry(registry):
    if not registry["parser_versions"] or len(set(registry["parser_versions"])) != len(registry["parser_versions"]):
        raise ValueError("Invalid parser deployment order")
    for topic, keys in registry["routes"].items():
        if not topic or not keys or any(key not in registry["schemas"] for key in keys):
            raise ValueError("Invalid Std route")
    for key, spec in registry["schemas"].items():
        if key != f"{spec['event_type']}|{spec['version']}" or spec["table"] not in FACT_TABLES:
            raise ValueError("Invalid Std schema target")
        names = [field["name"] for field in spec["fields"]]
        if len(names) != len(set(names)) or any(field["domain"] not in registry["domains"] for field in spec["fields"]):
            raise ValueError("Invalid Std fields")
        needed = set(COMMON_FACT_FIELDS + FACT_TABLES[spec["table"]])
        needed.difference_update(fact_defaults(spec))
        if not needed.issubset(names):
            raise ValueError("Missing fact field in Std schema")
        rules = spec.get("conditional_rules", [])
        if type(rules) is not list:
            raise ValueError("Invalid Std conditional rules")
        for rule in rules:
            if (type(rule) is not dict or not {"when"}.issubset(rule)
                    or set(rule) - {"when", "not_null", "null"}
                    or type(rule["when"]) is not dict or not rule["when"]
                    or not set(rule["when"]).issubset(names)):
                raise ValueError("Invalid Std conditional rule")
            constrained = []
            for operation in ("not_null", "null"):
                fields = rule.get(operation, [])
                if (type(fields) is not list or any(type(name) is not str for name in fields)
                        or len(set(fields)) != len(fields) or not set(fields).issubset(names)):
                    raise ValueError("Invalid Std conditional field")
                constrained.extend(fields)
            if not constrained or len(set(constrained)) != len(constrained):
                raise ValueError("Invalid Std conditional constraints")


def load_registry(path):
    registry = json.loads(Path(path).read_text())
    validate_registry(registry)
    return registry


def envelope_schema(spec, domains):
    from pyspark.sql.types import BooleanType, DoubleType, LongType, StringType, StructField, StructType
    kinds = {"integer": LongType(), "number": DoubleType(), "boolean": BooleanType()}
    data = StructType([StructField(field["name"], kinds.get(domains[field["domain"]]["type"], StringType()),
                                  field["nullable"]) for field in spec["fields"]])
    manifest = StructType([StructField(name, StringType(), name == "error_code") for name in (
        "event_type", "std_schema_version", "status", "processed_at", "parser_version",
        "fingerprint_algorithm", "fingerprint", "error_code")])
    return StructType([StructField("std_manifest", manifest), StructField("std_data", data)])
