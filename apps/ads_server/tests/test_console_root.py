from django.test import TestCase

from tests.factories import make_advertiser


class RootRedirectTests(TestCase):
    def test_anonymous_root_goes_to_login(self):
        r = self.client.get("/")
        self.assertRedirects(r, "/accounts/login/", fetch_redirect_response=False)  # 임시 이동(302)

    def test_query_is_not_forwarded(self):
        self.assertEqual(self.client.get("/?next=/admin/").headers["Location"], "/accounts/login/")

    def test_logged_in_advertiser_ends_up_on_the_advertiser_home(self):
        self.client.force_login(make_advertiser())
        r = self.client.get("/", follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/advertiser/")
        self.assertEqual(r.status_code, 200)

    def test_post_also_redirects_and_changes_nothing(self):
        self.assertEqual(self.client.post("/").status_code, 302)  # RedirectView 는 POST 도 같은 곳으로 보낸다(상태 변경 없음)
