from random import Random
from typing import Protocol, Sequence

from ..types import AdRequest, Eligible, Selection


class SelectionPolicy(Protocol):
    """선택 알고리즘. 이름·버전이 붙고 설정으로 고른다. 알고리즘을 바꿔도 `Selection` 구조는 바뀌지 않는다(설계 §4.3)."""

    name: str

    def select(self, candidates: Sequence[Eligible], request: AdRequest, rng: Random) -> Selection: ...
