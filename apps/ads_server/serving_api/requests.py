"""C1 요청 본문 검증(계약 `DecisionRequest`). 계약의 규칙을 **여기 한 곳**에서 지킨다. 틀리면 400 `InvalidRequest`/`ForbiddenContextKey`."""
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from foundation.api import errors, json_depth

UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")  # 계약 `Uuid`(하이픈 36자만)
CONTEXT_MAX_BYTES, CONTEXT_MAX_DEPTH, CONTEXT_MAX_PROPERTIES = 4096, 4, 50
FORBIDDEN_CONTEXT_KEYS = frozenset({"login_id", "username", "password", "password_hash", "nickname", "email"})  # 직접 식별자(계약 `Context`)
_FIELDS = frozenset({"slot_id", "subject_id", "context"})


@dataclass(frozen=True)
class DecisionRequest:
    slot_id: uuid.UUID
    subject_id: str | None  # 가명 UUID(소문자 표기). 수집만 한다. 있어야 하는지는 슬롯 성격이 정한다(`records.decide`)
    context: dict


def _error(pointer, message):
    return {"pointer": pointer, "message": message}


def _uuid_field(body, name, problems):
    value = body.get(name)
    if name not in body:
        problems.append(_error(f"/{name}", "필수입니다."))
    elif not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        problems.append(_error(f"/{name}", "UUID(하이픈 포함 36자) 문자열이어야 합니다."))
    else:
        return uuid.UUID(value)
    return None


def _forbidden_keys(node):
    """어느 깊이에서든 직접 식별자 키를 찾는다(대소문자 무시)."""
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower() in FORBIDDEN_CONTEXT_KEYS:
                    yield key
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def validate_context(context):
    if not isinstance(context, dict):
        raise errors.InvalidRequest(errors=[_error("/context", "JSON 객체여야 합니다.")])
    if len(context) > CONTEXT_MAX_PROPERTIES:
        raise errors.InvalidRequest(errors=[_error("/context", f"속성은 최대 {CONTEXT_MAX_PROPERTIES}개입니다.")])
    if len(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > CONTEXT_MAX_BYTES:
        raise errors.InvalidRequest(errors=[_error("/context", f"직렬화 크기는 최대 {CONTEXT_MAX_BYTES} 바이트입니다.")])
    if json_depth(context) > CONTEXT_MAX_DEPTH:
        raise errors.InvalidRequest(errors=[_error("/context", f"중첩 깊이는 최대 {CONTEXT_MAX_DEPTH} 입니다.")])
    found = sorted(set(_forbidden_keys(context)))
    if found:
        raise errors.ForbiddenContextKey(errors=[_error("/context", f"직접 식별자 키는 허용하지 않습니다: {', '.join(found)}")])
    return context


def parse_decision_request(body):
    problems = [_error(f"/{key}", "알 수 없는 속성입니다.") for key in body if key not in _FIELDS]
    slot_id = _uuid_field(body, "slot_id", problems)
    subject = _uuid_field(body, "subject_id", problems) if "subject_id" in body else None  # 필수 여부는 슬롯 성격에 달려 있어 서비스가 판단한다
    if problems:
        raise errors.InvalidRequest(errors=problems)
    context = validate_context(body["context"]) if "context" in body else {}
    return DecisionRequest(slot_id=slot_id, subject_id=None if subject is None else str(subject), context=context)


# ---------------------------------------------------------------- 반응 (계약 `ReactionRequest`)

REACTION_TYPES = ("IMPRESSION", "CLICK", "CONVERSION")
# 계약 `DateTimeUtc`와 같은 문법: ASCII 숫자, 대문자 `T`·`Z`, 소수 초 1~6자리(마이크로초 — 저장·비교가 잃는 것 없이 다루는 한계)
_UTC_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?Z")
_REACTION_FIELDS = frozenset({"type", "occurred_at"})


@dataclass(frozen=True)
class ReactionRequest:
    type: str
    occurred_at: datetime


def parse_utc_time(value):
    """RFC 3339 UTC(`...Z`) 문자열을 시각으로. 형식이 틀리거나 없는 날짜면 `None`. 소수 초는 6자리까지만 받는다(절삭하지 않는다)."""
    match = _UTC_TIME.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), int((fraction or "").ljust(6, "0")), tzinfo=UTC)
    except ValueError:
        return None


def path_uuid(value, name):
    """경로의 UUID(계약 형식만). 틀리면 400 — 반응 PUT 은 404 를 선언하지 않는다."""
    if not UUID_PATTERN.fullmatch(value):
        raise errors.InvalidRequest(errors=[_error(f"path:{name}", "UUID(하이픈 포함 36자)여야 합니다.")])
    return uuid.UUID(value)


def parse_reaction_request(body):
    problems = [_error(f"/{key}", "알 수 없는 속성입니다.") for key in body if key not in _REACTION_FIELDS]
    if "type" not in body:
        problems.append(_error("/type", "필수입니다."))
    elif body["type"] not in REACTION_TYPES:
        problems.append(_error("/type", f"{', '.join(REACTION_TYPES)} 중 하나여야 합니다."))
    occurred = None
    if "occurred_at" not in body:
        problems.append(_error("/occurred_at", "필수입니다."))
    else:
        occurred = parse_utc_time(body["occurred_at"])
        if occurred is None:
            problems.append(_error("/occurred_at", "RFC 3339 UTC 시각(예: 2026-10-07T03:21:46Z)이어야 합니다."))
    if problems:
        raise errors.InvalidRequest(errors=problems)
    return ReactionRequest(type=body["type"], occurred_at=occurred)
