"""records 의 외부 공개 면. 다른 모듈은 이 파일만 import 한다(설계 R2). 값 객체만 돌려준다."""
from .integrity import event_gaps
from .processing import process_after_receipt, process_pending, process_reaction, reset_stuck, stuck_count
from .services import decide, get_decision, get_reaction, observe_click, receive_reaction
from .report import daily_report
from .types import ChosenView, DailyReportView, DecisionView, ReactionView, ReportRow, ReportTotals

__all__ = ["decide", "get_decision", "receive_reaction", "observe_click", "get_reaction", "daily_report", "event_gaps", "process_reaction", "process_after_receipt", "process_pending", "stuck_count", "reset_stuck", "ChosenView", "DecisionView", "ReactionView", "DailyReportView", "ReportRow", "ReportTotals"]
