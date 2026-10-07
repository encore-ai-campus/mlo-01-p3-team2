"""테스트 데이터 도우미(작은 함수들). `factory_boy` 는 쓰지 않는다(계획 §6.0-8)."""
import io
import itertools
from datetime import datetime, timedelta, timezone

from foundation.models import User

PW = "Tr0ub4dor-horse-staple"
_counter = itertools.count(1)


def make_admin(username=None):
    return User.objects.create_superuser(username or f"admin_{next(_counter)}", PW, nickname="관리", class_label="-")


def make_advertiser(username=None):
    return User.objects.create_user(username or f"adv_{next(_counter)}", PW, nickname="광고주", class_label="1반")


NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def png_file(color=(200, 30, 30)):
    from tests import image_factory

    return io.BytesIO(image_factory.png_bytes(color=color))


def make_slot(admin, unit="IMPRESSION", floor=10, base=20, cap=50, name=None):
    from masters import api as masters

    media = masters.create_media(admin, f"매체-{next(_counter)}")
    return masters.create_slot(admin, media.media_id, name or f"슬롯-{next(_counter)}", unit, floor, base, cap, "초기")


class World:
    """광고주 한 명이 캠페인·광고그룹(입찰 30)·소재까지 가진 상태. 모든 호출은 고정 시각 NOW 기준."""

    def __init__(self, unit="IMPRESSION", with_creative=True, ends_in=10 * DAY):
        from campaigns import api as campaigns

        self.api = campaigns
        self.admin = make_admin()
        self.adv = make_advertiser()
        self.slot = make_slot(self.admin, unit=unit)
        self.campaign = campaigns.create_campaign(self.adv, "캠페인", NOW - DAY, None if ends_in is None else NOW + ends_in, 5000, now=NOW)
        self.group = campaigns.create_ad_group(self.adv, self.campaign.campaign_id, "그룹", unit, [self.slot.slot_id], bid_amount=30, now=NOW)
        self.creative = (
            campaigns.create_creative(self.adv, self.group.ad_group_id, "제목", "https://example.com/landing", png_file(), now=NOW)
            if with_creative else None
        )
