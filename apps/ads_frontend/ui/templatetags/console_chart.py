"""서버가 그리는 인라인 SVG 그래프(설계 D3-2: 라이브러리·스크립트 없음, 옆에 같은 값의 표). 색·글꼴은 CSS 클래스로만 준다 — CSP 가 `style` 속성을 막는다.

모양은 시안 v2(설계 §10 "광고주 화면 v2"): 선 + 아래로 옅어지는 영역, 오늘(집계 중)은 점선과 빈 점, 최고값 말풍선, 눈금은 0 과 같은 간격의 셋(1k 단위).
"""
import math

from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()

WIDTH, HEIGHT, LEFT, RIGHT, TOP, PLOT = 724, 196, 48, 14, 30, 132  # 그림 영역: x LEFT~WIDTH-RIGHT, y TOP~TOP+PLOT, 아래는 날짜


def _nice_step(top):
    """눈금 간격: 최대값을 세 칸에 담는 1·2·2.5·5 × 10ⁿ 중 가장 작은 것."""
    if top <= 0:
        return 1
    raw = top / 3
    base = 10 ** math.floor(math.log10(raw))
    return next(m * base for m in (1, 2, 2.5, 5, 10) if m * base >= raw)


def _short(value):
    """눈금 글자: 1,000 이상은 k(4k·12k·2.5k)."""
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


@register.simple_tag
def trend_chart(rows, name, label, partial_day=None):
    """일별 추세 그래프. `rows` 는 `ReportRow`(날짜·합계), `name` 은 지표 속성 이름. `partial_day`(오늘)는 집계 중이라 점선과 빈 점."""
    values = [getattr(row.totals, name) for row in rows]
    step = _nice_step(max(values, default=0))
    top = step * 3
    plot_w = WIDTH - LEFT - RIGHT
    gap = plot_w / max(len(rows) - 1, 1)
    xy = [(LEFT + i * gap if len(rows) > 1 else LEFT + plot_w / 2, TOP + PLOT - PLOT * v / top) for i, v in enumerate(values)]
    partial = [row.date == partial_day for row in rows]
    solid_end = len(rows) - 1 if partial and partial[-1] else len(rows)  # 오늘이 끝에 있으면 그 앞까지 실선
    path = lambda pts: " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    line = path(xy[:solid_end]) if solid_end > 1 else ""
    dash = path(xy[solid_end - 1:]) if 0 < solid_end < len(rows) else ""
    area = f"{path(xy)} L{xy[-1][0]:.1f} {TOP + PLOT} L{xy[0][0]:.1f} {TOP + PLOT} Z" if xy else ""
    every = max(1, math.ceil(len(rows) / 10))  # 날짜 글자는 최대 10개쯤
    grid = [(TOP + PLOT - PLOT * k / 3, _short(step * k)) for k in range(4)]
    points = [("point partial" if p else "point", f"{x:.1f}", f"{y:.1f}", f"{row.date:%m-%d} {v:,}") for (x, y), p, row, v in zip(xy, partial, rows, values)]
    ticks = [(f"{x:.1f}", "tick today" if p else "tick", "오늘" if p else f"{row.date.month}.{row.date.day}")
             for i, ((x, _), p, row) in enumerate(zip(xy, partial, rows)) if p or i % every == 0]
    peak = max(range(len(values)), key=values.__getitem__) if values and max(values) > 0 else None
    tip = ""
    if peak is not None:
        x, y = xy[peak]
        x = min(max(x, LEFT + 42), WIDTH - 42)
        tip = format_html('<g class="tip"><rect x="{}" y="{}" width="84" height="26" rx="6"/><text x="{}" y="{}" text-anchor="middle">{}</text></g>',
                          f"{x - 42:.1f}", f"{y - 38:.1f}", f"{x:.1f}", f"{y - 20:.1f}", f"{values[peak]:,}")
    return format_html(
        '<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img" aria-labelledby="chart-title">'
        '<title id="chart-title">{label} 일별 추세(최대 {max})</title>'
        '<defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop class="fill-top" offset="0"/><stop class="fill-bottom" offset="1"/></linearGradient></defs>'
        "{grid}"
        '<path class="area" d="{area}" fill="url(#chart-fill)"/>'
        '<path class="line" d="{line}"/><path class="line partial" d="{dash}"/>'
        "{points}{ticks}{tip}</svg>",
        w=WIDTH, h=HEIGHT, label=label, max=f"{max(values, default=0):,}", area=area, line=line, dash=dash, tip=tip,
        grid=format_html_join("", '<line class="grid" x1="{}" y1="{}" x2="{}" y2="{}"/><text class="axis" x="{}" y="{}" text-anchor="end">{}</text>',
                              ((LEFT - 8, f"{y:.1f}", WIDTH - RIGHT, f"{y:.1f}", LEFT - 14, f"{y + 4:.1f}", t) for y, t in grid)),
        points=format_html_join("", '<circle class="{}" cx="{}" cy="{}" r="4"><title>{}</title></circle>', points),
        ticks=format_html_join("", '<text class="{}" x="{}" y="' + str(HEIGHT - 8) + '" text-anchor="middle">{}</text>',
                               ((cls, x, t) for x, cls, t in ticks)),
    )
