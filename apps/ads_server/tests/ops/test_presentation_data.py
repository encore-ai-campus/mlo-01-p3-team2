"""화면 데이터(설계 §6.6 "6-15 분리"): 백엔드가 프론트에 보내는 값은 평범한 값뿐이고 비밀번호·올린 파일은 돌려보내지 않으며, 오류 화면은 세션을
건드리지 않는다. 프론트처럼 그린 화면의 CSRF 토큰은 백엔드 검사를 통과한다(6-18e 에서 test_frontend_sync 에서 나눔 — 제품 동작이라 운영용)."""
import re

from django import forms
from django.test import RequestFactory, TestCase
from django.urls import reverse

from foundation.api import present
from foundation.models import User
from foundation.presentation import to_data
from tests.support.factories import PW, World
from tests.support.presentation import PresentationClient

TOKEN = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


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
        response = present(request, "foundation/error.html", {"status": 404, "title": "t", "message": "m"}, status=404, session=False)
        self.assertNotIn("CSRF_COOKIE", request.META)
        self.assertEqual(response.status_code, 404)

    def test_an_error_screen_leaves_the_session_and_its_messages_alone(self):
        """6-16e(E4): 6-15c 뒤 오류 화면이 사용자·메시지를 읽어, 그 사이의 404 가 세션을 건드리고(`Vary: Cookie`·`Set-Cookie`) 다음 화면에 보일
        안내 메시지를 먹었다. 분리 전처럼 오류 화면은 제목·문구만 싣는다 — DB 장애의 500 이 세션을 읽다 다시 실패할 일도 없다."""
        w = World(ends_in=None)
        self.client.force_login(w.adv)
        key = re.search(r'name="request_key" value="([^"]+)"', self.client.get(reverse("campaign_create")).content.decode()).group(1)
        made = self.client.post(reverse("campaign_create"), {"request_key": key, "name": "메시지 캠페인", "starts_at": "2026-10-01T09:00",
                                                            "ends_at": "", "daily_budget": "3000"})
        self.assertEqual(made.status_code, 302)  # 안내 메시지를 남기고 다음 화면으로
        missing = {path: self.client.get(path) for path in ("/nowhere/", "/advertiser/nowhere/")}
        for path, r in missing.items():
            self.assertEqual((r.status_code, list(r.cookies)), (404, []), path)
        # 로그인 확인이 없는 경로는 세션을 읽지 않는다(/advertiser/ 아래는 역할 확인이 로그인 여부를 보느라 읽는다 — 응답이 쿠키에 따라 달라 Vary: Cookie 가 맞다)
        self.assertNotIn("Cookie", missing["/nowhere/"].get("Vary", ""))
        self.assertContains(self.client.get(made["Location"]), "캠페인을 만들었습니다")  # 메시지는 다음 화면에 그대로

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
