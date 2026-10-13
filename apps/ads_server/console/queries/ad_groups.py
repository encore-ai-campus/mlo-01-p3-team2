"""광고그룹 상세 화면용 조립(Step 3-2d — 각 서비스 `api` 의 값을 합치기만 한다)."""
from dataclasses import dataclass

from campaigns import api as campaigns
from masters import api as masters


@dataclass(frozen=True)
class AdGroupPage:
    group: object  # AdGroupView
    campaign_name: str  # 속한 캠페인(소유는 `get_ad_group` 이 확인했다 — 이름만 읽는다)
    bids: list  # BidView, 최신 버전부터
    images: list  # CreativeView — 고를 수 있는 내 이미지(보관하지 않은 소재 전부)와, 보관했어도 지금 선택된 것(6-11: 화면은 고르기만 한다)
    linked: dict  # {slot_id: SlotView} 지금 고른 위치(꺼진 위치 포함)
    choices: list  # 고를 수 있는 위치(켜진 것 — 과금 단위는 없다, 6-10d)
    effects: tuple  # 현재 입찰의 위치별 결과(SlotEffect), 입찰이 없으면 빈 튜플

    @property
    def inactive_linked(self):
        """고른 위치 중 지금 꺼진 것(위치를 다시 저장하면 빠진다 — 서비스는 꺼진 위치를 고를 수 없게 한다)."""
        chosen = {str(s.slot_id) for s in self.choices}
        return [s for slot_id, s in self.linked.items() if str(slot_id) not in chosen]


def ad_group_page(user, ad_group_id):
    """남의 광고그룹은 서비스가 404."""
    group = campaigns.get_ad_group(user, ad_group_id)
    linked = masters.get_slots_with_policy(group.slot_ids)
    effects = campaigns.bid_effects(group.current_bid.amount, list(group.slot_ids), slots=linked) if group.current_bid else ()  # 위치 정보와 같은 읽기
    images = [o.creative for o in campaigns.list_owned_creatives(user)]
    if group.creative_id is not None and group.creative_id not in {c.creative_id for c in images}:
        images.insert(0, campaigns.get_creative(user, group.creative_id))  # 보관한 소재가 아직 선택돼 있으면(끝난 캠페인) 그것도 보인다
    return AdGroupPage(
        group=group, campaign_name=campaigns.campaign_names([group.campaign_id])[group.campaign_id], bids=campaigns.list_bids(user, group.ad_group_id),
        images=images, linked=linked,
        choices=masters.list_slots(active_only=True), effects=effects,
    )
