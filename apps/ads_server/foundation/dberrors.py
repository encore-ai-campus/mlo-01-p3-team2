"""DB 오류 분류. 오류의 **원인**을 구분해야 하는 곳(예: 멱등 INSERT 의 유일 제약 충돌)이 쓴다.

DB 는 MySQL 8.4 하나다(오류 번호로 구분한다). 모르는 오류는 '유일 제약 충돌이 아님'으로 답한다 — 모르면 숨기지 않고 올리는 쪽이 안전하다.
"""
from django.db import OperationalError


def is_unique_violation(error):
    """`IntegrityError` 가 **유일 제약 위반**(중복 키)인가. CHECK·NOT NULL·외래 키 위반은 아니다."""
    cause = getattr(error, "__cause__", None)
    if cause is None:
        return False
    return bool(cause.args) and cause.args[0] == 1062  # MySQL ER_DUP_ENTRY


# MySQL: 교착(1213)·잠금 대기 초과(1205). 둘 다 **서버가 트랜잭션을 되돌린 것**이라 같은 일을 다시 하면 된다 — 데이터나 코드의 결함이 아니다.
TRANSIENT_MYSQL_CODES = frozenset({1205, 1213})


def is_transient_lock_error(error):
    """교착·잠금 대기 초과처럼 **다시 시도하면 되는** DB 오류인가. 실패 횟수를 세거나 반응을 포기시키는 근거가 되면 안 된다."""
    if not isinstance(error, OperationalError):
        return False
    cause = getattr(error, "__cause__", None) or error
    return bool(getattr(cause, "args", None)) and cause.args[0] in TRANSIENT_MYSQL_CODES
