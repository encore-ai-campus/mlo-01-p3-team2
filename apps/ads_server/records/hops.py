"""구간별 정합 manifest의 ① 구간 — 원본 행에서 **독립적으로** 다시 만든 기대 이벤트(계획 4-3b).

라이브 경로(`services`·`processing`)의 이벤트 기록 코드와는 따로 원본 행에서 값을 옮긴다. 그래서 라이브 쪽 매핑에 결함이 있으면 이 기대값과 어긋나 드러난다
(`tests/tools/load_test.py` 의 `verify_events` 도 같은 기대값을 쓴다). 형식은 `events` 의 빌더를 쓴다.

생성 시각(`produced_at`)은 종류마다 생성 규약이 정한 원본 시각이다: 결정 = 결정 시각, 접수 = 수신 시각, 판정 = 처리 시각(`processed_at`),
과금 = 그 과금을 일으킨 반응의 처리 시각(과금과 판정은 같은 처리 트랜잭션의 같은 `now` 를 쓴다).
"""
from functools import reduce
from operator import or_

from django.db.models import Q

from billing import api as billing
from events import api as events

from .models import Decision, Reaction, charge_shares
from .processing import parse_reaction_ref, reaction_ref


def expected_events():
    """{event_id: (이벤트 이름, 메시지 키, 생성 시각, 페이로드)} — 전부 메모리에 만든다(부하 검사기의 전수 대조용). 구간 manifest 는 `source_streams` 로 창마다 읽는다.
    호출한 쪽의 읽기 스냅샷 안에서 부르면 한 시점의 원본을 본다(`billing.api.consistent_read`).
    """
    expected = dict(_decision_event(d) for d in Decision.objects.all().iterator(chunk_size=2000))
    reactions = {}
    for r in Reaction.objects.all().iterator(chunk_size=2000):
        reactions[reaction_ref(r.media_id, r.reaction_id)] = (r.decision_id, r.processed_at)  # 원장의 멱등 키와 같은 형식(형식 도우미만 같이 쓰고, 기대 이벤트 매핑은 따로 만든다)
        expected.update([_received_event(r)] + ([_judged_event(r)] if r.status != "RECEIVED" else []))
    for e in billing.charge_entries(billing.charge_entry_ids()):
        expected.update([_charge_event(e, *reactions.get(e.reaction_ref, (None, None)))])  # 원장의 멱등 키(<매체>:<reaction_id>)로 반응을 거쳐 결정을 찾는다
    return expected


def source_streams():
    """① 구간을 창으로 읽는 흐름(`events.summarize_windows` 용, 외부 검토 00d3067 P3-3). `expected_events` 와 같은 매핑을 창 하나·종류 하나씩 적용한다:
    결정(결정 시각) / 접수(수신 시각) / 판정과 그 과금(처리 시각). 호출한 쪽의 읽기 스냅샷 안에서 쓴다."""
    return [
        events.table_stream(Decision.objects.all(), "decided_at", lambda rows: [_document(_decision_event(d)) for d in rows]),
        events.table_stream(Reaction.objects.all(), "received_at", lambda rows: [_document(_received_event(r)) for r in rows]),
        events.table_stream(Reaction.objects.filter(processed_at__isnull=False), "processed_at", _judged_documents),  # 판정한 반응 = 처리 시각이 있는 반응(DB 제약)
    ]


def _judged_documents(rows):
    """판정한 반응과 그 과금. 과금의 생성 시각은 그 반응의 처리 시각이라 같은 창이다 — 창의 반응으로 원장의 과금 줄을 찾는다(멱등 키).
    반응이 없는 과금 줄(있으면 안 된다)은 여기서 보이지 않는다. 예전에는 생성 시각이 없어 내보내기가 멈췄다."""
    rows = list(rows)
    reactions = {reaction_ref(r.media_id, r.reaction_id): r for r in rows}
    docs = [_document(_judged_event(r)) for r in rows]
    for e in billing.charge_entries_for(list(reactions)):
        docs.append(_document(_charge_event(e, reactions[e.reaction_ref].decision_id, reactions[e.reaction_ref].processed_at)))
    return docs


