"""C1 요청 본문 검증(계약 `DecisionRequest`). 계약의 규칙을 **여기 한 곳**에서 지킨다. 틀리면 400 `InvalidRequest`/`ForbiddenContextKey`."""
import json
import re
import uuid
from dataclasses import dataclass

from foundation.api import errors, json_depth

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")  # 계약 `Uuid`(하이픈 36자만)
CONTEXT_MAX_BYTES, CONTEXT_MAX_DEPTH, CONTEXT_MAX_PROPERTIES = 4096, 4, 50
FORBIDDEN_CONTEXT_KEYS = frozenset({"login_id", "username", "password", "password_hash", "nickname", "email"})  # 직접 식별자(계약 `Context`)
_FIELDS = frozenset({"slot_id", "subject_id", "context"})


@dataclass(frozen=True)
class DecisionRequest:
    slot_id: uuid.UUID
    subject_id: str  # 가명 UUID(소문자 표기). 수집만 한다
    context: dict


def _error(pointer, message):
    return {"pointer": pointer, "message": message}


def _uuid_field(body, name, problems):
    value = body.get(name)
    if name not in body:
        problems.append(_error(f"/{name}", "필수입니다."))
    elif not isinstance(value, str) or not _UUID.fullmatch(value):
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
    subject = _uuid_field(body, "subject_id", problems)
    if problems:
        raise errors.InvalidRequest(errors=problems)
    context = validate_context(body["context"]) if "context" in body else {}
    return DecisionRequest(slot_id=slot_id, subject_id=str(subject), context=context)
