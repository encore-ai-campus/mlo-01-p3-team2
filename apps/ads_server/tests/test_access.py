import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.test import SimpleTestCase, TestCase, override_settings, tag
from django.urls import URLResolver, get_resolver, reverse
from django.urls.resolvers import RoutePattern

from config.access_map import validate_admin_path
from foundation.api import owned_or_404, owned_queryset
from foundation.models import User
from tests.helpers import PROD_ENV, run_python
from tests.support_app.models import OwnedThing

PW = "Tr0ub4dor-horse-staple"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"

# 새 공개 뷰나 "로그인만 필요" 뷰를 추가하면 **여기도 고쳐야 한다**(리뷰 지점).
EXPECTED_PUBLIC = {
    "/accounts/signup/", "/accounts/login/", "/assets/<asset_name:name>",
    "/",  # 루트 주소 → 역할의 첫 화면(익명은 로그인 화면)으로 이동(내용 없음)
    # 매체 API(C1): 세션 로그인이 아니라 `X-Media-Key` 로 인증한다(`media_endpoint`). health 는 인증 없음
    "/api/media/v1/health", "/api/media/v1/decisions", "/api/media/v1/decisions/<str:decision_id>",
    "/api/media/v1/decisions/<str:decision_id>/reactions/<str:reaction_id>",
    "/c/<str:token>",  # 클릭 관측(C1 v1.1): 최종 사용자 브라우저가 연다. 서명 토큰이 곧 자격이다
}
LOGIN_ONLY = {"/accounts/logout/"}  # 로그인은 필요하지만 역할은 무관


def iter_routes(patterns, prefix=""):
    """URL 설정을 순회해 (전체 경로, 콜백) 을 낸다. 역할 접두사 아래(관리자 사이트)는 내려가지 않는다."""
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            if any(("/" + route).startswith(r["prefix"]) for r in settings.ACCESS_MAP):
                yield "/" + route, None  # 역할 접두사로 통째로 보호되는 하위 사이트(관리자 사이트)
                continue
            yield from iter_routes(p.url_patterns, route)
        else:
            assert isinstance(p.pattern, RoutePattern), f"정규식 URL 은 허용하지 않는다: {route}"
            yield "/" + route, p.callback


@tag("security")
class UrlSweepTests(SimpleTestCase):
    def test_every_url_is_protected_or_marked_public(self):
        routes = list(iter_routes(get_resolver().url_patterns))
        seen_public, seen_login_only = set(), set()
        for path, callback in routes:
            in_role_prefix = any(path.startswith(r["prefix"]) for r in settings.ACCESS_MAP)
            public = callback is not None and getattr(callback, "login_required", True) is False
            if public:
                self.assertFalse(in_role_prefix, f"역할 접두사 아래에 공개 뷰가 있다: {path}")
                self.assertIn(path, EXPECTED_PUBLIC, f"예상하지 못한 공개 뷰: {path}")
                seen_public.add(path)
            elif not in_role_prefix:
                self.assertIn(path, LOGIN_ONLY, f"보호 표시도 역할 접두사도 없는 URL: {path}")
                seen_login_only.add(path)
        self.assertEqual(seen_public, EXPECTED_PUBLIC)  # 오래된 항목이 남지 않게
        self.assertEqual(seen_login_only, LOGIN_ONLY)

    def test_admin_site_is_mounted_under_a_role_prefix(self):
        paths = [p for p, cb in iter_routes(get_resolver().url_patterns) if cb is None]
        self.assertEqual(paths, ["/" + settings.ADMIN_URL_PATH])


