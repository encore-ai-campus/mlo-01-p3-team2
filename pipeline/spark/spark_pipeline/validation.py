"""Validate original JSON before Spark can coerce or discard any fields."""
import json
import math
import re
import uuid
from datetime import datetime, timezone

import xxhash


class InvalidStd(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def fingerprint(value):
    return xxhash.xxh3_64_hexdigest(canonical_bytes(value))


def uuid4(value):
    try:
        return type(value) is str and uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def utc_time(value):
    if type(value) is not str or not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        raise ValueError("UTC instant")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC instant")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError("Non-finite JSON")


def decode_headers(headers):
    selected = {}
    for header in headers or []:
        name, value = header["key"], header["value"]
        if name not in ("event_type", "std_schema_version"):
            continue
        if name in selected or value is None:
            raise InvalidStd("INVALID_HEADER", "Missing or repeated Std header")
        try:
            selected[name] = bytes(value).decode("utf-8", errors="strict")
        except (ValueError, TypeError, UnicodeError):
            raise InvalidStd("INVALID_HEADER", "Invalid UTF-8 Std header") from None
    if set(selected) != {"event_type", "std_schema_version"} or not all(selected.values()):
        raise InvalidStd("INVALID_HEADER", "Missing Std header")
    return selected


def valid_domain(value, domain):
    kind = domain["type"]
    if kind == "uuid_v4":
        valid = uuid4(value)
    elif kind == "integer":
        valid = type(value) is int and -(2**63) <= value < 2**63
    elif kind == "number":
        try:
            valid = type(value) in (int, float) and math.isfinite(float(value))
        except (ValueError, OverflowError):
            valid = False
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind == "enum":
        valid = type(value) is str and value in domain["values"]
    elif kind == "string":
        valid = type(value) is str and bool(value)
        if valid and "pattern" in domain:
            valid = re.fullmatch(domain["pattern"], value) is not None
    elif kind == "utc_instant":
        try:
            utc_time(value)
            valid = True
        except (ValueError, TypeError, OverflowError):
            valid = False
    else:
        valid = False
    return valid and ("exclusive_minimum" not in domain or value > domain["exclusive_minimum"])


def validate_std(topic, key, value, headers, registry):
    identifier = None
    event, version, table = None, None, None
    try:
        selected = decode_headers(headers)
        event, version = selected["event_type"], selected["std_schema_version"]
        schema_key = f"{event}|{version}"
        if schema_key not in registry["routes"].get(topic, []):
            raise InvalidStd("UNSUPPORTED_SCHEMA", "Unsupported topic/event_type/std_schema_version")
        spec = registry["schemas"][schema_key]
        table = spec["table"]
        try:
            text = bytes(value).decode("utf-8", errors="strict")
            envelope = json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        except (ValueError, TypeError, UnicodeError):
            raise InvalidStd("PARSE_ERROR", "Invalid Std JSON") from None
        if type(envelope) is not dict or set(envelope) != {"std_manifest", "std_data"}:
            raise InvalidStd("INVALID_VALUE", "Std envelope fields")
        manifest, data = envelope["std_manifest"], envelope["std_data"]
        if type(manifest) is not dict or type(data) is not dict:
            raise InvalidStd("INVALID_VALUE", "Std manifest/data object")
        if uuid4(data.get("event_uuid")):
            identifier = data["event_uuid"]
        manifest_fields = {"event_type", "std_schema_version", "status", "processed_at", "parser_version",
                           "fingerprint_algorithm", "fingerprint", "error_code"}
        if manifest_fields - set(manifest):
            raise InvalidStd("MISSING_FIELD", "std_manifest fields")
        if set(manifest) - manifest_fields:
            raise InvalidStd("INVALID_VALUE", "Unknown std_manifest field")
        if manifest["event_type"] != event or manifest["std_schema_version"] != version:
            raise InvalidStd("HEADER_BODY_MISMATCH", "Std header/manifest mismatch")
        if manifest["status"] != "SUCCESS" or manifest["error_code"] is not None:
            raise InvalidStd("INVALID_VALUE", "Only SUCCESS Std input is accepted")
        if manifest["parser_version"] not in registry["parser_versions"]:
            raise InvalidStd("UNSUPPORTED_PARSER", "Unknown parser deployment version")
        if not valid_domain(manifest["processed_at"], registry["domains"]["UTC_INSTANT"]):
            raise InvalidStd("INVALID_VALUE", "std_manifest.processed_at")
        if manifest["fingerprint_algorithm"] != "xxh3_64":
            raise InvalidStd("INVALID_VALUE", "std_manifest.fingerprint_algorithm")
        if not valid_domain(manifest["fingerprint"], registry["domains"]["FINGERPRINT"]):
            raise InvalidStd("INVALID_VALUE", "std_manifest.fingerprint")
        try:
            actual = fingerprint(data)
        except (ValueError, TypeError, UnicodeError, OverflowError):
            raise InvalidStd("INVALID_VALUE", "std_data canonical JSON") from None
        if actual != manifest["fingerprint"]:
            raise InvalidStd("STD_CHECKSUM_MISMATCH", "std_data fingerprint mismatch")
        names = {field["name"] for field in spec["fields"]}
        if names - set(data):
            raise InvalidStd("MISSING_FIELD", "std_data required field")
        if set(data) - names:
            raise InvalidStd("INVALID_VALUE", "Unknown std_data field")
        for field in spec["fields"]:
            current = data[field["name"]]
            if current is None and field["nullable"]:
                continue
            if not valid_domain(current, registry["domains"][field["domain"]]):
                raise InvalidStd("INVALID_VALUE", "std_data." + field["name"])
        for rule in spec.get("conditional_rules", []):
            if all(data[name] == expected for name, expected in rule["when"].items()):
                for name in rule.get("not_null", []):
                    if data[name] is None:
                        raise InvalidStd("INVALID_VALUE", "std_data." + name)
                for name in rule.get("null", []):
                    if data[name] is not None:
                        raise InvalidStd("INVALID_VALUE", "std_data." + name)
        for name, expected in spec["constants"].items():
            if data.get(name) != expected:
                raise InvalidStd("INVALID_VALUE", "std_data." + name)
        if key is None or bytes(key) != data["user_uuid"].encode("utf-8"):
            raise InvalidStd("KEY_MISMATCH", "Kafka key must equal std_data.user_uuid")
        return {"event_type": event, "version": version, "table": table, "event_uuid": identifier,
                "error_code": None, "error_detail": None}
    except InvalidStd as error:
        return {"event_type": event, "version": version, "table": table, "event_uuid": identifier,
                "error_code": error.code, "error_detail": error.detail}


def source_reference(topic, partition, offset):
    return f"kafka://{topic}/{partition}/{offset}"
