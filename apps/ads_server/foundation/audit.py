"""감사 로그 (위협 T23). 추가만 하고, 비밀값은 기록하지 않는다."""
import json
import re

from .net import client_ip

_SENSITIVE_KEY = re.compile(r"password|passwd|token|secret|api[_-]?key|(^|[_-])key($|[_-])|authorization|cookie|session", re.I)
_MAX_STRING = 500
_MAX_DETAIL_JSON = 4000


def redact_detail(value):
    """비밀로 보이는 키를 **제거**하고 긴 문자열을 자른다."""
    if isinstance(value, dict):
        return {k: redact_detail(v) for k, v in value.items() if not _SENSITIVE_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [redact_detail(v) for v in value]
    if isinstance(value, str):
        return value[:_MAX_STRING]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:_MAX_STRING]


def record_audit(request, action, target=None, detail=None, actor=None):
    """감사 로그 한 줄을 추가한다. request 는 None 일 수 있다(예: 요청 없는 신호)."""
    from .models import AuditLog

    user = actor
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            user = candidate
    cleaned = redact_detail(detail or {})
    if len(json.dumps(cleaned, ensure_ascii=False, default=str)) > _MAX_DETAIL_JSON:
        cleaned = {"truncated": True}
    target_type = target_id = ""
    if target is not None:
        if isinstance(target, tuple):
            target_type, target_id = target[0], str(target[1])
        else:
            target_type, target_id = target._meta.label_lower, str(target.pk)
    return AuditLog.objects.create(
        actor_id=getattr(user, "pk", None),
        actor_username=getattr(user, "username", "") or "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=cleaned,
        ip=(client_ip(request) if request is not None else "") or "",
        request_id=str(getattr(request, "request_id", "") or ""),
    )
