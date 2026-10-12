def check(candidate, effect, request):
    if effect.eligible and candidate.remaining_daily_budget < effect.applied_amount:
        return "budget_exhausted"
    return None
