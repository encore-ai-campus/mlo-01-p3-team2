"""HTTP 계층 도우미 (설계 §3, 위협 T9~T14).

- parse_json: 본문 크기·깊이 제한, NaN/Infinity·중복 키 거부, 최상위는 객체. 실패는 모두 ApiError → 4xx.
- 오류 응답: `/api/` 는 application/problem+json, 그 외는 HTML. **입력 오류는 500 이 되지 않고 내부 정보를 싣지 않는다.**
"""
import json
import math
import re

from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string

from .errors import (
    ApiError, Forbidden, InvalidRequest, NotFound, PayloadTooLarge, Unavailable, UnsupportedMediaType,
)

API_PREFIX = "/api/"
DEFAULT_MAX_BYTES = 16 * 1024  # 계약: 요청 본문 최대 16 KiB
DEFAULT_MAX_DEPTH = 8
_JSON_CT = re.compile(r"^application/json\s*(;.*)?$", re.IGNORECASE)


def is_api_path(path):
    return path.startswith(API_PREFIX)


# ---------- JSON 파싱 ----------

def _reject_constant(name):
    raise ValueError(f"허용하지 않는 값: {name}")  # NaN, Infinity, -Infinity


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):  # 1e999999 같은 값
        raise ValueError("유한하지 않은 수")
    return value


def _no_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"중복 키: {key}")
        seen[key] = value
    return seen


def json_depth(value):
    """JSON 값의 중첩 깊이(객체·배열만 센다). 다른 입력 검증(예: C1 context 의 깊이 제한)도 같은 기준을 쓴다."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, (dict, list)):
            deepest = max(deepest, depth)
            children = node.values() if isinstance(node, dict) else node
            stack.extend((child, depth + 1) for child in children)
    return deepest


def _has_unpaired_surrogate(value):
    """키와 값 모두, 어느 깊이에서든. JSON 이스케이프(`\\ud800`)는 문법상 유효해 디코더가 받지만 UTF-8 로 저장·전송할 수 없다."""
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def parse_json(request, max_bytes=DEFAULT_MAX_BYTES, max_depth=DEFAULT_MAX_DEPTH):
    """요청 본문을 JSON 객체(dict)로 읽는다. 실패하면 ApiError(4xx)."""
    if not _JSON_CT.match(request.META.get("CONTENT_TYPE", "")):
        raise UnsupportedMediaType("Content-Type 은 application/json 이어야 합니다.")
    declared = request.META.get("CONTENT_LENGTH")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise PayloadTooLarge(f"요청 본문은 최대 {max_bytes} 바이트입니다.")
        except ValueError:
            raise InvalidRequest("Content-Length 가 올바르지 않습니다.")
    raw = request.read(max_bytes + 1)  # 한도 + 1 바이트까지만 읽는다(전부 읽지 않는다)
    if len(raw) > max_bytes:
        raise PayloadTooLarge(f"요청 본문은 최대 {max_bytes} 바이트입니다.")
    if not raw:
        raise InvalidRequest("본문이 비어 있습니다.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidRequest("본문은 UTF-8 이어야 합니다.")
    try:
        value = json.loads(
            text, parse_constant=_reject_constant, parse_float=_parse_float, object_pairs_hook=_no_duplicate_keys
        )
    except (ValueError, RecursionError):
        raise InvalidRequest("JSON 형식이 올바르지 않습니다.")
    if not isinstance(value, dict):
        raise InvalidRequest("최상위는 JSON 객체여야 합니다.")
    if _has_unpaired_surrogate(value):
        raise InvalidRequest("유효하지 않은 유니코드(짝 없는 서로게이트)가 있습니다.")
    if json_depth(value) > max_depth:
        raise InvalidRequest(f"중첩 깊이는 최대 {max_depth} 입니다.")
    return value


# ---------- 오류 응답 ----------

def problem_response(request, error):
    """ApiError → application/problem+json. 내부 정보(스택트레이스·SQL)는 싣지 않는다."""
    body = {
        "type": f"/problems/{error.code}",
        "title": error.title,
        "status": error.status,
        "code": error.code,
    }
    if error.detail and error.detail != error.title:
        body["detail"] = error.detail
    request_id = getattr(request, "request_id", None)
    if request_id:
        body["request_id"] = str(request_id)
    if error.errors:
        body["errors"] = error.errors
    response = JsonResponse(body, status=error.status, content_type="application/problem+json")
    retry_after = error.retry_after if error.retry_after is not None else (1 if error.status in (429, 503) else None)
    if retry_after is not None:  # 계약: 429·503 은 Retry-After 를 항상 보낸다
        response["Retry-After"] = str(max(0, int(retry_after)))
    for name, value in error.headers.items():
        response[name] = value
    return response


def _html_error(status, title, message):
    html = render_to_string("foundation/error.html", {"status": status, "title": title, "message": message})
    return HttpResponse(html, status=status)


def _respond(request, error, message):
    if is_api_path(request.path):
        return problem_response(request, error)
    return _html_error(error.status, error.title, message)


def bad_request(request, exception=None):
    return _respond(request, InvalidRequest(), "요청을 처리할 수 없습니다.")


def permission_denied(request, exception=None):
    return _respond(request, Forbidden(), "이 화면에 접근할 권한이 없습니다.")


def not_found(request, exception=None):
    return _respond(request, NotFound(), "요청한 페이지를 찾을 수 없습니다.")


def server_error(request):
    return _respond(request, ApiError(), "잠시 후 다시 시도해 주세요.")


def transient_db_error(request):
    """교착·잠금 대기 초과(MySQL 1213·1205)가 뷰 밖으로 나왔을 때: 500 대신 503 + `Retry-After`. 이 두 오류는 서버가 그 트랜잭션을 되돌린 것이라
    같은 요청을 다시 보내면 된다(`is_transient_lock_error`). 커밋 결과가 불명확한 오류(연결 끊김 등)·다른 오류는 여기 오지 않는다(외부 검토 7936ac7)."""
    response = _respond(request, Unavailable(retry_after=1), "잠시 혼잡해 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
    response["Retry-After"] = "1"
    return response


def csrf_failure(request, reason=""):
    return _respond(request, Forbidden(), "요청을 확인할 수 없습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.")
