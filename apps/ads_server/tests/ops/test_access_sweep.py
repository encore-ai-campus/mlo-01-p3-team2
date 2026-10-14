"""Step 3-3 접근 제어 전수: 화면 경로를 **모두** 실제 값으로 채워 역할마다 GET·POST 를 보낸다(관리자 ↔ 광고주 상호 차단, 익명 리다이렉트).

`test_access.UrlSweepTests` 는 모든 URL 이 역할 접두사 아래이거나 공개로 표시됐는지(정적) 보고, 여기서는 그 접두사가 **실제로** 막는지 본다.
새 경로를 더하면 이 시험이 자동으로 함께 돈다(경로 목록을 손으로 적지 않는다).
"""
import uuid

from django.conf import settings
from django.test import TestCase, tag
from django.urls import reverse

from tests.support.factories import make_admin, make_advertiser
from tests.support.helpers import ROUTE_PARAM, every_route


def concrete(route):
    """`<str:campaign_id>` 같은 자리를 실제 값으로 채운다(UUID — 남의·없는 객체와 같은 모양). 정규식 경로는 None."""
    def fill(match):
        return "0" * 64 + ".png" if match.group(1) == "asset_name" else str(uuid.uuid4())
    return "/" + ROUTE_PARAM.sub(fill, route)


def under(prefix):
    paths = sorted({concrete(r) for r in every_route() if concrete(r).startswith(prefix)})
    assert paths, prefix  # 공회전이 아니다
    return paths


@tag("security")
class AccessSweepTests(TestCase):
    def setUp(self):
        self.admin, self.adv = make_admin(), make_advertiser()
        self.advertiser_paths = under("/advertiser/")
        self.admin_paths = under("/" + settings.ADMIN_URL_PATH)

    def as_user(self, user):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)

    def test_advertiser_pages_send_anonymous_to_login_and_refuse_admins(self):
        for path in self.advertiser_paths:
            for method in (self.client.get, self.client.post):
                self.as_user(None)
                r = method(path)
                self.assertEqual(r.status_code, 302, path)
                self.assertTrue(r["Location"].startswith(reverse("login") + "?next="), path)
                self.as_user(self.admin)
                self.assertEqual(method(path).status_code, 403, path)  # 관리자도 광고주 화면은 못 쓴다

    def test_admin_pages_are_hidden_from_anonymous_and_advertisers(self):
        for path in self.admin_paths:
            for user in (None, self.adv):
                self.as_user(user)
                self.assertEqual(self.client.get(path).status_code, 404, path)
                self.assertEqual(self.client.post(path).status_code, 404, path)  # 쓰기도 존재를 숨긴다

    def test_the_sweep_covers_the_screens(self):
        """공회전 방지: 광고주 화면과 운영 화면의 주요 경로가 실제로 목록에 있다."""
        for fragment in ("/campaigns/", "/ad-groups/", "/creatives/", "/ads/new/", "/points/", "/me/"):
            self.assertTrue(any(fragment in p for p in self.advertiser_paths), fragment)
        for fragment in ("operator/media/", "operator/campaigns/", "operator/reviews/", "operator/advertisers/", "foundation/user/"):
            self.assertTrue(any(fragment in p for p in self.admin_paths), fragment)
