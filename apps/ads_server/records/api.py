"""records 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2). 값 객체만 돌려준다."""
from .services import decide, get_decision
from .types import ChosenView, DecisionView

__all__ = ["decide", "get_decision", "ChosenView", "DecisionView"]
