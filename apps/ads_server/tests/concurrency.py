"""경쟁 시험의 공용 도우미. 실제 MySQL 연결을 스레드마다 하나씩 쓰고(`TransactionTestCase`), SQL 직전의 훅으로 실행 순서를 고정한다.

- `Worker`: 별도 연결에서 일을 실행하고 예외를 모은다(끝나면 연결을 닫는다).
- `pausing_before`: 첫 해당 SQL 직전에 멈춘다(`paused` 를 알리고 `release` 를 기다린다). 시험이 중간에 실패해도 스레드가 `WAIT` 동안 매달리지
  않게 `self.addCleanup(release.set)` 을 함께 건다.
- `arriving_before`: 멈추지 않고 첫 해당 SQL 직전에 `arrived` 만 알린다. 뒤따르는 `is_alive()` 가 "느린 실행"이 아니라 **그 SQL(잠금)에서의 대기**임을 보인다.
- `Uncommitted`: 별도 연결의 트랜잭션에서 일을 끝까지 하고 **커밋을 미룬다**(진행 중인 접수·비활성화).
- `overlap`: 한쪽이 첫 해당 SQL 직전에 멈춘 사이 다른 쪽을 시작하고, 둘째가 막혀 있는지 본 뒤 재개해 둘 다 끝낸다.
- `run_together`: 여러 일을 스레드 하나씩, 같은 순간에 시작한다(배리어).
"""
import threading

from django.db import connection, transaction

WAIT = 30  # 안전망(시험이 멈춰도 영원히 기다리지 않는다)
BLOCKED = 0.7  # 이만큼 기다려도 끝나지 않으면 '막혀 있다'고 본다


class Worker(threading.Thread):
    """별도 연결에서 `work()` 를 실행한다. 예외는 모아 둔다."""

    def __init__(self, work):
        super().__init__(daemon=True)
        self.work, self.errors, self.result = work, [], None

    def run(self):
        try:
            self.result = self.work()
        except BaseException as error:  # noqa: BLE001
            self.errors.append(error)
        finally:
            connection.close()


def _matches(sql, verb, table):
    return sql.lstrip().upper().startswith(verb) and f"`{table}`" in sql


def pausing_before(verb, table, work, paused, release):
    """`work()` 를 실행하되 `table` 에 대한 첫 `verb`(UPDATE·INSERT) 직전에 `paused` 를 알리고 `release` 를 기다린다."""
    def hook(execute, sql, params, many, context):
        if _matches(sql, verb, table) and not paused.is_set():
            paused.set()
            assert release.wait(WAIT)
        return execute(sql, params, many, context)

    def run():
        with connection.execute_wrapper(hook):
            return work()
    return run


def arriving_before(fragment, table, work, arrived):
    """`work()` 를 실행하되 `table` 을 다루고 `fragment`(예: "FOR UPDATE")가 든 첫 SQL 직전에 `arrived` 를 알린다(멈추지 않는다)."""
    def hook(execute, sql, params, many, context):
        if fragment in sql and f"`{table}`" in sql:
            arrived.set()
        return execute(sql, params, many, context)

    def run():
        with connection.execute_wrapper(hook):
            return work()
    return run


class Uncommitted:
    """`work()` 를 별도 연결의 트랜잭션에서 끝까지 실행하고 **커밋을 미룬다**(다른 연결에서는 그 변경이 보이지 않는다). `commit()` 으로 커밋한다."""

    def __init__(self, work):
        self.done, self.release = threading.Event(), threading.Event()

        def run():
            with transaction.atomic():
                work()
                self.done.set()
                self.release.wait(WAIT)

        self.worker = Worker(run)

    def __enter__(self):
        self.worker.start()
        assert self.done.wait(WAIT), self.worker.errors
        return self

    def commit(self):
        self.release.set()
        self.worker.join(WAIT)
        assert not self.worker.errors, self.worker.errors

    def __exit__(self, *exc):
        self.release.set()
        self.worker.join(WAIT)


def overlap(test, first, verb, table, second, waits=True):
    """`first` 가 `table` 에 대한 첫 `verb` 직전에 멈춘 사이 `second` 를 시작한다. `waits` 면 둘째가 `BLOCKED` 동안 끝나지 않는지(잠금에서 기다리는지) 본다.
    첫째를 재개해 둘 다 끝낸 뒤 (첫째, 둘째) `Worker` 를 돌려준다 — 오류·결과는 부른 쪽이 본다."""
    paused, release = threading.Event(), threading.Event()
    test.addCleanup(release.set)
    a = Worker(pausing_before(verb, table, first, paused, release))
    a.start()
    test.assertTrue(paused.wait(WAIT), f"첫 작업이 {table} {verb} 에 이르지 않았다")
    b = Worker(second)
    b.start()
    b.join(BLOCKED)
    if waits:
        test.assertTrue(b.is_alive(), f"둘째 작업이 첫 작업({table} {verb} 직전)의 잠금을 기다리지 않았다")
    release.set()
    a.join(WAIT)
    b.join(WAIT)
    return a, b


def run_together(jobs, timeout=WAIT):
    """`jobs`(인자 없는 함수들)를 스레드 하나씩, 같은 순간에 시작한다. 결과 목록(실패한 일은 `None`)과 오류 목록을 돌려준다."""
    barrier, results, errors = threading.Barrier(len(jobs)), [None] * len(jobs), []

    def run(index, job):
        try:
            barrier.wait(timeout=10)
            results[index] = job()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, job), daemon=True) for i, job in enumerate(jobs)]
    [t.start() for t in threads]
    [t.join(timeout) for t in threads]
    assert not any(t.is_alive() for t in threads), "스레드가 끝나지 않았다(잠금 대기?)"
    return results, errors
