"""관리자 첫 화면(Django admin — 백엔드가 그린다, 설계 §6.6 "6-15 분리")의 반응 처리 현황 카드. 우리 화면의 서식 필터는 프론트(apps/ads_frontend/ui/templatetags)에 있다."""
from django import template

from records import api as records

register = template.Library()


@register.filter
def number(value):
    """정수 표시(천 단위 쉼표)."""
    return f"{value:,}"


@register.simple_tag
def reaction_status():
    """반응 처리 현황(관리자 첫 화면 카드, 설계 §10 "반응 처리 현황 노출", 6-3i) — `records.api.inbox_status()`, 질의 한 번."""
    return records.inbox_status()
