"""서버가 그리는 인라인 SVG 그래프(설계 D3-2: 라이브러리·스크립트 없음, 옆에 같은 값의 표). 색·글꼴은 CSS 클래스로만 준다 — CSP 가 `style` 속성을 막는다."""
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()

WIDTH, HEIGHT, LEFT, BOTTOM, TOP = 640, 200, 44, 24, 12


@register.simple_tag
def trend_chart(rows, name, label, partial_day=None):
    """일별 막대 그래프. `rows` 는 `ReportRow`(날짜·합계), `name` 은 지표 속성 이름. `partial_day` 의 막대는 집계 중이라 흐리게 그린다."""
    values = [getattr(row.totals, name) for row in rows]
    top = max(values, default=0) or 1
    plot_w, plot_h = WIDTH - LEFT, HEIGHT - BOTTOM - TOP
    step = plot_w / max(len(rows), 1)
    every = max(1, round(len(rows) / 10))  # 날짜 글자가 겹치지 않게 최대 10개쯤만
    bars, ticks = [], []
    for i, (row, value) in enumerate(zip(rows, values)):
        h = plot_h * value / top
        x = LEFT + i * step + step * 0.15
        bars.append((("bar partial" if row.date == partial_day else "bar"), f"{x:.1f}", f"{TOP + plot_h - h:.1f}", f"{step * 0.7:.1f}", f"{h:.1f}",
                     f"{row.date:%m-%d} {value:,}"))
        if i % every == 0:
            ticks.append((f"{LEFT + i * step + step / 2:.1f}", HEIGHT - 6, f"{row.date:%m-%d}"))
    return format_html(
        '<svg class="chart" viewBox="0 0 {w} {h}" width="100%" role="img" aria-labelledby="chart-title">'
        '<title id="chart-title">{label} 일별 추세(최대 {top})</title>'
        '<line class="axis" x1="{left}" y1="{base}" x2="{w}" y2="{base}"/>'
        '<text x="{tx}" y="{ty}" text-anchor="end">{top}</text><text x="{tx}" y="{base}" text-anchor="end">0</text>'
        "{bars}{ticks}</svg>",
        w=WIDTH, h=HEIGHT, label=label, top=f"{max(values, default=0):,}", left=LEFT, base=TOP + plot_h, tx=LEFT - 6, ty=TOP + 10,
        bars=format_html_join("", '<rect class="{}" x="{}" y="{}" width="{}" height="{}"><title>{}</title></rect>', bars),
        ticks=format_html_join("", '<text x="{}" y="{}" text-anchor="middle">{}</text>', ticks),
    )
