"""실제 대기 없이 재전송 시각을 조절하는 테스트 시계."""

from datetime import datetime, timedelta, timezone


class FixedClock:
    """실제로 기다리지 않고 재전송 시각 경계를 넘긴다."""

    def __init__(self):
        self.current = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


