"""Step 3-0 콘솔 공통 틀: 예외 → 화면 한 곳(`console/errors.py`), 포인트 표시, 쪽 나누기, 레이아웃."""
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.template import Context, RequestContext
from django.test import RequestFactory, SimpleTestCase, TestCase, tag
from django.urls import reverse

from assets.api import ImageRejected
from console.errors import form_errors, message_of
from console.paging import PER_PAGE, page_of
from foundation.api import errors
from tests.factories import make_advertiser
from tests.presentation import rendering


class Form(forms.Form):
    name = forms.CharField(required=False)
    image = forms.FileField(required=False)


def errors_of(error, **kw):
    form = Form({})
    form.is_valid()
    form_errors(form, error, **kw)
    return {k: list(v) for k, v in form.errors.items()}


class FormErrorsTests(SimpleTestCase):
    """서비스의 예외를 폼 오류로 바꾸는 곳은 여기 한 곳이다(설계 §6.6 규칙 2)."""

    def test_validation_errors_go_to_their_field_or_the_form(self):
        self.assertEqual(errors_of(ValidationError({"name": ["짧습니다."], "unknown": ["모르는 칸"]})),
                         {"name": ["짧습니다."], "__all__": ["모르는 칸"]})
        self.assertEqual(errors_of(ValidationError("바꿀 항목이 없습니다.")), {"__all__": ["바꿀 항목이 없습니다."]})

    def test_service_pointers_go_to_the_field(self):
        problem = errors.InvalidRequest(errors=[{"pointer": "/name", "message": "이름이 비었습니다."}, {"pointer": "/x/y", "message": "다른 칸"}])
        self.assertEqual(errors_of(problem), {"name": ["이름이 비었습니다."], "__all__": ["다른 칸"]})
        nested = errors.InvalidRequest(errors=[{"pointer": "/creative/title", "message": "소재 제목"}])  # 마지막 조각(title)이 폼에 없는 칸
        self.assertEqual(errors_of(nested), {"__all__": ["소재 제목"]})
        self.assertEqual(errors_of(nested, pointers={"/creative/title": "name"}), {"name": ["소재 제목"]})

    def test_a_conflict_without_details_is_a_form_message(self):
        self.assertEqual(errors_of(errors.StaleVersion()), {"__all__": [errors.StaleVersion.title]})
        self.assertEqual(errors_of(errors.Conflict("종료된 캠페인입니다.")), {"__all__": ["종료된 캠페인입니다."]})

    def test_a_rejected_image_goes_to_the_image_field(self):
        self.assertEqual(errors_of(ImageRejected("too_large", "너무 큽니다."), image_field="image"), {"image": ["너무 큽니다."]})

    def test_not_found_forbidden_and_server_errors_are_not_form_errors(self):
        with self.assertRaises(Http404):
            errors_of(errors.NotFound())
        with self.assertRaises(PermissionDenied):
            errors_of(errors.Forbidden())
        for error in (errors.Unavailable(), RuntimeError("버그")):
            with self.subTest(error), self.assertRaises(type(error)):
                errors_of(error)

    def test_message_of_for_actions_without_a_form(self):
        self.assertEqual(message_of(errors.Conflict("이미 중단되었습니다.")), "이미 중단되었습니다.")
        self.assertEqual(message_of(errors.StaleVersion()), errors.StaleVersion.title)
        self.assertEqual(message_of(ValidationError({"a": ["하나"], "b": ["둘"]})), "하나 둘")
        with self.assertRaises(Http404):
            message_of(errors.NotFound())


class PointsAndPagingTests(SimpleTestCase):
    """서식 필터·쪽 나누기 조각은 프론트에 있다(6-15) — 프론트 렌더러의 엔진으로 그린다."""

    def render(self, text, **context):
        return rendering.engine().from_string("{% load console_format %}" + text).render(Context(context))

    def test_points(self):
        self.assertEqual(self.render("{{ v|points }}", v=1234567), "1,234,567 포인트")
        self.assertEqual(self.render("{{ v|points }}", v=-50), "-50 포인트")
        self.assertEqual(self.render("{{ v|points }}", v=None), "")

    def test_page_of_tolerates_bad_page_numbers(self):
        items = list(range(PER_PAGE * 2 + 1))
        factory = RequestFactory()
        self.assertEqual(page_of(items, factory.get("/", {"page": "abc"})).number, 1)
        self.assertEqual(page_of(items, factory.get("/", {"page": "999"})).number, 3)
        self.assertEqual(list(page_of(items, factory.get("/", {"page": "3"}))), [PER_PAGE * 2])

    def test_pager_keeps_other_query_values(self):
        request = RequestFactory().get("/", {"page": "2", "from": "2026-10-01"})
        page = page_of(list(range(PER_PAGE * 3)), request)
        html = rendering.engine().get_template("console/_pager.html").render(RequestContext(request, {"page": page}))
        self.assertIn("?page=1&amp;from=2026-10-01", html)
        self.assertIn("?page=3&amp;from=2026-10-01", html)
        self.assertIn("2 / 3", html)


@tag("security")
class LayoutTests(TestCase):
    def test_signed_in_advertiser_sees_navigation_and_no_script_unless_a_page_adds_one(self):
        self.client.force_login(make_advertiser())
        html = self.client.get(reverse("advertiser_home")).content.decode()
        self.assertIn('aria-label="주 메뉴"', html)
        self.assertIn(reverse("advertiser_home"), html)
        self.assertNotIn("<script", html)

    def test_anonymous_pages_have_no_navigation(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn('aria-label="주 메뉴"', html)
