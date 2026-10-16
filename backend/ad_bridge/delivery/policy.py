"""노출 재전송의 대기 시간과 전송 임대 시간을 정한다."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    base_delay: float = 1
    max_delay: float = 300
    lease_seconds: float = 60

    def __post_init__(self):
        for value in (self.base_delay, self.max_delay, self.lease_seconds):
            try:
                valid = (
                    not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and value > 0
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("재전송 시간 설정은 유한한 양수여야 합니다.")
        if self.max_delay < self.base_delay:
            raise ValueError("최대 대기 시간은 최초 대기 시간보다 짧을 수 없습니다.")

    def delay_for(self, attempts: int, retry_after: int | None = None) -> float:
        if type(attempts) is not int or attempts < 1:
            raise ValueError("전송 시도 횟수는 양의 정수여야 합니다.")
        if retry_after is not None and (type(retry_after) is not int or retry_after < 0):
            raise ValueError("Retry-After는 0 이상의 정수 초여야 합니다.")
        delay = self.base_delay
        remaining = attempts - 1
        # 상한에 도달하면 멈추므로 누적 시도 횟수가 커져도 큰 거듭제곱을 만들지 않는다.
        while remaining > 0 and delay < self.max_delay:
            delay = min(delay * 2, self.max_delay)
            remaining -= 1
        # 광고 서버의 재시도 최소 대기 시간은 로컬 지수 대기 상한보다 우선한다.
        return max(delay, retry_after or 0)
