"""경쟁 시험의 공용 도우미. 실제 MySQL 연결을 스레드마다 하나씩 쓰고(`TransactionTestCase`), SQL 직전의 훅으로 실행 순서를 고정한다.

- `Worker`: 별도 연결에서 일을 실행하고 예외를 모은다(끝나면 연결을 닫는다).
- `pausing_before`: 첫 해당 SQL 직전에 멈춘다(`paused` 를 알리고 `release` 를 기다린다). 시험이 중간에 실패해도 스레드가 `WAIT` 동안 매달리지
  않게 `self.addCleanup(release.set)` 을 함께 건다.
- `arriving_before`: 멈추지 않고 첫 해당 SQL 직전에 `arrived` 만 알린다. 뒤따르는 `is_alive()` 가 "느린 실행"이 아니라 **그 SQL(잠금)에서의 대기**임을 보인다.
"""
import threading

from django.db import connection

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
