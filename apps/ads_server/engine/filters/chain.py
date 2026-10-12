"""필터 체인. 후보는 **처음 걸린 필터**의 사유로 한 번만 거절된다. 거절은 사유별 개수만 남긴다(trace 가 커지지 않게)."""
from ..registry import get_filter


def run_filters(priced, request, names):
    """priced = [(Candidate, Effect)]. 반환: (통과한 [(Candidate, Effect)], {사유: 개수})."""
    checks = [get_filter(name) for name in names]
    survivors, rejected = [], {}
    for candidate, effect in priced:
        for check in checks:
            reason = check(candidate, effect, request)
            if reason is not None:
                rejected[reason] = rejected.get(reason, 0) + 1
                break
        else:
            survivors.append((candidate, effect))
    return survivors, rejected
