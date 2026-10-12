def check(facts):
    """매체 비활성화는 그 전에 만든 결정을 끝낸다(설계 §10, 6-1b): 결정 뒤에 매체가 꺼진 적이 있고 반응이 그 뒤에 **접수**됐으면 거부한다.
    다시 켠 뒤에 보낸 반응도, 서버가 관측한 클릭도 같다. 꺼지기 전에 접수된 반응은 판정이 늦어도 그대로 판정한다(기준은 접수 시각).
    같은 순간이면: 결정과 같은 시각에 끈 것은 결정 전으로, 접수와 같은 시각에 끈 것은 접수 전으로 본다(과금하지 않는 쪽 — `masters.first_deactivation` 의 (결정, 접수] 구간)."""
    return "media_deactivated" if facts.media_deactivated_at is not None else None  # 결정이 없으면 이 사실도 없다(None)
