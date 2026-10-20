"""기한이 된 노출 기록을 확보하고 공통 전송 함수를 호출한다."""

from .policy import RetryPolicy, utc_now
from .sender import send_once


def dispatch_due_impressions(
    *, client, store, limit: int = 100, policy: RetryPolicy | None = None,
    now=utc_now, should_stop=lambda: False,
) -> dict[str, int]:
    """기한이 된 미접수 기록 또는 임대가 만료된 기록을 한 묶음 전송한다."""
    if type(limit) is not int or limit < 1:
        raise ValueError("배치 크기는 양의 정수여야 합니다.")
    policy = policy if policy is not None else RetryPolicy()
    counts = {"attempted": 0, "acknowledged": 0, "unconfirmed": 0, "blocked": 0}
    for _ in range(limit):
        if should_stop():
            break
        # 저장소는 임대를 커밋하고 반환한다. HTTP 동안 DB 트랜잭션을 유지하지 않는다.
        record = store.claim_due_impression(now=now(), lease_seconds=policy.lease_seconds)
        if record is None:
            break
        result = send_once(client=client, store=store, record=record, policy=policy, now=now)
        counts["attempted"] += 1
        if result.record.delivery_state == "ACKNOWLEDGED":
            counts["acknowledged"] += 1
        elif result.record.delivery_state == "BLOCKED":
            counts["blocked"] += 1
        else:
            # 임대 만료 후 다른 작업자가 전송 중인 경우에도 접수 완료로 추정하지 않는다.
            counts["unconfirmed"] += 1
    return counts
