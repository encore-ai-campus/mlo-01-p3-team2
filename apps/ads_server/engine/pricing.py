"""적용 금액과 종료 판정 — 이 규칙은 **여기에만** 있다(설계 §4.2·§4.5).

선택 로직, 광고주 화면의 안내값(effects·bid-preview), 캠페인의 종료 전환·수정 가드가 모두 이 함수를 부른다.
"""
from .types import Effect, _int

WITHIN_RANGE = "within_range"
CAPPED_AT_CAP = "capped_at_cap"
BELOW_FLOOR = "below_floor"


def effect_of(bid, floor, cap):
    """입찰 금액을 슬롯 정책(하한·상한)에 대어 본다.

    | 입찰 | 결과 |
    | 입찰 < 하한 | 후보 제외 |
    | 하한 ≤ 입찰 ≤ 상한 | 입찰 그대로 |
    | 입찰 > 상한 | 상한으로 적용 |
    """
    _int("bid", bid)
    _int("floor", floor)
    _int("cap", cap)
    if bid < floor:
        return Effect(False, None, BELOW_FLOOR)
    if bid > cap:
        return Effect(True, cap, CAPPED_AT_CAP)
    return Effect(True, bid, WITHIN_RANGE)


def is_expired(ends_at, now):
    """종료 시각(미포함)이 지났는가. `ends_at` 이 없으면 끝나지 않는다. `ends_at == now` 는 종료다."""
    return ends_at is not None and ends_at <= now
