from random import Random
from typing import Sequence

from ..types import AdRequest, Eligible, Selection


class HighestBid:
    """적용 금액이 가장 큰 후보. **동점이면 동점 후보 중 무작위**(상한에 닿은 광고들이 고르게 노출된다).

    `request` 는 읽지 않는다. `rng` 는 동점 처리에만 쓴다. 같은 시드면 입력 순서와 무관하게 같은 결과가 나오도록
    동점 후보를 광고그룹 ID 로 정렬한 뒤 뽑는다.
    """

    name = "highest-bid/v1"

    def select(self, candidates: Sequence[Eligible], request: AdRequest, rng: Random) -> Selection:
        if not candidates:
            return Selection(None, {"policy": self.name, "candidates": 0})
        top = max(c.applied_amount for c in candidates)
        tied = sorted((c for c in candidates if c.applied_amount == top), key=lambda c: str(c.ad_group_id))
        chosen = tied[0] if len(tied) == 1 else rng.choice(tied)
        return Selection(chosen, {
            "policy": self.name,
            "candidates": len(candidates),
            "max_applied_amount": top,
            "tied": [str(c.ad_group_id) for c in tied],
            "picked": str(chosen.ad_group_id),
        })
