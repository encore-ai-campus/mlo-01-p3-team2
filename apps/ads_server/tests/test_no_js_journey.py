"""Step 3-3 종료 점검: JS 없이 주요 흐름이 끝까지 가는지 보는 **HTML 폼 기반 서버 통합 시험**(계획 §8.1.1 D3-1 — JS 가 꺼져도 모든 흐름이 동작한다).

시험이 값을 지어 보내지 않고, 서버가 그린 HTML 의 폼에서 JS 없는 브라우저가 보낼 것만 보낸다: 이름이 있고 꺼지지 않은 칸, 체크된 체크 상자·라디오,
고른 선택지, 글 상자 내용, 누른 제출 버튼. 사람이 칸에 넣는 값만 바꾸고, 그 폼에 없는 칸은 넣을 수 없다. CSRF 검사를 켠다.
숨김 칸(요청 키·버전·변경 시각·CSRF)이나 버튼 이름·`enctype` 이 템플릿에서 빠지면 여기서 드러난다.

브라우저가 아니다: 폼은 HTMLParser 로 읽고 Django 시험 클라이언트로 낸다. 브라우저 엔진·CSS·키보드 동작·JS 실행은 이 시험의 범위 밖이고,
실제 브라우저로 본 것은 따로 기록한다(3-3c Chrome 점검, 외부 검토의 Chrome 확인).
"""
from html.parser import HTMLParser

from django.test import Client, TestCase, tag
from django.urls import reverse

from campaigns.models import Campaign
from tests.factories import PW, World, png_file


