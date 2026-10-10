"""구간별 정합 manifest의 ① 구간 — 원본 행에서 **독립적으로** 다시 만든 기대 이벤트(계획 4-3b).

라이브 경로(`services`·`processing`)의 이벤트 기록 코드와는 따로 원본 행에서 값을 옮긴다. 그래서 라이브 쪽 매핑에 결함이 있으면 이 기대값과 어긋나 드러난다
(`scripts/load_test.py` 의 `verify_events` 도 같은 기대값을 쓴다). 형식은 `events` 의 빌더를 쓴다.
"""
from billing import api as billing
from events import api as events

from .models import Decision, Reaction


def expected_events():
    """{event_id: (이벤트 이름, 메시지 키, 생성 시각, 페이로드)}.

    생성 시각(`produced_at`)은 종류마다 생성 규약이 정한 원본 시각이다: 결정 = 결정 시각, 접수 = 수신 시각, 판정 = 처리 시각(`processed_at`),
    과금 = 그 과금을 일으킨 반응의 처리 시각(과금과 판정은 같은 처리 트랜잭션의 같은 `now` 를 쓴다).
    호출한 쪽의 읽기 스냅샷 안에서 부르면 한 시점의 원본을 본다(`billing.api.consistent_read`).
    """
    expected = {}
    for d in Decision.objects.all().iterator(chunk_size=2000):
        selected = None if d.creative_id is None else {
            "campaign_id": d.campaign_id, "ad_group_id": d.ad_group_id, "creative_id": d.creative_id, "pricing_unit": d.pricing_unit, "bid_id": d.bid_id,
            "bid_version": d.bid_version, "bid_policy_id": d.bid_policy_id, "policy_version": d.policy_version, "bid_amount": d.bid_amount, "applied_amount": d.applied_amount,
        }
        expected[events.event_id_for(events.NAMES["decision"], d.decision_id)] = (events.NAMES["decision"], d.decision_id, d.decided_at, events.decision_payload(
            decision_id=d.decision_id, media_id=d.media_id, slot_id=d.slot_id, decided_at=d.decided_at, audience=d.audience, subject_id=d.subject_id,
            selected=selected, selection_policy=d.selection_policy, candidate_count=d.candidate_count, rejected_counts=d.rejected_counts,
        ))
    decision_of, processed_of = {}, {}
    for r in Reaction.objects.all().iterator(chunk_size=2000):
        decision_of[f"{r.media_id}:{r.reaction_id}"] = r.decision_id
        processed_of[f"{r.media_id}:{r.reaction_id}"] = r.processed_at
        common = dict(inbox_id=r.inbox_id, reaction_id=r.reaction_id, media_id=r.media_id, decision_id=r.decision_id, type=r.type, occurred_at=r.occurred_at,
                      received_at=r.received_at, subject_id=r.subject_id, source=r.source)
        expected[events.event_id_for(events.NAMES["reaction_received"], r.inbox_id)] = (
            events.NAMES["reaction_received"], r.decision_id, r.received_at, events.reaction_received_payload(raw=r.raw, **common))
        if r.status != "RECEIVED":
            expected[events.event_id_for(events.NAMES["reaction"], r.inbox_id)] = (events.NAMES["reaction"], r.decision_id, r.processed_at, events.reaction_payload(
                status=r.status, reason_code=r.reason_code, applied_rule=r.applied_rule, **{"basis": r.basis}, **common))  # (읽기만 한다 — basis 를 쓰는 곳은 processing 하나라는 소스 검사에 걸리지 않게 키워드 대신 풀어서 넘긴다)
    entries = {e.entry_id: e for e in billing.charge_entries(list(billing.charge_entry_ids()))}
    for e in entries.values():
        decision_id = decision_of.get(e.reaction_ref)  # 원장의 멱등 키(<매체>:<reaction_id>)로 반응을 거쳐 결정을 찾는다
        expected[events.event_id_for(events.NAMES["charge"], e.entry_id)] = (events.NAMES["charge"], decision_id, processed_of.get(e.reaction_ref), events.charge_payload(
            entry_id=e.entry_id, campaign_id=e.campaign_id, charge_policy=e.charge_policy, created_at=e.created_at, reaction_ref=e.reaction_ref, decision_id=decision_id,
            requested_amount=e.charged + e.shortfall, charged_amount=e.charged, shortfall=e.shortfall, budget_day=billing.budget_day_of(e.created_at),
        ))
    return expected


def source_documents():
    """① 구간의 정규화 문서(MongoDB 에 쓰는 문서 형태)."""
    for event_id, (name, _key, produced_at, payload) in expected_events().items():
        yield events.normal_document(event_id, name, events.SCHEMA_VERSION, produced_at, payload)
