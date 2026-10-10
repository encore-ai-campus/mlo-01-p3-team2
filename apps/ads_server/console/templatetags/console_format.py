from django import template

from masters.api import Audience, PricingUnit

register = template.Library()
_UNITS, _AUDIENCES = dict(PricingUnit.choices), dict(Audience.choices)


@register.filter
def unit_label(value):
    """과금 단위 코드 → 화면 이름(노출·클릭·전환)."""
    return _UNITS.get(value, value)


@register.filter
def audience_label(value):
    """슬롯 성격 코드 → 화면 이름(개인·일괄)."""
    return _AUDIENCES.get(value, value)


@register.filter
def points(value):
    """포인트 금액 표시(천 단위 쉼표 + 단위). 값이 없으면 빈 문자열. 포인트는 정수다."""
    if value is None or value == "":
        return ""
    return f"{value:,} 포인트"
