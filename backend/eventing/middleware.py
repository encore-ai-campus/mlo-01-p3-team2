"""Attach a Raw user-session identity to existing authenticated browser sessions."""
from .events import ensure_platform_session


class PlatformSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        state = getattr(request, "campus_session_status", None)
        if (getattr(request, "user", None) is not None and request.user.is_authenticated and request.user.is_active
                and (state is None or state.get("authenticated"))):
            ensure_platform_session(request.user, request.session)
        return self.get_response(request)
