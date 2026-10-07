class ByUnitV1:
    """반응 유형이 광고그룹의 과금 단위와 같을 때만, 그 반응의 Decision 에 기록된 적용 금액을 과금한다(설계 §4.7)."""

    name = "by-unit/v1"

    def amount_for(self, reaction_type, pricing_unit, applied_amount):
        return applied_amount if reaction_type == pricing_unit else 0
