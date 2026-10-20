from zoneinfo import ZoneInfo

from django import template

register = template.Library()
KST = ZoneInfo("Asia/Seoul")


@register.filter
def kst(value, fmt="%Y-%m-%d %H:%M"):
    """UTC 시각을 **화면 표시용으로만** KST 로 바꾼다. 저장·계산에는 쓰지 않는다."""
    if value is None or value == "":
        return ""
    if value.tzinfo is None:
        raise ValueError("naive datetime 은 표시할 수 없다(USE_TZ=True 이므로 aware 여야 한다).")
    return value.astimezone(KST).strftime(fmt)
