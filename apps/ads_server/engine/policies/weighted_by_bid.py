from bisect import bisect_right
from itertools import accumulate
from random import Random
from typing import Sequence

from ..types import AdRequest, Eligible, Selection

K = 2  # 상한에 있는 광고는 하한에 있는 광고의 (1 + K) 배 비중. 바꾸면 `name` 의 버전을 올린다 — 결정의 selection_policy 로 어느 K 였는지 안다


class WeightedByBid:
    """상한 근접 가중 추첨(6-14, 설계 §4.3 — "후보 수로 100을 나누고 상한에 가까울수록 높게, 하한 근처도 0은 아니게").

    가중치 = (상한 − 하한) + K × (적용 금액 − 하한): `1 + K × 상한 근접도` 에 `상한 − 하한` 을 곱한 정수라 반올림이 없다. 하한 = 상한이면 모두 1(균등).
    가중치 합 안의 난수 하나로 뽑는다. 같은 적용 금액은 같은 확률이라 동점 처리가 따로 없다. 후보는 광고그룹 ID 순으로 놓는다 —
    같은 시드면 입력 순서와 무관하게 같은 결과. `request` 는 읽지 않는다.
    """

    name = "weighted-by-bid/v1"

    def select(self, candidates: Sequence[Eligible], request: AdRequest, rng: Random) -> Selection:
        if not candidates:
            return Selection(None, {"policy": self.name, "candidates": 0})
        ordered = sorted(candidates, key=lambda c: str(c.ad_group_id))
        weights = [_weight(c) for c in ordered]
        cumulative = list(accumulate(weights))
        draw = rng.randrange(cumulative[-1])
        i = bisect_right(cumulative, draw)  # draw 가 [앞 누적, 이 누적) 에 드는 후보
        chosen = ordered[i]
        # 요약만 남긴다(후보 목록 없음): 뽑힌 광고의 확률 = weight / total
        return Selection(chosen, {"policy": self.name, "candidates": len(ordered), "k": K, "total": cumulative[-1], "weight": weights[i],
                                  "draw": draw, "picked": str(chosen.ad_group_id)})


def _weight(candidate):
    span = candidate.cap - candidate.floor
    return span + K * (candidate.applied_amount - candidate.floor) if span else 1
