"""백엔드와 프론트(apps/ads_frontend)가 어긋나지 않는지(설계 §6.6 "6-15 분리"). 프론트는 백엔드 코드를 가져오지 않으므로 같은 것을 데이터로 따로 갖는다 —
경로·URL 이름(`ui/routes.py`), 화면 이름표(`ui/labels.py`), KST 표시(`ui/templatetags/kst.py`, 백엔드 Django admin 도 쓴다). 화면 데이터는 그 밖의 값이
새지 않게 막는다."""
import re
from datetime import datetime, timezone

from django import forms
from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from billing.api import EntryType
from campaigns.api import CampaignStatus, ReviewStatus
from console import urls as console_urls
from console.operator import urls as operator_urls
from foundation.api import present
from foundation.models import User
from foundation.presentation import to_data
from foundation.templatetags.kst import kst as backend_kst
from masters.api import Audience
from tests.factories import PW, World
from tests.presentation import PresentationClient, rendering  # noqa: F401 — rendering: 프론트 경로를 sys.path 에 둔다
from ui import labels, routes
from ui.templatetags.kst import kst as frontend_kst

TOKEN = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


def table(urlpatterns):
    return sorted((p.pattern._route, p.name) for p in urlpatterns)


class FrontendSyncTests(SimpleTestCase):
    def test_frontend_routes_match_the_backend(self):
        """프론트의 경로 표 = 백엔드의 콘솔·운영 경로(양쪽 모두 빠짐없이), 관리 사이트는 관리 템플릿이 거는 이름의 경로가 같다."""
        self.assertEqual(sorted(routes.CONSOLE), table(console_urls.urlpatterns))
        self.assertEqual(sorted(routes.OPERATOR), table(operator_urls.urlpatterns))
        site = {p.name: str(p.pattern) for p in admin.site.get_urls() if getattr(p, "name", None)}  # 모델별 하위 경로(URLResolver)는 이름이 없다
        for route, name in routes.ADMIN:
            self.assertEqual(site[name], route, name)

    def test_frontend_labels_match_the_backend_choices(self):
        for data, choices in ((labels.AUDIENCES, Audience), (labels.CAMPAIGN_STATUSES, CampaignStatus), (labels.ENTRY_TYPES, EntryType),
                              (labels.REVIEW_STATUSES, ReviewStatus)):
            self.assertEqual(data, {k: str(v) for k, v in choices.choices}, choices.__name__)

    def test_the_frontend_and_backend_show_the_same_kst_time(self):
        for value in (datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc), datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)):
            self.assertEqual(frontend_kst(value), backend_kst(value))
            self.assertEqual(frontend_kst(value, "%Y-%m-%d"), backend_kst(value, "%Y-%m-%d"))


class PresentationDataTests(TestCase):
    def test_only_plain_values_go_out(self):
        """ORM 객체 같은 것은 화면 데이터로 새지 않는다(§6.6 규칙 4) — 실수하면 바로 오류다."""
        with self.assertRaises(TypeError):
            to_data(User(username="x"))
        with self.assertRaises(TypeError):
            to_data(object())

    def test_passwords_and_uploaded_files_are_never_sent_back(self):
        class Form(forms.Form):
            password = forms.CharField(widget=forms.PasswordInput)
            image = forms.FileField()

        from django.core.files.uploadedfile import SimpleUploadedFile

        form = Form({"password": "secret-value"}, {"image": SimpleUploadedFile("x.png", b"data")})
        form.is_valid()
        fields = {f["name"]: f["value"] for f in to_data(form)["$form"]["fields"]}
        self.assertEqual(fields, {"password": None, "image": None})

    def test_an_error_screen_sets_no_csrf_cookie(self):
        """오류 화면에는 폼이 없다 — 이미지 경로의 404 도 쿠키를 심지 않는다(계약 C3)."""
        request = RequestFactory().get("/assets/missing.png")
        response = present(request, "foundation/error.html", {"status": 404, "title": "t", "message": "m"}, status=404, csrf=False)
        self.assertNotIn("CSRF_COOKIE", request.META)
        self.assertEqual(response.status_code, 404)


class CsrfThroughTheFrontendTests(TestCase):
    """CSRF 검사를 켠 채, 프론트처럼 그린 화면의 토큰으로 로그인·폼 제출이 통과한다(6-15e — 렌더러가 프론트 요청으로 토큰을 새로 만들어
    백엔드의 토큰을 덮던 결함을 브라우저 점검에서 찾았다)."""

    def test_the_token_in_a_drawn_form_passes_the_backends_csrf_check(self):
        w = World(ends_in=None)
        client = PresentationClient(enforce_csrf_checks=True)
        token = TOKEN.search(client.get(reverse("login")).content.decode()).group(1)
        r = client.post(reverse("login"), {"username": w.adv.username, "password": PW, "csrfmiddlewaretoken": token})
        self.assertEqual(r.status_code, 302)
        detail = reverse("ad_group_detail", args=[w.group.ad_group_id])
        token = TOKEN.search(client.get(detail).content.decode()).group(1)
        r = client.post(reverse("ad_group_bid", args=[w.group.ad_group_id]), {"amount": "350", "expected_version": "1", "csrfmiddlewaretoken": token})
        self.assertRedirects(r, detail)
