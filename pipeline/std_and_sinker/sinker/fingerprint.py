import json

import xxhash

from .errors import DataError


def canonical_bytes(value):
    """UTF-8, sorted keys, no whitespace; preserve JSON numeric types."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(value):
    return xxhash.xxh3_64_hexdigest(canonical_bytes(value))


def verify_fingerprint(raw_data, manifest):
    if manifest.get("fingerprint_algorithm") != "xxh3_64":
        raise DataError("INVALID_VALUE", "raw_manifest.fingerprint_algorithm")
    try:
        actual = fingerprint(raw_data)
    except (TypeError, ValueError, UnicodeError, OverflowError) as error:
        raise DataError("INVALID_VALUE", "raw_data canonical JSON") from error
    if actual != manifest.get("fingerprint"):
        raise DataError("RAW_CHECKSUM_MISMATCH", "raw_data fingerprint mismatch")
