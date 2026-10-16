from typing import Protocol


class ChargePolicy(Protocol):
    """반응 하나에 **얼마를 과금할지**. 이름이 원장 항목에 남는다(설계 R8). 0 이면 과금하지 않는다."""

    name: str

    def amount_for(self, reaction_type: str, shares: dict[str, int], applied_amount: int) -> int: ...  # shares: 반응 유형 → 비율(%)
