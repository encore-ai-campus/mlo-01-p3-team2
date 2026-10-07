"""engine 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2). 순수 파이썬이며 DB·Django 를 모른다."""
from random import Random

from .filters.chain import run_filters
from .pricing import effect_of, is_expired
from .registry import DEFAULT_FILTERS, DEFAULT_POLICY, UnknownName, get_policy, register_policy, unregister_policy
from .types import AdRequest, Candidate, DecisionResult, Effect, Eligible, Selection


def decide(candidates, request: AdRequest, rng: Random, policy=DEFAULT_POLICY, filters=DEFAULT_FILTERS) -> DecisionResult:
    """적용 금액 계산 → 자격 필터 → 선택 알고리즘. 알 수 없는 정책·필터 이름은 오류다."""
    selector = get_policy(policy)  # 이름 오류는 후보가 없어도 바로 드러나게 먼저 확인한다
    candidates = list(candidates)
    for c in candidates:
        if c.slot_id != request.slot_id:
            raise ValueError("요청한 슬롯의 후보가 아니다")
    priced = [(c, effect_of(c.bid_amount, c.floor, c.cap)) for c in candidates]
    survivors, rejected = run_filters(priced, request, filters)
    eligible = []
    for c, effect in survivors:
        if effect.applied_amount is None:
            raise ValueError("필터 목록에 floor 가 없어 적용 금액이 없는 후보가 남았다")
        eligible.append(Eligible.of(c, effect.applied_amount))
    return DecisionResult(selector.select(eligible, request, rng), considered=len(candidates), rejected=rejected)


__all__ = [
    "decide", "effect_of", "is_expired", "register_policy", "unregister_policy", "get_policy", "UnknownName",
    "DEFAULT_POLICY", "DEFAULT_FILTERS", "AdRequest", "Candidate", "Eligible", "Effect", "Selection", "DecisionResult",
]
