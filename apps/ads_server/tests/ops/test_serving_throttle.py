import threading
import unittest

from serving_api.throttle import TokenBuckets
from tests.support.cases import Cases


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TokenBucketTests(Cases, unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.buckets = TokenBuckets(self.clock)

    def take(self, key="a", rate=2, burst=3):
        return self.buckets.take(key, rate, burst)

    def case_burst_then_blocked_with_integer_retry_after_of_at_least_one(self):
        self.assertEqual([self.take() for _ in range(3)], [None, None, None])
        wait = self.take()
        self.assertIsInstance(wait, int)
        self.assertGreaterEqual(wait, 1)
        self.assertEqual(wait, 1)  # 초당 2개: 토큰 1개까지 0.5초 → 올림해 1초

    def case_refill_at_the_configured_rate_and_never_beyond_burst(self):
        [self.take() for _ in range(3)]
        self.assertIsNotNone(self.take())
        self.clock.now += 1.0  # 2개 충전
        self.assertEqual([self.take(), self.take()], [None, None])
        self.assertIsNotNone(self.take())
        self.clock.now += 100.0  # 오래 쉬어도 버스트(3)를 넘지 않는다
        self.assertEqual([self.take() for _ in range(3)], [None, None, None])
        self.assertIsNotNone(self.take())

    def case_retry_after_grows_with_the_deficit_and_rounds_up(self):
        self.assertEqual([self.buckets.take("slow", 0.25, 1)], [None])  # 초당 0.25 = 4초에 하나
        self.assertEqual(self.buckets.take("slow", 0.25, 1), 4)
        self.clock.now += 3.9
        self.assertEqual(self.buckets.take("slow", 0.25, 1), 1)  # 0.1초 남음 → 올림 1
        self.clock.now += 0.2
        self.assertIsNone(self.buckets.take("slow", 0.25, 1))

    def case_keys_are_independent_and_reset_clears_state(self):
        [self.take("a") for _ in range(3)]
        self.assertIsNotNone(self.take("a"))
        self.assertIsNone(self.take("b"))  # 다른 키는 영향 없음
        self.buckets.reset()
        self.assertIsNone(self.take("a"))

    def case_clock_going_backwards_does_not_grant_tokens(self):
        [self.take() for _ in range(3)]
        self.clock.now -= 50
        self.assertIsNotNone(self.take())

    def case_concurrent_takes_never_exceed_the_burst(self):
        results, barrier = [], threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(10):
                results.append(self.buckets.take("shared", 1, 20))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(None), 20)  # 80번 시도 중 정확히 버스트만큼만 통과

    def case_reordered_requests_never_charge_the_same_elapsed_time_twice(self):
        """시각을 먼저 읽은 요청이 **잠금을 늦게** 얻어도 마지막 갱신 시각이 과거로 돌아가면 안 된다.

        rate=1, burst=1: 0초에 한 번, 1초 시점에 한 번 → 1초 구간에서 허용은 딱 2건. 시각 조회가 잠금 밖이면 3건이 통과한다.
        """
        slow_reads, release, value = threading.Event(), threading.Event(), [0.0]
        slow = []

        def clock():
            if threading.current_thread() in slow:
                slow_reads.set()
                release.wait(2)  # 시각 0 을 얻고도 처리가 늦어지는 요청
                return 0.0
            return value[0]

        buckets = TokenBuckets(clock)
        passed = [buckets.take("k", 1, 1) is None]  # t=0: 초기 토큰
        results = {}

        def run(name):
            results[name] = buckets.take("k", 1, 1)

        late = threading.Thread(target=run, args=("late",))
        slow.append(late)
        late.start()
        slow_reads.wait(2)
        value[0] = 1.0
        fast = threading.Thread(target=run, args=("fast",))
        fast.start()
        fast.join(0.3)  # 잠금 밖 조회면 여기서 먼저 끝난다. 안이면 late 가 잠금을 쥐고 있어 기다린다.
        release.set()
        late.join(2)
        fast.join(2)
        passed.append(results["fast"] is None)
        passed.append(results["late"] is None)
        passed.append(buckets.take("k", 1, 1) is None)  # t=1 에 한 번 더
        self.assertEqual(passed.count(True), 2, passed)

    def test_token_bucket(self):
        self.run_cases()
