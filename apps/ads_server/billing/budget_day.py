"""예산 "그날"의 경계 — **함수·설정값 한 곳**(설계 §4.7). 소진액 집계와 화면의 리셋 시각이 모두 여기서 나온다.

`BUDGET_DAY_OFFSET_HOURS` 기본 0 = UTC 자정(KST 09:00 리셋). KST 자정으로 바꾸려면 9 로 두고 `recompute_spend` 를 실행한다.
"""
from datetime import datetime, time, timedelta, timezone

from django.conf import settings


def _offset():
    return timedelta(hours=settings.BUDGET_DAY_OFFSET_HOURS)


def budget_day_of(instant):
    """이 시각이 속한 예산 일(날짜)."""
    return (instant.astimezone(timezone.utc) + _offset()).date()


def day_start(day):
    """예산 일의 시작 시각(UTC)."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc) - _offset()


def next_reset(instant):
    """다음 리셋 시각(UTC). 화면에 "N시에 초기화"로 보여 준다."""
    return day_start(budget_day_of(instant) + timedelta(days=1))
