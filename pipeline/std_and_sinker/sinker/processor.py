import json
from dataclasses import dataclass

from bson import BSON
from bson.errors import InvalidDocument

from .contracts import is_uuid4
from .errors import DataError
from .fingerprint import fingerprint
from .mongo import now


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("Non-finite JSON constant")


@dataclass(frozen=True)
class Record:
    topic: str
    partition: int
    offset: int
    value: bytes | None
    key: bytes | None
    timestamp: int | None = None
    headers: list | None = None

    def origin(self):
        return {
            "topic": self.topic, "partition": self.partition, "offset": self.offset,
            "timestamp": self.timestamp, "key": self.key,
            "headers": [{"key": key, "value": value} for key, value in (self.headers or [])],
        }


@dataclass(frozen=True)
class Outcome:
    status: str
    event_uuid: str | None = None
    error_code: str | None = None


class Processor:
    """No offset operations here: return only after all required writes/ACKs."""

    def __init__(self, registry, sink, publisher):
        self.registry = registry
        self.sink = sink
        self.publisher = publisher

    def handle(self, record):
        origin = record.origin()
        try:
            envelope = json.loads(
                record.value, object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
            if type(envelope) is not dict or not is_uuid4(envelope.get("event_uuid")):
                raise ValueError("Invalid event identifier")
            # Reject input MongoDB cannot represent; preserve its bytes separately.
            BSON.encode(envelope)
        except (ValueError, TypeError, UnicodeError, OverflowError, InvalidDocument):
            self.sink.store_receipt(
                "raw_wrong_receipts", origin, record.value, "PARSE_ERROR",
                "Invalid JSON, event_uuid, or BSON representation",
            )
            return Outcome("WRONG", error_code="PARSE_ERROR")
        identifier = envelope["event_uuid"]
        if not self.sink.store_raw(envelope, origin):
            self.sink.store_receipt(
                "raw_conflict_receipts", origin, record.value, "EVENT_UUID_CONFLICT",
                "Different Raw envelope for the same event_uuid", envelope,
            )
            return Outcome("CONFLICT", identifier, "EVENT_UUID_CONFLICT")
        contract = None
        output_topic = None
        data = None
        error = None
        try:
            manifest = envelope.get("raw_manifest")
            if type(manifest) is not dict:
                raise DataError("INVALID_VALUE", "raw_manifest")
            for field in ("event_type", "schema_version"):
                if field not in manifest:
                    raise DataError("MISSING_FIELD", f"raw_manifest.{field}")
            contract, output_topic = self.registry.select(
                manifest["event_type"], manifest["schema_version"], record.topic,
            )
            data = self.registry.standardize(envelope, contract)
            if record.key != data["user_uuid"].encode("utf-8"):
                raise DataError("INVALID_VALUE", "Kafka key must equal user_uuid")
        except DataError as caught:
            error = caught
        manifest = envelope.get("raw_manifest")
        event_type = manifest.get("event_type") if type(manifest) is dict else None
        document = {
            "_id": identifier,
            "std_manifest": {
                "event_type": event_type.upper() if type(event_type) is str else None,
                "std_schema_version": contract["std_schema_version"] if contract else None,
                "status": "FAIL" if error else "SUCCESS",
                "processed_at": now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "parser_version": self.registry.parser_version,
                "fingerprint_algorithm": "xxh3_64",
                "fingerprint": None if error else fingerprint(data),
                "error_code": error.code if error else None,
            },
            "std_data": None if error else data,
            "error_detail": error.detail if error else None,
        }
        stored = self.sink.store_std(document)
        if stored["std_manifest"]["status"] == "SUCCESS":
            if output_topic is None:
                raise RuntimeError("Successful stored result has no output route")
            self.publisher.publish(
                output_topic, stored["std_data"]["user_uuid"],
                {"std_manifest": stored["std_manifest"], "std_data": stored["std_data"]},
            )
        return Outcome(stored["std_manifest"]["status"], identifier, stored["std_manifest"]["error_code"])
