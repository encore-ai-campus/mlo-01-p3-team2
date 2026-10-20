from ..pricing import is_expired


def check(candidate, effect, request):
    if candidate.period_start > request.now:
        return "not_started"
    if is_expired(candidate.period_end, request.now):
        return "expired"
    return None
