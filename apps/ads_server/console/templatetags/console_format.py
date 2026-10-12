from urllib.parse import urlsplit

from django import template

from billing.api import EntryType
from campaigns.api import CampaignStatus, ReviewStatus
from masters.api import Audience, PricingUnit
from records import api as records

register = template.Library()
_UNITS, _AUDIENCES, _STATUSES, _ENTRIES = dict(PricingUnit.choices), dict(Audience.choices), dict(CampaignStatus.choices), dict(EntryType.choices)
_REVIEWS = dict(ReviewStatus.choices)


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


@register.filter
def metric(totals, name):
    """합계에서 지표 하나(`impressions`·`clicks`·`conversions`·`spent`)를 꺼낸다(템플릿은 변수 이름으로 속성을 못 읽는다)."""
    return getattr(totals, name)


@register.filter
def change(report, name):
    """직전 구간 대비 증감률(`report.totals` 와 `report.previous_totals` 의 지표 `name`). 직전이 0 이면 비율을 낼 수 없어 '—'(0 나눗셈을 하지 않는다)."""
    current, previous = getattr(report.totals, name), getattr(report.previous_totals, name)
    if not previous:
        return "—"
    return f"{(current - previous) / previous * 100:+.1f}%"


@register.filter
def number(value):
    """정수 표시(천 단위 쉼표)."""
    return f"{value:,}"


@register.filter
def percent(ratio):
    """비율(0~1) → '12.5%'. 분모가 0 이라 비율이 없으면(`None`) '—'."""
    return "—" if ratio is None else f"{ratio * 100:.1f}%"


_SEVERITIES = {"critical": "긴급", "warning": "주의", "info": "알림"}


@register.filter
def severity_label(value):
    """알림 심각도 → 화면 이름."""
    return _SEVERITIES.get(value, value)


@register.filter
def review_label(value):
    """재검토 요청 상태 코드 → 화면 이름."""
    return _REVIEWS.get(value, value)


_EFFECTS = {"within_range": "그대로 적용", "capped_at_cap": "상한으로 적용", "below_floor": "하한 미만 — 노출 안 됨",
            "slot_inactive": "꺼진 위치 — 노출 안 됨", "no_policy": "알 수 없는 위치"}


@register.filter
def effect_label(value):
    """위치별 적용 결과(C6 `SlotEffect.reason`) → 화면 문구. 모르는 값은 그대로(계약: 알 수 없는 값을 오류로 다루지 않는다)."""
    return _EFFECTS.get(value, value)


@register.simple_tag
def reaction_status():
    """반응 처리 현황(관리자 첫 화면 카드, 설계 §10 "반응 처리 현황 노출", 6-3i) — `records.api.inbox_status()`, 질의 한 번."""
    return records.inbox_status()
