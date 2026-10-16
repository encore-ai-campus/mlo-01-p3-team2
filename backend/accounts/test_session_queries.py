"""HTTP 요청 하나에서는 세션 확인을 한 번만 한다(계획 docs/metaverse-optimization-plan.md 4e).
미들웨어가 구한 상태(`request.campus_session_status`)를 화면 데이터·세션 상태 응답이 다시 쓴다. 활동 POST 는 기록(touch)해야 하므로 그대로다."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from . import session_policy, session_views
from .models import Profile


class OneSessionCheckPerRequestTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="one-check")
        Profile.objects.create(user=user, nickname="한 번 확인", cohort="mlo-1", setup_complete=True)
        self.client.force_login(user)

    def count(self, request):
        calls = []
        original = session_policy.check_session

        def counting(*args, **kwargs):
            calls.append(kwargs.get("touch", False))
            return original(*args, **kwargs)

        with patch.object(session_policy, "check_session", counting), patch.object(session_views, "check_session", counting):
            response = request()
        return response, calls

    def test_session_status_checks_once(self):
        response, calls = self.count(lambda: self.client.get("/accounts/session/status/"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertEqual(calls, [False])

    def test_a_page_with_session_data_checks_once(self):
        response, calls = self.count(lambda: self.client.get("/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls.count(False), 1)

    def test_activity_still_records(self):
        response, calls = self.count(lambda: self.client.post("/accounts/session/activity/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(True, calls)