@tag("security")
class AccessControlTests(TestCase):
    def setUp(self):
        self.adv = User.objects.create_user("adv_a", PW, nickname="광고주A", class_label="1반")
        self.admin = User.objects.create_superuser("root_a", PW, nickname="관리자", class_label="-")
        self.admin_index = reverse("admin:index")
        self.assertEqual(self.admin_index, "/test-admin/")

    def login_as(self, user):
        self.client.force_login(user, backend=MODEL_BACKEND)

    def test_anonymous_redirected_to_login(self):
        r = self.client.get("/advertiser/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/accounts/login/?next=/advertiser/")

    @override_settings(ROOT_URLCONF="tests.urls_default_deny")
    def test_unmarked_view_requires_login(self):
        r = self.client.get("/unmarked/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r["Location"])
        self.login_as(self.adv)
        self.assertEqual(self.client.get("/unmarked/").status_code, 200)

    def test_anonymous_gets_404_on_admin_prefix(self):
        for path in ("/test-admin/", "/test-admin/login/", "/test-admin/foundation/user/", "/test-admin/nope/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_advertiser_cannot_open_admin_area(self):
        self.login_as(self.adv)
        for path in ("/test-admin/", "/test-admin/foundation/user/", "/test-admin/login/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_admin_cannot_open_advertiser_area(self):
        self.login_as(self.admin)
        self.assertEqual(self.client.get("/advertiser/").status_code, 403)

    def test_admin_can_open_admin_area(self):
        self.login_as(self.admin)
        self.assertEqual(self.client.get(self.admin_index).status_code, 200)

    def test_advertiser_can_open_advertiser_area(self):
        self.login_as(self.adv)
        self.assertEqual(self.client.get("/advertiser/").status_code, 200)

    def test_lookalike_paths_are_not_treated_as_role_areas(self):
        self.login_as(self.adv)
        for path in ("/advertiser-evil/", "/test-adminx/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        # 테스트 클라이언트는 "//x/" 를 호스트 x 의 "/" 로 읽으므로 경로를 직접 지정한다
        self.assertEqual(self.client.get("/", PATH_INFO="//test-admin/").status_code, 404)

    def test_login_redirects_by_role(self):
        r = self.client.post(reverse("login"), {"username": "root_a", "password": PW})
        self.assertEqual(r["Location"], "/test-admin/")
        self.client.post(reverse("logout"))
        r = self.client.post(reverse("login"), {"username": "adv_a", "password": PW})
        self.assertEqual(r["Location"], "/advertiser/")

    def test_login_next_honors_safe_url_and_rejects_external(self):
        r = self.client.post(reverse("login") + "?next=/advertiser/", {"username": "adv_a", "password": PW})
        self.assertEqual(r["Location"], "/advertiser/")
        self.client.post(reverse("logout"))
        r = self.client.post(reverse("login") + "?next=https://evil.example/", {"username": "adv_a", "password": PW})
        self.assertEqual(r["Location"], "/advertiser/")

    def test_signup_cannot_escalate_role(self):
        self.client.post(reverse("signup"), {
            "username": "sneaky_one", "password": PW, "password_confirm": PW,
            "nickname": "sneak", "class_label": "1", "role": "admin", "is_staff": "1", "is_superuser": "1",
        })
        self.client.post(reverse("login"), {"username": "sneaky_one", "password": PW})
        self.assertEqual(self.client.get(self.admin_index).status_code, 404)

    def test_inactive_user_is_treated_as_anonymous(self):
        self.adv.is_active = False
        self.adv.save()
        self.login_as(self.adv)
        self.assertEqual(self.client.get("/advertiser/").status_code, 302)


@tag("security")
class AdminPathSettingTests(SimpleTestCase):
    def test_validate_admin_path_rules(self):
        self.assertEqual(validate_admin_path("ops-9f3a/"), "ops-9f3a/")
        for bad in ("", "/ops/", "ops", "a//b/", "admin/"):
            with self.assertRaises(ImproperlyConfigured, msg=bad):
                validate_admin_path(bad)
        self.assertEqual(validate_admin_path("admin/", allow_default=True), "admin/")

    def test_admin_url_default_rejected_in_prod(self):
        code = "from django.conf import settings; print(settings.ADMIN_URL_PATH)"
        ok = run_python(code, "config.settings.prod", PROD_ENV)
        self.assertEqual(ok.stdout.strip(), "ops-9f3a/", ok.stderr)
        for bad in ("admin/", "/ops/", "ops"):
            r = run_python(code, "config.settings.prod", dict(PROD_ENV, ADMIN_URL_PATH=bad))
            self.assertNotEqual(r.returncode, 0, bad)


@tag("security")
class OwnershipTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("owner_a", PW, nickname="A", class_label="1")
        self.b = User.objects.create_user("owner_b", PW, nickname="B", class_label="1")
        self.thing_a = OwnedThing.objects.create(owner=self.a, name="a-thing")
        self.thing_b = OwnedThing.objects.create(owner=self.b, name="b-thing")

    def test_owner_gets_own_object(self):
        self.assertEqual(owned_or_404(OwnedThing.objects.all(), self.a, id=self.thing_a.id), self.thing_a)

    def test_owned_or_404_hides_others_objects(self):
        with self.assertRaises(Http404):
            owned_or_404(OwnedThing.objects.all(), self.a, id=self.thing_b.id)

    def test_missing_and_malformed_ids_are_404(self):
        for bad in (uuid.uuid4(), "not-a-uuid", "", "1; DROP TABLE"):
            with self.assertRaises(Http404, msg=str(bad)):
                owned_or_404(OwnedThing.objects.all(), self.a, id=bad)

    def test_owned_queryset_contains_only_own_objects(self):
        self.assertEqual(list(owned_queryset(OwnedThing.objects.all(), self.a)), [self.thing_a])
