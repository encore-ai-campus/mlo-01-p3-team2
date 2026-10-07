"""후보 조립. **판정은 하지 않는다** — 각 모듈의 `api` 에서 사실을 모아 engine 의 `Candidate` 로 옮길 뿐이다(설계 §6.2).

질의는 모듈마다 한 번씩이라 후보 수와 무관하다(N+1 없음): 정책(masters) 1, 후보 사실(campaigns) 1, 잔액(billing) 1, 오늘 소진액(billing) 1.
"""
from billing import api as billing
from campaigns import api as campaigns
from engine.api import Candidate
from masters import api as masters


def assemble(slot, now):
    """`slot` 은 masters 의 SlotView(현재 정책 포함). 이 슬롯의 `Candidate` 목록을 돌려준다."""
    facts = campaigns.candidate_facts_for_slot(slot.slot_id)
    # 슬롯과 과금 단위가 다른 광고그룹은 후보가 아니다(서비스가 막아 두었지만 구조적 일관성을 한 번 더 확인한다)
    facts = [f for f in facts if f.pricing_unit == slot.pricing_unit]
    if not facts:
        return [], {}
    wallets = billing.balances({f.owner_id for f in facts})
    spent = billing.spend_today({f.campaign_id for f in facts}, now=now)
    policy = slot.policy
    return [
        Candidate(
            campaign_id=f.campaign_id, ad_group_id=f.ad_group_id, creative_id=f.creative_id, slot_id=f.slot_id,
            pricing_unit=f.pricing_unit, bid_amount=f.bid_amount, bid_version=f.bid_version, bid_created_at=f.bid_created_at,
            floor=policy.floor, base=policy.base, cap=policy.cap, policy_version=policy.policy_version,
            campaign_status=f.campaign_status, ad_group_enabled=f.ad_group_enabled, period_start=f.period_start,
            period_end=f.period_end, wallet_balance=wallets.get(f.owner_id, 0),
            remaining_daily_budget=max(0, f.daily_budget - spent.get(f.campaign_id, 0)),
        )
        for f in facts
    ], {f.creative_id: f for f in facts}