def unresolved_charges(batch=2000, examples=10):
    """창에 놓을 수 없는 과금 원장 줄 — 멱등 키(`reaction_ref`)로 **판정한 반응**을 찾지 못한 `CHARGE` 항목(반응이 없음·판정 전·표준 표기가 아닌 키).
    과금 이벤트의 생성 시각은 그 반응의 처리 시각이라 이런 줄은 원본 구간의 어느 창에도 넣을 수 없고, `source_streams` 는 반응에서 과금을 찾으므로 조용히 빠진다.
    원장 시각으로 추정하지 않고 따로 센다(외부 검토 e781f20 P2). 원장을 ID 순으로 이어 읽어 메모리는 한 묶음만 쓴다. 반환: (건수, 예시 entry_id 최대 `examples`개)."""
    count, sample, after = 0, [], None
    while rows := billing.charge_refs_after(after, batch):
        after = rows[-1][0]
        keys = {entry_id: parse_reaction_ref(ref) for entry_id, ref in rows}  # 원본 구간과 같은 동일성: 반응에서 만든 표준 문자열과 정확히 같은 키
        by_media = {}
        for media_id, reaction_id in filter(None, keys.values()):
            by_media.setdefault(media_id, set()).add(reaction_id)
        pairs = reduce(or_, (Q(media_id=m, reaction_id__in=ids) for m, ids in by_media.items()), Q(pk__in=[]))  # 정확한 쌍만(교차 조합이 아니다 — 행 수 ≤ 묶음)
        judged = set(Reaction.objects.filter(pairs, processed_at__isnull=False).values_list("media_id", "reaction_id")) if by_media else set()
        for entry_id, key in keys.items():
            if key not in judged:
                count += 1
                if len(sample) < examples:
                    sample.append(str(entry_id))
    return count, sample


def _document(item):
    event_id, (name, _key, produced_at, payload) = item
    return events.normal_document(event_id, name, events.SCHEMA_VERSIONS[name], produced_at, payload)


def _decision_event(d):
    name = events.NAMES["decision"]
    selected = None if d.creative_id is None else {
        "campaign_id": d.campaign_id, "ad_group_id": d.ad_group_id, "creative_id": d.creative_id, "charge_shares": charge_shares(d), "bid_id": d.bid_id,
        "bid_version": d.bid_version, "bid_policy_id": d.bid_policy_id, "policy_version": d.policy_version, "bid_amount": d.bid_amount, "applied_amount": d.applied_amount,
    }
    return events.event_id_for(name, d.decision_id), (name, d.decision_id, d.decided_at, events.decision_payload(
        decision_id=d.decision_id, media_id=d.media_id, slot_id=d.slot_id, decided_at=d.decided_at, audience=d.audience, subject_id=d.subject_id,
        selected=selected, selection_policy=d.selection_policy, candidate_count=d.candidate_count, rejected_counts=d.rejected_counts,
    ))


def _common(r):
    return dict(inbox_id=r.inbox_id, reaction_id=r.reaction_id, media_id=r.media_id, decision_id=r.decision_id, type=r.type, occurred_at=r.occurred_at,
                received_at=r.received_at, subject_id=r.subject_id, source=r.source)


def _received_event(r):
    name = events.NAMES["reaction_received"]
    return events.event_id_for(name, r.inbox_id), (name, r.decision_id, r.received_at, events.reaction_received_payload(raw=r.raw, **_common(r)))


def _judged_event(r):
    name = events.NAMES["reaction"]
    return events.event_id_for(name, r.inbox_id), (name, r.decision_id, r.processed_at, events.reaction_payload(
        status=r.status, reason_code=r.reason_code, applied_rule=r.applied_rule, basis=r.basis, **_common(r)))


def _charge_event(e, decision_id, processed_at):
    name = events.NAMES["charge"]
    return events.event_id_for(name, e.entry_id), (name, decision_id, processed_at, events.charge_payload(
        entry_id=e.entry_id, campaign_id=e.campaign_id, charge_policy=e.charge_policy, created_at=e.created_at, reaction_ref=e.reaction_ref, decision_id=decision_id,
        requested_amount=e.charged + e.shortfall, charged_amount=e.charged, shortfall=e.shortfall, budget_day=billing.budget_day_of(e.created_at),
    ))
