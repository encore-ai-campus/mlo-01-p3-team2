"""광고 결정을 요청하고 소유권 저장이 끝난 결과만 호출자에게 반환한다."""

from ..api.types import Decision


def create_decision(*, client, store, slot_id, subject_id=None, owner_id=None) -> Decision:
    # 공유 요청은 두 식별자를 모두 생략하고, 개인 요청은 둘 다 준비한 뒤 발급한다.
    if (subject_id is None) != (owner_id is None):
        raise ValueError("개인 광고는 사용자와 가명이 모두 필요하며, 공유 광고는 둘 다 생략합니다.")
    decision = client.create_decision(slot_id=slot_id, subject_id=subject_id)
    # 기록에 실패하면 광고를 반환하지 않는다. 광고 없음도 발급 기록으로 보관한다.
    # 내부 소유자 UUID는 저장소에만 전달하고 광고 서버 요청에는 넣지 않는다.
    store.remember_decision(decision, subject_id, owner_id=owner_id)
    return decision
