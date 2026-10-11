from functools import wraps
import json

from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache

from accounts.models import needs_profile_setup
from . import service


def api(method):
    def decorate(view):
        @never_cache
        @wraps(view)
        def wrapped(request):
            if not request.user.is_authenticated:
                return JsonResponse({"error": "다시 로그인해 주세요."}, status=401)
            if needs_profile_setup(request.user):
                return JsonResponse({"error": "닉네임과 캐릭터 설정을 먼저 완료해 주세요."}, status=403)
            if request.method != method:
                response = JsonResponse({"error": "지원하지 않는 요청입니다."}, status=405)
                response["Allow"] = method
                return response
            try:
                return view(request)
            except service.RaffleError as exc:
                return JsonResponse({"error": exc.message}, status=exc.status)
            except DatabaseError:
                return JsonResponse({"error": "이벤트 정보를 처리하지 못했어요. 잠시 후 다시 시도해 주세요."}, status=503)
        return wrapped
    return decorate


@api("GET")
def state(request):
    return JsonResponse(service.snapshot(request.user))


@api("POST")
def control(request):
    if not request.user.is_staff:
        raise service.RaffleError("관리자만 이벤트를 운영할 수 있어요.", 403)
    if request.content_type != "application/json":
        raise service.RaffleError("JSON 형식으로 요청해 주세요.", 415)
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > 4096:
            raise service.RaffleError("입력한 내용이 너무 깁니다.", 413)
        raw = request.body
        if len(raw) > 4096:
            raise service.RaffleError("입력한 내용이 너무 깁니다.", 413)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise service.RaffleError("요청 내용을 확인해 주세요.", 400)
    if "eventId" not in data or (data["eventId"] is not None and not isinstance(data["eventId"], str)):
        raise service.RaffleError("대상 이벤트를 확인해 주세요.", 400)
    action, title = data.get("action"), data.get("title")
    if not isinstance(action, str) or (title is not None and (not isinstance(title, str) or not 1 <= len(title.strip()) <= 100)):
        raise service.RaffleError("이벤트 이름은 1~100자로 입력해 주세요.", 400)
    times = {}
    for field, name in (("opensAt", "opens_at"), ("drawAt", "draw_at")):
        value = data.get(field)
        parsed = None
        if value is not None:
            try:
                parsed = parse_datetime(value) if isinstance(value, str) else None
            except ValueError:
                parsed = None
            if parsed is None or timezone.is_naive(parsed):
                raise service.RaffleError("시간대가 포함된 예약 시간을 입력해 주세요.", 400)
        times[name] = parsed
    service.control_event(action, data["eventId"], title=title.strip() if title else None, **times)
    return JsonResponse(service.snapshot(request.user))
