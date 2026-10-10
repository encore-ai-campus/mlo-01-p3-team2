from django import template

register = template.Library()


@register.filter
def points(value):
    """포인트 금액 표시(천 단위 쉼표 + 단위). 값이 없으면 빈 문자열. 포인트는 정수다."""
    if value is None or value == "":
        return ""
    return f"{value:,} 포인트"
