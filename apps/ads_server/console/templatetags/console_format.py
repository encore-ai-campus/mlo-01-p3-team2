from urllib.parse import urlsplit

from django import template

from billing.api import EntryType
from campaigns.api import CampaignStatus
from masters.api import Audience, PricingUnit

register = template.Library()
_UNITS, _AUDIENCES, _STATUSES, _ENTRIES = dict(PricingUnit.choices), dict(Audience.choices), dict(CampaignStatus.choices), dict(EntryType.choices)


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


@register.filter
def get_item(mapping, key):
    """사전에서 키로 꺼낸다(템플릿은 변수 키로 사전을 못 읽는다)."""
    return mapping.get(key) if mapping else None


@register.filter
def domain(url):
    """이동 주소의 도메인(관리자 화면에서 눈에 띄게 보인다 — 피싱 주소를 알아보게). 해석하지 못하면 빈 문자열."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


@register.filter
def status_label(value):
    """캠페인 상태 코드 → 화면 이름."""
    return _STATUSES.get(value, value)


@register.filter
def entry_label(value):
    """원장 항목 종류 코드 → 화면 이름(가입 지급·반응 과금·관리자 조정)."""
    return _ENTRIES.get(value, value)
