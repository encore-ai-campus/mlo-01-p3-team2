"""게임 프레임워크에 의존하지 않는 광고 응답 값."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ad:
    creative_id: str
    title: str
    image_url: str
    redirect_url: str
    click_url: str


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: str
    slot_id: str
    slot_name: str
    audience: str
    decided_at: str
    ad: Ad | None
    request_id: str | None


@dataclass(frozen=True, slots=True)
class Reaction:
    """반응 접수 결과. ACCEPTED도 차감 금액이나 잔액을 뜻하지 않는다."""

    reaction_id: str
    decision_id: str
    subject_id: str | None
    type: str
    occurred_at: str
    received_at: str
    status: str
    reason_code: str | None
    request_id: str | None
