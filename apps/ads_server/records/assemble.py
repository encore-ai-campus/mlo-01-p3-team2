"""후보 조립. **판정은 하지 않는다** — 각 모듈의 `api` 에서 사실을 모아 engine 의 `Candidate` 로 옮길 뿐이다(설계 §6.2).

질의는 모듈마다 한 번씩이라 후보 수와 무관하다(N+1 없음): 정책(masters) 1, 후보 사실(campaigns) 1, 잔액(billing) 1, 오늘 소진액(billing) 1.
"""
from billing import api as billing
from campaigns import api as campaigns
from engine.api import Candidate


def assemble(slot, now):
    """`slot` 은 masters 의 SlotView(현재 정책 포함). 이 슬롯의 `Candidate` 목록과 광고그룹 ID 별 후보 사실을 돌려준다.
    광고그룹으로 묶는다 — 한 소재를 여러 광고그룹이 고를 수 있어(6-9) 소재로 묶으면 서로 덮인다(6-16d)."""
    facts = campaigns.candidate_facts_for_slot(slot.slot_id)
    if not facts:
        return [], {}
    wallets = billing.balances({f.owner_id for f in facts})
    spent = billing.spend_today({f.campaign_id for f in facts}, now=now)
    policy = slot.policy
    return [
        Candidate(
            campaign_id=f.campaign_id, ad_group_id=f.ad_group_id, creative_id=f.creative_id, slot_id=f.slot_id,
            bid_amount=f.bid_amount, bid_version=f.bid_version,
            floor=policy.floor, cap=policy.cap, policy_version=policy.policy_version,
            campaign_status=f.campaign_status, ad_group_enabled=f.ad_group_enabled, period_start=f.period_start,
            period_end=f.period_end, wallet_balance=wallets.get(f.owner_id, 0),
            remaining_daily_budget=max(0, f.daily_budget - spent.get(f.campaign_id, 0)),
        )
        for f in facts
    ], {f.ad_group_id: f for f in facts}
