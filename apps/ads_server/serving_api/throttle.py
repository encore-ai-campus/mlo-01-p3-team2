"""매체별·경로군별 **토큰 버킷** 요청 제한(설계 §6.5, 계약 C1 "요청 제한").

버킷은 (매체 UUID, 경로군) 이다 — 키를 교체해도 같은 매체의 버킷이다. 초과하면 몇 초 뒤에 다시 보낼지를 돌려준다.

ponytail: 상태가 **프로세스 메모리**에 있다. 워커가 N 개면 실제 한도는 최대 N 배로 느슨해진다(워커 수는 적게 둔다, Step 0-1).
상한이 문제가 되면 공유 저장소(DB·캐시)로 옮긴다. 150명 규모의 개발용 초기값이며 2-6 부하 측정 뒤에 조정한다.
"""
import math
import threading
import time


class TokenBuckets:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._state = {}

    def reset(self):
        with self._lock:
            self._state.clear()

    def take(self, key, rate, burst):
        """토큰 한 개를 쓴다. 통과면 `None`, 막히면 다시 시도할 때까지의 **정수 초(1 이상)**."""
        with self._lock:
            now = self.clock()  # 시각 조회부터 충전·차감·저장까지 한 임계 구역이다. 밖에서 읽으면 늦게 처리된 요청이 마지막 시각을 과거로 되돌린다
            tokens, last = self._state.get(key, (float(burst), now))
            tokens = min(float(burst), tokens + max(0.0, now - last) * rate)
            if tokens >= 1.0:
                self._state[key] = (tokens - 1.0, now)
                return None
            self._state[key] = (tokens, now)
            return max(1, math.ceil((1.0 - tokens) / rate))


buckets = TokenBuckets()
