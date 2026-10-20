"""게임에서 받은 첫 노출 알림을 저장하고 전송한다."""

from ..delivery.policy import RetryPolicy, utc_now
from ..delivery.sender import ImpressionReport, send_once


def report_impression_once(
    *, client, store, decision_id, owner_id, occurred_at: str,
    policy: RetryPolicy | None = None, now=utc_now,
    subject_id=None,
) -> ImpressionReport:
    """최초 알림만 즉시 전송한다. 중복 알림의 재전송은 별도 작업자가 담당한다."""
    policy = policy if policy is not None else RetryPolicy()
    # 공유 노출의 가명은 로그인 사용자를 확인한 서버가 생성해 전달한다.
    # 기존 개인 저장소 어댑터에는 새 선택 인자를 강제하지 않는다.
    viewer = {} if subject_id is None else {"subject_id": subject_id}
    record, created = store.reserve_impression(
        decision_id, owner_id, occurred_at, now=now(), lease_seconds=policy.lease_seconds,
        **viewer,
    )
    if not created:
        return ImpressionReport(record, False)
    return send_once(client=client, store=store, record=record, policy=policy, now=now)
