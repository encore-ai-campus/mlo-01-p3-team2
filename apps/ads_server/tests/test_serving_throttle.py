import threading
import unittest

from serving_api.throttle import TokenBuckets


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TokenBucketTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.buckets = TokenBuckets(self.clock)

    def take(self, key="a", rate=2, burst=3):
        return self.buckets.take(key, rate, burst)

    def test_burst_then_blocked_with_integer_retry_after_of_at_least_one(self):
        self.assertEqual([self.take() for _ in range(3)], [None, None, None])
        wait = self.take()
        self.assertIsInstance(wait, int)
        self.assertGreaterEqual(wait, 1)
        self.assertEqual(wait, 1)  # 초당 2개: 토큰 1개까지 0.5초 → 올림해 1초

    def test_refill_at_the_configured_rate_and_never_beyond_burst(self):
        [self.take() for _ in range(3)]
        self.assertIsNotNone(self.take())
        self.clock.now += 1.0  # 2개 충전
        self.assertEqual([self.take(), self.take()], [None, None])
        self.assertIsNotNone(self.take())
        self.clock.now += 100.0  # 오래 쉬어도 버스트(3)를 넘지 않는다
        self.assertEqual([self.take() for _ in range(3)], [None, None, None])
        self.assertIsNotNone(self.take())

    def test_retry_after_grows_with_the_deficit_and_rounds_up(self):
        self.assertEqual([self.buckets.take("slow", 0.25, 1)], [None])  # 초당 0.25 = 4초에 하나
        self.assertEqual(self.buckets.take("slow", 0.25, 1), 4)
        self.clock.now += 3.9
        self.assertEqual(self.buckets.take("slow", 0.25, 1), 1)  # 0.1초 남음 → 올림 1
        self.clock.now += 0.2
        self.assertIsNone(self.buckets.take("slow", 0.25, 1))

    def test_keys_are_independent_and_reset_clears_state(self):
        [self.take("a") for _ in range(3)]
        self.assertIsNotNone(self.take("a"))
        self.assertIsNone(self.take("b"))  # 다른 키는 영향 없음
        self.buckets.reset()
        self.assertIsNone(self.take("a"))

    def test_clock_going_backwards_does_not_grant_tokens(self):
        [self.take() for _ in range(3)]
        self.clock.now -= 50
        self.assertIsNotNone(self.take())

    def test_concurrent_takes_never_exceed_the_burst(self):
        results, barrier = [], threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(10):
                results.append(self.buckets.take("shared", 1, 20))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(None), 20)  # 80번 시도 중 정확히 버스트만큼만 통과
