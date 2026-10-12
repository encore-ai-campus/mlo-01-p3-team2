"""C2 이벤트의 모양(DRD §5.6). **이벤트 필드 이름과 형식은 이 파일에서만 정한다** — 호출하는 쪽(records·billing)은 값을 넘기기만 한다.

공통 봉투는 `event_id`·`event_name`·`schema_version`·`produced_at`·`payload` 이고, 여기서는 `payload` 를 만든다.
JSON 이므로 UUID 는 문자열, 시각은 UTC ISO 8601(`records/basis.py` 와 같은 형식)이다. 스키마가 바뀌면 `schema_version` 을 올린다.
"""
import uuid
from datetime import timezone

DECISION = "ad.decision"
REACTION_RECEIVED = "ad.reaction_received"
REACTION = "ad.reaction"
CHARGE = "ad.charge"
SCHEMA_VERSION = 1

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "events.ads-server")


def event_id_of(event_name, source_id):
    """원천 행의 ID(결정·수신함·원장 항목)와 이벤트 종류에서 결정적으로 만든 이벤트 ID. 재처리·재전송에도 같은 값이다."""
    return uuid.uuid5(_NAMESPACE, f"{event_name}/{source_id}")


def _id(value):
    return None if value is None else str(value)


def _iso(value):
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def decision_payload(*, decision_id, media_id, slot_id, decided_at, audience, subject_id, selected, selection_policy, candidate_count, rejected_counts):
    """`selected` 는 광고가 없으면 `None`, 아니면 선택된 광고의 스냅샷(dict). 광고주 계정(owner)은 싣지 않는다 — 파이프라인에 필요 없고 개인 연결 위험만 늘린다."""
    return {
        "decision_id": _id(decision_id), "media_id": _id(media_id), "slot_id": _id(slot_id), "decided_at": _iso(decided_at),
        "audience": audience, "subject_id": subject_id,
        "selected": None if selected is None else {
            "campaign_id": _id(selected["campaign_id"]), "ad_group_id": _id(selected["ad_group_id"]), "creative_id": _id(selected["creative_id"]),
            "pricing_unit": selected["pricing_unit"], "bid_id": _id(selected["bid_id"]), "bid_version": selected["bid_version"],
            "bid_policy_id": _id(selected["bid_policy_id"]), "policy_version": selected["policy_version"],
            "bid_amount": selected["bid_amount"], "applied_amount": selected["applied_amount"],
        },
        "selection_policy": selection_policy, "candidate_count": candidate_count, "rejected_counts": rejected_counts,
    }


def reaction_received_payload(*, inbox_id, reaction_id, media_id, decision_id, type, occurred_at, received_at, subject_id, source, raw):
    """접수: **보고된 사실만**. 판정 단위의 사람·슬롯 성격은 싣지 않는다(접수는 판정이 아니다)."""
    return {
        "inbox_id": _id(inbox_id), "reaction_id": _id(reaction_id), "media_id": _id(media_id), "decision_id": _id(decision_id),
        "type": type, "occurred_at": _iso(occurred_at), "received_at": _iso(received_at), "subject_id": subject_id, "source": source, "raw": raw,
    }


def reaction_payload(*, inbox_id, reaction_id, media_id, decision_id, type, occurred_at, received_at, subject_id, source, status, reason_code, applied_rule, basis):
    """판정: 확인한 사실. 판정 단위의 사람(`person_id`)·슬롯 성격(`audience`)은 **`basis` 에서 읽는다**(판정 시점의 스냅샷이 유일한 원본)."""
    return {
        "inbox_id": _id(inbox_id), "reaction_id": _id(reaction_id), "media_id": _id(media_id), "decision_id": _id(decision_id),
        "type": type, "occurred_at": _iso(occurred_at), "received_at": _iso(received_at),
        "subject_id": subject_id, "person_id": basis.get("person"), "source": source, "audience": basis.get("audience"),
        "status": status, "reason_code": reason_code, "applied_rule": applied_rule, "basis": basis,
    }


def charge_payload(*, entry_id, campaign_id, charge_policy, created_at, reaction_ref, decision_id, requested_amount, charged_amount, shortfall, budget_day):
    """과금: 원장 `CHARGE` 한 줄. 지갑 잔액·광고주 계정 정보는 싣지 않는다."""
    return {
        "entry_id": _id(entry_id), "campaign_id": _id(campaign_id), "charge_policy": charge_policy, "created_at": _iso(created_at),
        "reaction_ref": reaction_ref, "decision_id": _id(decision_id), "requested_amount": requested_amount, "charged_amount": charged_amount,
        "shortfall": shortfall, "budget_day": budget_day.isoformat(),
    }
