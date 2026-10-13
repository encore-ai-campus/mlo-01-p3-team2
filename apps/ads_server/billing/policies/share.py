class ShareV1:
    """반응 하나의 과금 = 내림(결정에 기록된 적용 금액 × 결정에 남긴 그 유형의 비율 ÷ 100)(설계 §10 "구성별 반응 비율 과금").
    비율은 각각 1~98·합 100 이고 하한은 100 이상이라 0 이 나오지 않고, 결정 하나의 합은 적용 금액을 넘지 않는다."""

    name = "share/v1"

    def amount_for(self, reaction_type, shares, applied_amount):
        return applied_amount * shares[reaction_type] // 100
