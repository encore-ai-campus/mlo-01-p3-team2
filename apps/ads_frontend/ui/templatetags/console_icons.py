"""광고주 화면의 선 아이콘(시안 v2 의 18px 경로 그대로, 선 굵기 1.5 — 설계 §10 "광고주 화면 v2"). 인라인 SVG 라 스크립트·외부 파일이 없다."""
from django import template
from django.utils.html import format_html

register = template.Library()

PATHS = {
    "dashboard": "M1 1H7V7H1Z M11 1H17V7H11Z M1 11H7V17H1Z M11 11H17V17H11Z",
    "campaigns": "M2 4H16V16H2Z M6 1V6 M12 1V6 M2 8H16",
    "creatives": "M2 2H16V16H2Z M2 13L7 8L11 12L14 9L16 11",
    "points": "M2 4H16V15H2Z M2 7H16 M11 9H16V12H11Z",
    "account": "M9 8C5 8 5 2 9 2C13 2 13 8 9 8 M2 17C2 10 16 10 16 17",
    "arrow": "M3 9H15 M10 4L15 9L10 14",
    "search": "M12 12L17 17 M13 7A6 6 0 1 1 1 7A6 6 0 1 1 13 7",
    "plus": "M9 2V16 M2 9H16",
    "chevron": "M5 7L9 11L13 7",
    "check": "M3 9L7 13L15 4",
    "clock": "M9 1A8 8 0 1 1 9 17A8 8 0 1 1 9 1 M9 4V9L12 11",
    "upload": "M9 12V2 M5 6L9 2L13 6 M2 12V16H16V12",
    "lock": "M4 8H14V16H4Z M6 8V5C6 1 12 1 12 5V8",
    "refresh": "M15 9A6 6 0 1 1 13 4.5 M13 1V5H9",
    "chart": "M2 2V16H16 M5 12L8 8L11 10L15 5",
    "image": "M2 3H16V15H2Z M5 7A1.5 1.5 0 1 1 5 6.9 M2 13L7 9L10 12L12 10L16 13",
    "bell": "M4 13V8C4 2 14 2 14 8V13L16 15H2Z M7 17H11",
}


@register.simple_tag
def icon(name, size=18):
    """장식 아이콘(`aria-hidden`) — 뜻은 옆의 글자가 전한다. 크기가 달라도 선 굵기는 1.5px 그대로."""
    return format_html(
        '<svg class="icon" width="{0}" height="{0}" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="{1}" vector-effect="non-scaling-stroke"/></svg>',
        size, PATHS[name])
