"""광고그룹 상세 화면용 조립(Step 3-2d — 각 서비스 `api` 의 값을 합치기만 한다)."""
from dataclasses import dataclass

from campaigns import api as campaigns
from masters import api as masters


@dataclass(frozen=True)
class AdGroupPage:
    group: object  # AdGroupView
    campaign: object  # CampaignView
    bids: list  # BidView, 최신 버전부터
    creatives: list  # CreativeView
    linked: dict  # {slot_id: SlotView} 지금 고른 위치(꺼진 위치 포함)
    choices: list  # 고를 수 있는 위치(켜져 있고 단위가 같은 것)
    effects: tuple  # 현재 입찰의 위치별 결과(SlotEffect), 입찰이 없으면 빈 튜플

    @property
    def inactive_linked(self):
        """고른 위치 중 지금 꺼진 것(위치를 다시 저장하면 빠진다 — 서비스는 꺼진 위치를 고를 수 없게 한다)."""
        chosen = {str(s.slot_id) for s in self.choices}
        return [s for slot_id, s in self.linked.items() if str(slot_id) not in chosen]


def ad_group_page(user, ad_group_id):
    """남의 광고그룹은 서비스가 404."""
    group = campaigns.get_ad_group(user, ad_group_id)
    effects = campaigns.bid_effects(group.current_bid.amount, list(group.slot_ids)) if group.current_bid else ()
    return AdGroupPage(
        group=group, campaign=campaigns.get_campaign(user, group.campaign_id), bids=campaigns.list_bids(user, group.ad_group_id),
        creatives=campaigns.list_creatives(user, group.ad_group_id), linked=masters.get_slots_with_policy(group.slot_ids),
        choices=[s for s in masters.list_slots(active_only=True) if s.pricing_unit == group.pricing_unit], effects=effects,
    )
