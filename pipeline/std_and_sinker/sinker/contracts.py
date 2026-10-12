import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .errors import DataError


def is_uuid4(value):
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except (ValueError, AttributeError):
        return False


def utc_string(value):
    if type(value) is not str or not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        raise ValueError("Invalid UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must be UTC")
    parsed = parsed.astimezone(timezone.utc)
    precision = "milliseconds" if parsed.microsecond % 1000 == 0 else "microseconds"
    return parsed.isoformat(timespec=precision).replace("+00:00", "Z")


class ContractRegistry:
    """Immutable files, loaded once. Topic routing is separate from event contracts."""

    def __init__(self, directory, routes_file=None):
        directory = Path(directory)
        self.words = self._read(directory / "standard_words.json")
        self.terms = self._read(directory / "standard_terms.json")
        self.domains = self._read(directory / "domains.json")
        self.common = self._read(directory / "common.json")
        self.routes = self._read(Path(routes_file) if routes_file else directory / "routes.json")
        self.parser_version = self.common["parser_version"]
        self.parser_versions = self.common["parser_versions"]
        if self.parser_version not in self.parser_versions:
            raise ValueError("parser_version missing from deployment order")
        self.contracts = {}
        for path in sorted((directory / "events").glob("*/*.json")):
            contract = self._read(path)
            key = (contract["event_type"], contract["schema_version"])
            if key in self.contracts:
                raise ValueError(f"Duplicate contract: {key}")
            self.contracts[key] = contract
            fields = self.common["data_fields"] + contract["fields"]
            for field in fields:
                if field["name"] not in self.terms:
                    raise ValueError(f"Unknown standard term: {field['name']}")
            names = [field["name"] for field in fields]
            if len(names) != len(set(names)):
                raise ValueError(f"Repeated field in contract: {key}")
            if contract["copy_fields"] != names:
                raise ValueError(f"copy_fields must match declared fields: {key}")
            if contract["constants"].get("event_type") != contract["event_type"].upper():
                raise ValueError(f"Invalid Std event_type constant: {key}")
            if set(contract["constants"]) - {"event_type", "action"}:
                raise ValueError(f"Unsupported constant field: {key}")
            if any(name not in names for name in contract.get("double_fields", [])):
                raise ValueError(f"Unknown DOUBLE field: {key}")
        if not self.contracts:
            raise ValueError("No event contracts found")
        for name, term in self.terms.items():
            if term["domain"] not in self.domains:
                raise ValueError(f"Unknown domain: {name}")
            if any(word not in self.words for word in term["words"]):
                raise ValueError(f"Unknown standard word: {name}")
        for route in self.routes.values():
            if not route.get("output_topic") or not route.get("event_types"):
                raise ValueError("Invalid route")
            if any(not any(key[0] == name for key in self.contracts) for name in route["event_types"]):
                raise ValueError("Route refers to unknown event")

    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def validate_topics(self, topics):
        for topic in topics:
            if topic not in self.routes:
                raise ValueError(f"No route registered for input topic: {topic}")

    def select(self, event_type, schema_version, topic):
        if type(event_type) is not str or type(schema_version) is not str:
            raise DataError("INVALID_VALUE", "raw_manifest event_type/schema_version")
        contract = self.contracts.get((event_type, schema_version))
        if contract is None:
            raise DataError("UNSUPPORTED_VERSION", "Unsupported event_type/schema_version")
        route = self.routes.get(topic)
        if route is None or event_type not in route["event_types"]:
            raise DataError("INVALID_VALUE", "Event not allowed on input topic")
        return contract, route["output_topic"]

    def validate_fields(self, obj, fields, prefix):
        if type(obj) is not dict:
            raise DataError("INVALID_VALUE", prefix)
        for field in fields:
            name = field["name"]
            location = f"{prefix}.{name}"
            if name not in obj:
                raise DataError("MISSING_FIELD", location)
            value = obj[name]
            if value is None and field.get("nullable", False):
                continue
            domain = self.domains[self.terms[name]["domain"]]
            kind = domain["type"]
            valid = False
            if kind == "uuid_v4":
                valid = is_uuid4(value)
            elif kind == "integer":
                valid = type(value) is int and -(2**63) <= value < 2**63
            elif kind == "boolean":
                valid = type(value) is bool
            elif kind == "number":
                try:
                    valid = type(value) in (int, float) and math.isfinite(float(value))
                except (OverflowError, ValueError):
                    valid = False
            elif kind == "string":
                valid = type(value) is str and bool(value)
                if valid and "pattern" in domain:
                    valid = re.fullmatch(domain["pattern"], value) is not None
            elif kind == "enum":
                valid = type(value) is str and value in domain["values"]
            elif kind == "utc_instant":
                try:
                    utc_string(value)
                    valid = True
                except (TypeError, ValueError, OverflowError):
                    valid = False
            if valid and "exclusive_minimum" in domain:
                valid = value > domain["exclusive_minimum"]
            if not valid:
                raise DataError("INVALID_VALUE", location)

    def standardize(self, envelope, contract):
        from .fingerprint import verify_fingerprint

        manifest, data = envelope.get("raw_manifest"), envelope.get("raw_data")
        self.validate_fields(manifest, self.common["manifest_fields"], "raw_manifest")
        verify_fingerprint(data, manifest)
        self.validate_fields(data, self.common["data_fields"] + contract["fields"], "raw_data")
        result = {
            "event_uuid": envelope["event_uuid"],
            "occurred_at": utc_string(manifest["occurred_at"]),
            **{name: data[name] for name in contract["copy_fields"]},
            **contract["constants"],
        }
        for name in contract.get("double_fields", []):
            result[name] = float(result[name])
        return result
