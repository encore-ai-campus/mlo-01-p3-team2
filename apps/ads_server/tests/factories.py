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
SHARES = {"impression_share": 98, "click_share": 1, "conversion_share": 1}  # 입찰 정책의 반응 유형별 과금 비율(6-10b) — 시험 기본값
SUBJECT = "0197a5c0-0000-7000-8000-000000000001"  # 개인(individual) 슬롯의 결정에 쓰는 가명 UUID


def at(seconds):
    """`NOW` 에서 `seconds` 초 뒤."""
    return NOW + timedelta(seconds=seconds)


def utc(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def png_file(color=(200, 30, 30)):
    from tests import image_factory

    return io.BytesIO(image_factory.png_bytes(color=color))


def make_slot(admin, unit="IMPRESSION", floor=10, base=20, cap=50, name=None):
    from masters import api as masters

    media = masters.create_media(admin, f"매체-{next(_counter)}")
    return masters.create_slot(admin, media.media_id, name or f"슬롯-{next(_counter)}", unit, floor, base, cap, "초기", **SHARES)


class World:
    """광고주 한 명이 캠페인·광고그룹(입찰 30)·소재까지 가진 상태. 모든 호출은 고정 시각 NOW 기준."""

    def __init__(self, unit="IMPRESSION", with_creative=True, ends_in=10 * DAY):
        from billing import api as billing
        from campaigns import api as campaigns

        self.api = campaigns
        self.admin = make_admin()
        self.adv = make_advertiser()
        billing.grant_signup(self.adv, now=NOW)  # 가입하면 지급된다(기본 50,000)
        self.slot = make_slot(self.admin, unit=unit)
        self.campaign = campaigns.create_campaign(self.adv, "캠페인", NOW - DAY, None if ends_in is None else NOW + ends_in, 5000, now=NOW)
        self.group = campaigns.create_ad_group(self.adv, self.campaign.campaign_id, "그룹", unit, [self.slot.slot_id], bid_amount=30, now=NOW)
        self.creative = (
            campaigns.create_creative(self.adv, self.group.ad_group_id, "제목", "https://example.com/landing", png_file(), now=NOW)
            if with_creative else None
        )


def media_api(test):
    """매체 API 시험 준비: 요청 제한 버킷을 비우고(끝나면 다시), 세계 하나와 그 매체의 키를 만들고, 결정 시각을 `NOW` 로 고정한다. (세계, 키)를 돌려준다."""
    from unittest import mock

    from masters import api as masters
    from serving_api.throttle import buckets

    buckets.reset()
    test.addCleanup(buckets.reset)
    w = World()
    key = masters.issue_media_key(w.admin, w.slot.media_id).key
    test.enterContext(mock.patch("records.services._now", lambda now=None: now or NOW))  # 후보 광고의 기간(NOW 기준)이 맞도록
    return w, key


def impression(world, when, slot=None):
    """`when` 에 결정, 1초 뒤 노출 수신·인정(입찰이 과금된다)."""
    import uuid
    from random import Random

    from records import api as records

    slot = slot or world.slot
    later = when + timedelta(seconds=1)
    decision = records.decide(slot.media_id, slot.slot_id, subject_id=SUBJECT, now=when, rng=Random(1))
    view, _ = records.receive_reaction(decision.media_id, decision.decision_id, uuid.uuid4(), "IMPRESSION", later, {}, now=later)
    assert records.process_reaction(view.inbox_id, now=later) == "ACCEPTED"
