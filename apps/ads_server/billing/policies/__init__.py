"""이름 → 과금 정책. 어떤 이름을 쓸지는 설정(`BILLING_CHARGE_POLICY`)이 정한다. 알 수 없는 이름은 즉시 오류다."""
from .by_unit import ByUnitV1

_POLICIES = {ByUnitV1.name: ByUnitV1()}


class UnknownChargePolicy(ValueError):
    pass


def get_charge_policy(name):
    try:
        return _POLICIES[name]
    except KeyError:
        raise UnknownChargePolicy(f"알 수 없는 과금 정책: {name!r} (등록된 것: {sorted(_POLICIES)})")


def register_charge_policy(policy):
    if policy.name in _POLICIES:
        raise ValueError(f"이미 등록된 과금 정책: {policy.name!r}")
    _POLICIES[policy.name] = policy


def unregister_charge_policy(name):
    _POLICIES.pop(name, None)
