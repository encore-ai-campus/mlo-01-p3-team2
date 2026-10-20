"""이름 → 구현. 선택 알고리즘과 필터는 이름으로 고르고, 알 수 없는 이름은 **즉시 오류**다(조용히 기본값으로 바꾸지 않는다).

어떤 이름을 쓸지는 호출하는 쪽(`records`)이 설정에서 읽어 넘긴다(설계 R4). 이 파일은 설정을 읽지 않는다.
"""
from .filters import balance, budget, floor, period, status
from .policies.weighted_by_bid import WeightedByBid

DEFAULT_POLICY = WeightedByBid.name
# 순서가 곧 판정 순서다. `floor` 는 적용 금액이 없는 후보(하한 미만)를 거르므로 `budget`·`balance` 보다 앞이어야 한다.
DEFAULT_FILTERS = ("status", "period", "floor", "budget", "balance")

_POLICIES = {WeightedByBid.name: WeightedByBid()}
_FILTERS = {"status": status.check, "period": period.check, "floor": floor.check, "budget": budget.check, "balance": balance.check}


class UnknownName(ValueError):
    pass


def get_policy(name):
    try:
        return _POLICIES[name]
    except KeyError:
        raise UnknownName(f"알 수 없는 선택 정책: {name!r} (등록된 것: {sorted(_POLICIES)})")


def get_filter(name):
    try:
        return _FILTERS[name]
    except KeyError:
        raise UnknownName(f"알 수 없는 필터: {name!r} (등록된 것: {sorted(_FILTERS)})")


def register_policy(policy):
    """새 알고리즘을 등록한다(이름 중복 불가). `engine/policies/` 에 파일 하나를 더하고 여기에 한 줄을 더하는 것이 전부다."""
    if policy.name in _POLICIES:
        raise ValueError(f"이미 등록된 정책: {policy.name!r}")
    _POLICIES[policy.name] = policy


def unregister_policy(name):
    _POLICIES.pop(name, None)
