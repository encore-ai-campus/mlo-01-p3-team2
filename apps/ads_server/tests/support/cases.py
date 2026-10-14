"""한 규칙 = 시험 하나(설계 §10 "시험 구성" ④, 6-18): 규칙(시험 클래스)의 경우를 `case_…` 메서드로 두고, 시험 하나가 모두 돈다.

경우마다 원래 시험처럼 **따로** 돈다 — 새 인스턴스로 `setUp`·`tearDown` 과 DB 격리(TestCase 는 저장점으로 되돌림, TransactionTestCase 는 표 비우기)를 거친다.
실패·오류는 경우 이름의 subTest 로 보고하고(한 경우가 실패해도 나머지를 모두 돈다), 건너뜀도 그대로 건너뜀이다.
"""
import unittest


class Cases:
    """`case_*` 메서드를 이름 순서로 모두 돈다. 쓰는 클래스는 `def test_…(self): self.run_cases()` 하나를 둔다."""

    # 경우들을 도는 바깥 시험은 클래스의 setUp·tearDown 을 하지 않는다 — 그 준비가 남긴 행이 경우들에 섞이지 않게
    # (TransactionTestCase 는 커밋된 행이 남고, TestCase 는 경우의 저장점이 바깥 준비 위에 열린다). unittest 의 _callSetUp·_callTearDown 훅(3.8+).
    def _callSetUp(self):
        if self._testMethodName.startswith("case_"):
            super()._callSetUp()

    def _callTearDown(self):
        if self._testMethodName.startswith("case_"):
            super()._callTearDown()

    def run_cases(self):
        names = sorted(n for n in dir(self) if n.startswith("case_") and callable(getattr(self, n)))
        self.assertTrue(names, "경우가 없다")
        for name in names:
            result = unittest.TestResult()
            type(self)(name)(result)  # Django 의 __call__ — 원래 시험 하나와 같은 준비·정리·격리
            with self.subTest(name):
                for _test, trace in result.errors + result.failures:
                    self.fail(trace)
                for _test, reason in result.skipped:
                    self.skipTest(reason)
