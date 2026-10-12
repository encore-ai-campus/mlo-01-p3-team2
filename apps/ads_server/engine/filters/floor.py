def check(candidate, effect, request):
    return None if effect.eligible else "below_floor"
