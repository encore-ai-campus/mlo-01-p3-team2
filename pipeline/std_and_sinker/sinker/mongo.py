from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timezone

from bson import Binary
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from .errors import ResultConflict
from .fingerprint import canonical_bytes


def now():
    return datetime.now(timezone.utc)


def logical_result(document):
    result = deepcopy(document)
    result["std_manifest"].pop("processed_at", None)
    return result


class MongoSink:
    def __init__(self, uri, database, parser_versions):
        self.client = MongoClient(
            uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
            socketTimeoutMS=10000, tz_aware=True,
        )
        try:
            self.client.admin.command("ping")
            self.db = self.client.get_database(database, write_concern=WriteConcern(w="majority"))
        except BaseException:
            with suppress(Exception):
                self.client.close()
            raise
        self.parser_versions = parser_versions

    def store_raw(self, envelope, origin):
        document = {
            "_id": envelope["event_uuid"],
            "raw_manifest": envelope.get("raw_manifest"),
            "raw_data": envelope.get("raw_data"),
            "ingested_at": now(), "kafka_origin": origin,
        }
        try:
            stored = self.db.raw_logs.find_one_and_update(
                {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            stored = self.db.raw_logs.find_one({"_id": document["_id"]})
            if stored is None:
                raise
        # JSON key order is ignored, but int/float/bool differences are preserved.
        original = {"raw_manifest": stored["raw_manifest"], "raw_data": stored["raw_data"]}
        incoming = {"raw_manifest": document["raw_manifest"], "raw_data": document["raw_data"]}
        return canonical_bytes(original) == canonical_bytes(incoming)

    def store_receipt(self, kind, origin, value, code, detail, envelope=None):
        collection = self.db[kind]
        document = {
            "_id": f"{origin['topic']}:{origin['partition']}:{origin['offset']}",
            "kafka_origin": origin, "received_at": now(),
            "error_code": code, "error_detail": detail,
            "raw_bytes": Binary(value or b""),
        }
        if envelope is not None:
            document["event_uuid"] = envelope["event_uuid"]
            document["raw_manifest"] = envelope.get("raw_manifest")
            document["raw_data"] = envelope.get("raw_data")
        collection.update_one({"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True)

    def store_std(self, document):
        """Keep prior results; newer deployed parsers may recover FAIL to SUCCESS."""
        identifier = document["_id"]
        for _ in range(5):
            existing = self.db.std_logs.find_one({"_id": identifier})
            if existing is None:
                try:
                    self.db.std_logs.insert_one(deepcopy(document))
                    return document
                except DuplicateKeyError:
                    continue
            old_version = existing["std_manifest"]["parser_version"]
            new_version = document["std_manifest"]["parser_version"]
            if old_version not in self.parser_versions or new_version not in self.parser_versions:
                raise ResultConflict("Unknown parser deployment order")
            old_rank = self.parser_versions.index(old_version)
            new_rank = self.parser_versions.index(new_version)
            if new_rank < old_rank:
                return existing
            if new_rank == old_rank:
                if canonical_bytes(logical_result(existing)) != canonical_bytes(logical_result(document)):
                    raise ResultConflict("Different result from the same parser version")
                return existing
            # DRD explicitly permits a new parser to recover a failed result.
            # Other cross-version replacements require a separate contract.
            if not (
                existing["std_manifest"]["status"] == "FAIL"
                and document["std_manifest"]["status"] == "SUCCESS"
            ):
                return existing
            replaced = self.db.std_logs.replace_one(existing, deepcopy(document))
            if replaced.matched_count:
                return document
        raise ResultConflict("Concurrent Std result updates")

    def close(self):
        self.client.close()
