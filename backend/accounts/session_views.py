from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .session_policy import check_session, invalid_status


def response(request, *, touch=False):
    if not request.user.is_authenticated:
        state = getattr(request, "campus_session_status", invalid_status())
        return JsonResponse({**state, "authenticated": False}, status=401)
    state = check_session(request.session.session_key, touch=touch, force=touch)
    return JsonResponse(state, status=503 if state.get("reason") == "retry" else 200 if state["authenticated"] else 401)


@never_cache
@require_GET
def session_status(request):
    return response(request)


@never_cache
@require_POST
def session_activity(request):
    return response(request, touch=True)
