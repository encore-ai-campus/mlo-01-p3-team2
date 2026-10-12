"""광고 결정을 요청하고 소유권 저장이 끝난 결과만 호출자에게 반환한다."""

from ..api.types import Decision


def create_decision(*, client, store, slot_id, subject_id) -> Decision:
    decision = client.create_decision(slot_id=slot_id, subject_id=subject_id)
    # 기록에 실패하면 광고를 반환하지 않는다. 광고 없음도 발급 기록으로 보관한다.
    store.remember_decision(decision, subject_id)
    return decision
