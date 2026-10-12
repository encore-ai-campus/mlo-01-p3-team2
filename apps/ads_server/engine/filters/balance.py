def check(candidate, effect, request):
    if effect.eligible and candidate.wallet_balance < effect.applied_amount:
        return "insufficient_balance"
    return None