class Forms(HTMLParser):
    """화면의 폼들과, 각 폼에서 브라우저가 보내는 칸."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms, self._form, self._text, self._select = [], None, None, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._form = {"attrs": a, "values": [], "choices": {}, "files": set(), "buttons": []}
            self.forms.append(self._form)
        if tag == "option" and self._select is not None and ("selected" in a or self._select[1] is None):
            self._select[1] = a.get("value", "")
        if self._form is None or "name" not in a or "disabled" in a:  # 꺼진 칸은 보내지 않는다
            return
        name, kind = a["name"], a.get("type", "").lower()
        if (tag == "button" and kind in ("", "submit")) or (tag == "input" and kind == "submit"):
            self._form["buttons"].append((name, a.get("value", "")))
        elif tag == "input" and kind in ("checkbox", "radio"):
            self._form["choices"].setdefault(name, []).append((a.get("value", "on"), "checked" in a))
        elif tag == "input" and kind == "file":
            self._form["files"].add(name)
        elif tag == "input":
            self._form["values"].append([name, a.get("value", "")])
        elif tag in ("textarea", "select"):
            field = [name, "" if tag == "textarea" else None]
            self._form["values"].append(field)
            self._text, self._select = (field, None) if tag == "textarea" else (None, field)

    def handle_data(self, data):
        if self._text is not None:
            self._text[1] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        self._text = None if tag == "textarea" else self._text
        self._select = None if tag == "select" else self._select


def submit(client, page, pick, button=None, files=None, **typed):
    """`page` 의 폼 하나(`pick(폼 속성)`)를 낸다. `typed` 는 사람이 칸에 넣는 값(체크 상자·라디오는 체크할 값), `button` 은 누를 제출 버튼의 value."""
    (form,) = [f for f in Forms(page.content.decode()).forms if pick(f["attrs"])]
    data = {}
    for name, value in form["values"]:
        data.setdefault(name, []).append(value or "")
    for name, options in form["choices"].items():
        if checked := [v for v, on in options if on]:
            data[name] = checked
    for name, value in typed.items():
        chosen = value if isinstance(value, list) else [value]
        if name in form["choices"]:
            assert set(chosen) <= {v for v, _ in form["choices"][name]}, f"고를 수 없는 값: {name}={chosen}"
        else:
            assert name in data, f"화면에 없는 칸: {name}"
        data[name] = chosen
    for name, file in (files or {}).items():
        assert name in form["files"], f"화면에 없는 파일 칸: {name}"
        assert form["attrs"].get("enctype") == "multipart/form-data", "이 폼은 파일을 보내지 않는다(enctype)"  # 브라우저는 파일 이름만 보낸다
        data[name] = file
    if button is not None:
        name, value = next((n, v) for n, v in form["buttons"] if v == button)
        data[name] = [value]
    query = page.request.get("QUERY_STRING")
    return client.post(form["attrs"].get("action") or page.request["PATH_INFO"] + (f"?{query}" if query else ""), data)


def action(url):
    return lambda attrs: attrs.get("action") == url


def no_action(attrs):
    return "action" not in attrs


@tag("security")
class NoJsJourneyTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)  # 매체·노출 위치와 관리자
        self.adv, self.admin = Client(enforce_csrf_checks=True), Client(enforce_csrf_checks=True)

    def go(self, client, url):
        page = client.get(url)
        self.assertEqual(page.status_code, 200, url)
        return page

    def login(self, client, username):
        done = submit(client, self.go(client, reverse("login")), no_action, username=username, password=PW)
        self.assertEqual(done.status_code, 302, done.content.decode()[:300])

    def test_an_advertiser_and_an_admin_get_through_the_main_flows_without_js(self):
        # 가입 → 로그인
        done = submit(self.adv, self.go(self.adv, reverse("signup")), no_action, username="nojs_user", password=PW, password_confirm=PW, nickname="자바없음", class_label="3반")
        self.assertRedirects(done, reverse("login"))
        self.login(self.adv, "nojs_user")

        # 광고 만들기: 단위 고르기(다시 그림) → 미리보기(서버 계산) → 집행
        page = submit(self.adv, self.go(self.adv, reverse("ad_create")), lambda a: "ad-create" in a.get("class", ""), button="unit", pricing_unit="IMPRESSION")
        self.assertEqual(page.status_code, 200)
        slot = str(self.w.slot.slot_id)
        filled = dict(campaign_name="자바 없는 캠페인", ends_at="2030-12-31T09:00", daily_budget="3000", group_name="그룹", slot_ids=[slot], bid_amount="25",
                      title="제목", redirect_url="https://example.com/nojs")
        page = submit(self.adv, page, lambda a: "ad-create" in a.get("class", ""), button="preview", **filled)
        self.assertContains(page, "지금 정책 기준")
        done = submit(self.adv, page, lambda a: "ad-create" in a.get("class", ""), button="create", files={"image": png_file((1, 2, 3))})  # 미리보기 뒤 이미지는 다시 고른다
        campaign = Campaign.objects.get(name="자바 없는 캠페인")
        detail = reverse("campaign_detail", args=[campaign.campaign_id])
        self.assertRedirects(done, detail)

        # 캠페인 수정(화면이 본 변경 시각을 싣는다)
        self.assertRedirects(submit(self.adv, self.go(self.adv, detail), no_action, name="바꾼 이름"), detail)
        self.assertContains(self.go(self.adv, detail), "바꾼 이름")

        # 광고그룹: 새 입찰(화면이 본 버전을 싣는다)
        group = campaign.ad_groups.get()
        group_url = reverse("ad_group_detail", args=[group.ad_group_id])
        self.assertRedirects(submit(self.adv, self.go(self.adv, group_url), action(reverse("ad_group_bid", args=[group.ad_group_id])), amount="40"), group_url)
        self.assertEqual(group.bids.order_by("-bid_version").first().amount, 40)

        # 관리자: 모니터링에서 중단(사유)
        self.login(self.admin, self.w.admin.username)
        monitor = reverse("operator:campaign_monitor")
        done = submit(self.admin, self.go(self.admin, monitor), action(reverse("operator:campaign_suspend", args=[campaign.campaign_id])), reason="이동 주소 확인 필요")
        self.assertRedirects(done, monitor, fetch_redirect_response=False)

        # 광고주: 사유를 보고 재검토 요청
        page = self.go(self.adv, detail)
        self.assertContains(page, "이동 주소 확인 필요")
        self.assertRedirects(submit(self.adv, page, action(reverse("campaign_review", args=[campaign.campaign_id])), message="고쳤습니다"), detail)

        # 관리자: 재검토 대기에서 해제(본 중단 회차·요청을 싣는다)
        queue = reverse("operator:review_queue")
        done = submit(self.admin, self.go(self.admin, queue), action(reverse("operator:campaign_release", args=[campaign.campaign_id])))
        self.assertRedirects(done, queue, fetch_redirect_response=False)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "ACTIVE")

        # 포인트: 원장이 보인다
        self.assertContains(self.go(self.adv, reverse("points")), "가입")

    def test_the_helper_refuses_fields_the_page_does_not_have(self):
        """도우미가 공회전하지 않는다: 화면에 없는 칸, 꺼진 칸(단위를 고르기 전의 위치), 선택지에 없는 값은 보낼 수 없다."""
        self.login(self.adv, self.w.adv.username)
        page = self.go(self.adv, reverse("ad_create"))  # 단위를 고르기 전 — 모든 위치가 꺼져 있다
        ad_form = lambda a: "ad-create" in a.get("class", "")
        with self.assertRaisesRegex(AssertionError, "화면에 없는 칸"):
            submit(self.adv, page, ad_form, button="unit", made_up="1")
        with self.assertRaisesRegex(AssertionError, "화면에 없는 칸: slot_ids"):
            submit(self.adv, page, ad_form, button="unit", slot_ids=[str(self.w.slot.slot_id)])
        with self.assertRaisesRegex(AssertionError, "고를 수 없는 값"):
            submit(self.adv, page, ad_form, button="unit", pricing_unit="VIEW")
