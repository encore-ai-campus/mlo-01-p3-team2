"""게임에서 받은 첫 노출 알림을 저장하고 전송한다."""

from ..delivery.policy import RetryPolicy, utc_now
from ..delivery.sender import ImpressionReport, send_once


def report_impression_once(
    *, client, store, decision_id, owner_id, occurred_at: str,
    policy: RetryPolicy | None = None, now=utc_now,
) -> ImpressionReport:
    """최초 알림만 즉시 전송한다. 중복 알림의 재전송은 별도 작업자가 담당한다."""
    policy = policy if policy is not None else RetryPolicy()
    record, created = store.reserve_impression(
        decision_id, owner_id, occurred_at, now=now(), lease_seconds=policy.lease_seconds,
    )
    if not created:
        return ImpressionReport(record, False)
    return send_once(client=client, store=store, record=record, policy=policy, now=now)
