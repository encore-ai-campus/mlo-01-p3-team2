"""Step 3-3 화면 전수 점검: 실제 데이터로 모든 화면을 그려 보안 헤더·CSP 위반·접근성 기본을 본다.

- 범위: 광고주·운영 화면은 손으로 적은 목록이지만, 모든 경로를 실제 값으로 GET 해서 HTML 로 그려지는 화면이 목록에 없으면 실패한다(빠뜨림 방지).
  관리자 사이트는 등록된 모든 모델의 목록·상세 화면과 비밀번호 변경·초기화를 등록에서 만든다. 정상 GET 으로는 나오지 않는 화면(키 발급·잠금·오류)은 따로 만든다.
  접근성 기본은 콘솔·운영 화면만 본다 — Django admin 기본 화면의 마크업(예: 비밀번호 관리자를 위해 CSS 로 숨긴 아이디 칸)은 우리가 고치지 않는다.

- 헤더: CSP(`script-src 'self'`)·클릭재킹 차단·`nosniff`·리퍼러 정책·캐시 금지. GET 으로 그리는 화면과, POST 응답으로만 그려지는 화면(키 발급·로그인 잠금).
- CSP 위반이 될 마크업: 인라인 스크립트(데이터 블록 제외)·`style` 속성·`on…` 이벤트 속성. 브라우저가 막아 화면이 깨지거나 기능이 죽는다.
- 접근성 기본: `<html lang>`, 이미지 대체 글, 입력 칸의 이름표(label·aria-label), 버튼의 이름, 주요 영역(`main`), 비밀번호 칸의 `autocomplete`(현재·새 비밀번호), 겹치지 않는 id.
- 색 대비: 디자인 토큰(프론트 `ui/static/console/app.css`)의 글자·배경 쌍이 라이트·다크 모두 WCAG AA(4.5:1) 이상.
"""
import re
import uuid
from html.parser import HTMLParser
from random import Random

from django.conf import settings
from axes.models import AccessFailureLog
from django.contrib import admin
from django.test import Client, TestCase, tag
from django.urls import resolve, reverse

from billing import api as billing
from campaigns import api as campaigns
from masters import api as masters
from records import api as records
from tests.support.factories import NOW, PW, SUBJECT, WHOLE, World, png_file
from tests.support.presentation import rendering
from tests.support.helpers import ROUTE_PARAM, every_route
from tests.support.cases import Cases

INPUTS_NEEDING_NAMES = {"text", "password", "number", "url", "email", "search", "date", "datetime-local", "file", "checkbox", "radio", None}


class PageAudit(HTMLParser):
    """마크업에서 규칙 위반을 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems, self.labels_for, self.inputs, self.lang, self.main = [], set(), [], None, False
        self.label_depth, self.button_text, self.in_button, self.button_attrs, self.script_open = 0, "", False, {}, None
        self.ids = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "main" or a.get("role") == "main":
            self.main = True
        if "style" in a:
            self.problems.append(f"style 속성: <{tag} style={a['style']!r}>")
        for name in a:
            if name.startswith("on"):
                self.problems.append(f"이벤트 속성: <{tag} {name}>")
        if tag == "script":
            if not a.get("src") and a.get("type") not in ("application/json", "application/ld+json"):
                self.problems.append("인라인 스크립트")
        if tag == "input" and a.get("type") == "password" and a.get("autocomplete") not in ("current-password", "new-password"):
            self.problems.append(f"비밀번호 칸의 autocomplete: <input name={a.get('name')!r} autocomplete={a.get('autocomplete')!r}>")  # 비밀번호 관리자가 칸을 구분한다
        if tag == "img" and "alt" not in a:
            self.problems.append(f"대체 글 없는 이미지: {a.get('src')}")
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            kind = a.get("type") if tag == "input" else None
            if tag != "input" or kind in INPUTS_NEEDING_NAMES:
                named = self.label_depth > 0 or a.get("aria-label") or a.get("aria-labelledby") or a.get("title")
                self.inputs.append((a.get("id"), bool(named), f"<{tag} name={a.get('name')!r}>"))
        if tag == "button":
            self.in_button, self.button_text, self.button_attrs = True, "", a

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1
        if tag == "button" and self.in_button:
            self.in_button = False
            if not self.button_text.strip() and not self.button_attrs.get("aria-label") and not self.button_attrs.get("title"):
                self.problems.append(f"이름 없는 버튼: {self.button_attrs}")

    def handle_data(self, data):
        if self.in_button:
            self.button_text += data

    def report(self):
        problems = list(self.problems)
        for input_id, named, desc in self.inputs:
            if not named and input_id not in self.labels_for:
                problems.append(f"이름표 없는 입력 칸: {desc}")
        if not (self.lang or "").lower().startswith("ko"):
            problems.append(f"html lang: {self.lang!r}")
        if not self.main:
            problems.append("main 영역 없음")
        problems += [f"겹친 id: {i}" for i in sorted({i for i in self.ids if self.ids.count(i) > 1})]  # 이름표(for)가 다른 폼의 칸을 가리킨다
        return problems


@tag("security")
class ScreenQualityTests(Cases, TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.suspended = campaigns.create_campaign(self.w.adv, "<b>중단된 캠페인</b>", self.w.campaign.starts_at, None, 1000)
        campaigns.suspend_campaign(self.w.admin, self.suspended.campaign_id, "<i>사유</i>")
        campaigns.create_review_request(self.w.adv, self.suspended.campaign_id, "고쳤습니다")
        campaigns.create_creative(self.w.adv, self.w.group.ad_group_id, "둘째 소재", "https://example.com/2", png_file((9, 9, 9)))  # 이미지마다 고르기 버튼이 되풀이된다
        # 관리자 사이트의 모든 모델 상세 화면을 보려고 줄을 하나씩 둔다
        Client().post(reverse("login"), {"username": "nobody", "password": "wrong-password-xyz"})  # 잠금 시도
        Client().post(reverse("login"), {"username": self.w.admin.username, "password": PW})  # 접속 기록
        AccessFailureLog.objects.create(username="nobody", ip_address="127.0.0.1", user_agent="test", path_info="/", locked_out=False)  # 설정이 꺼져 있어도 화면은 있다
        masters.issue_media_key(self.w.admin, self.w.slot.media_id, "점검")
        masters.set_media_active(self.w.admin, masters.create_media(self.w.admin, "끈 매체").media_id, False)  # 매체 비활성화 기록
        records.decide(self.w.slot.media_id, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        billing.charge_for_reaction(self.w.adv.pk, self.w.campaign.campaign_id, "IMPRESSION", WHOLE, 10, f"{self.w.slot.media_id}:{uuid.uuid4()}", now=NOW)

    def pages(self):
        adv = [reverse(n, args=a) for n, a in (
            ("advertiser_home", []), ("campaign_list", []), ("campaign_detail", [self.w.campaign.campaign_id]),
            ("campaign_detail", [self.suspended.campaign_id]), ("ad_group_detail", [self.w.group.ad_group_id]), ("ad_create", []),
            ("campaign_create", []), ("creative_list", []), ("creative_detail", [self.w.creative.creative_id]),
            ("points", []), ("my_account", []),
        )]
        operator = [reverse(n, args=a) for n, a in (
            ("operator:media_list", []), ("operator:media_detail", [self.w.slot.media_id]),
            ("operator:slot_policy", [self.w.slot.slot_id]), ("operator:policy_bulk", []), ("operator:campaign_monitor", []),
            ("operator:review_queue", []), ("operator:advertiser_list", []), ("operator:advertiser_detail", [self.w.adv.pk]),
        )]
        anonymous = [reverse("login"), reverse("signup")]
        return [(self.w.adv, adv), (self.w.admin, operator + self.admin_site_pages()), (None, anonymous)]

    def admin_site_pages(self):
        """관리자 사이트에 등록된 **모든** 모델의 목록·상세 화면(등록이 늘면 함께 본다. 읽기 전용이라 추가·삭제 화면은 없다), 첫 화면, 본인 비밀번호 변경, 사용자 비밀번호 초기화."""
        urls = [reverse("admin:index"), reverse("admin:password_change"), reverse("admin:password_change_done"),
                reverse("admin:auth_user_password_change", args=[self.w.adv.pk])]  # UserAdmin 이 이 이름을 고정해 쓴다
        missing = []
        for model in admin.site._registry:
            if model._meta.app_label == "tests_support":  # 시험 설정에만 있는 모델
                continue
            name = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            urls.append(reverse(f"{name}_changelist"))
            row = model._default_manager.order_by("pk").first()
            if row is None:
                missing.append(name)
                continue
            urls.append(reverse(f"{name}_change", args=[row.pk]))
        self.assertEqual(missing, [], "상세 화면을 볼 줄이 없다(준비 데이터에 더한다)")
        return urls

    def case_no_console_or_operator_screen_is_left_out(self):
        """화면 목록은 손으로 적지만 빠뜨리면 실패한다: 광고주·운영 경로를 모두 실제 값으로 GET 해서, HTML 로 그려지는 화면은 위 목록에 있어야 한다.
        POST 전용 동작은 405, 파일(이미지)은 HTML 이 아니다. 실제 값이 없는 경로는 404 라 여기서 실패한다(값을 더한다)."""
        values = {
            "campaign_id": self.w.campaign.campaign_id, "ad_group_id": self.w.group.ad_group_id, "creative_id": self.w.creative.creative_id,
            "media_id": self.w.slot.media_id, "slot_id": self.w.slot.slot_id, "user_id": self.w.adv.pk, "name": self.w.creative.image_name,
            "review_request_id": campaigns.get_campaign(self.w.adv, self.suspended.campaign_id).suspension.open_review_request_id,
            "key_id": uuid.uuid4(),  # 폐기(POST 전용)에만 쓴다
        }
        audited = {resolve(url.split("?")[0]).view_name for _, urls in self.pages() for url in urls}
        clients = {}
        for prefix, user in (("advertiser/", self.w.adv), (settings.ADMIN_URL_PATH + "operator/", self.w.admin)):
            clients[prefix] = Client()
            clients[prefix].force_login(user)
        screens = 0
        for route in sorted(set(every_route())):
            prefix = next((p for p in clients if route.startswith(p)), None)
            if prefix is None:
                continue
            path = "/" + ROUTE_PARAM.sub(lambda m: str(values[m.group(2)]), route)
            r = clients[prefix].get(path)
            if r.status_code == 405 or (r.status_code == 200 and not r["Content-Type"].startswith("text/html")):
                continue
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(resolve(path).view_name, audited, f"점검 목록에 없는 화면: {path}")
            screens += 1
        self.assertGreaterEqual(screens, 15)  # 공회전이 아니다

    def case_every_screen_has_the_security_headers_and_no_csp_violations(self):
        checked = 0
        for user, urls in self.pages():
            client = Client()
            if user is not None:
                client.force_login(user)
            for url in urls:
                r = client.get(url)
                self.assertEqual(r.status_code, 200, url)
                audit = self.assert_headers(r, url)
                markup = [p for p in audit.problems if not p.startswith("대체 글")]
                self.assertEqual(markup, [], url)
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def assert_headers(self, r, label):
        csp = r.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp, label)
        self.assertIn("frame-ancestors 'none'", csp, label)
        self.assertEqual(r.get("X-Frame-Options"), "DENY", label)
        self.assertEqual(r.get("X-Content-Type-Options"), "nosniff", label)
        self.assertTrue(r.get("Referrer-Policy"), label)
        self.assertIn("no-store", r.get("Cache-Control", ""), label)
        audit = PageAudit()
        audit.feed(r.content.decode())
        return audit

    def case_post_only_and_error_screens_are_checked_too(self):
        """정상 GET 으로는 나오지 않는 화면: 매체 키 발급(평문은 이 응답 한 번), 로그인 잠금(429), 오류 화면(`foundation/error.html`).
        헤더·마크업·접근성 모두 같은 기준."""
        admin = Client()
        admin.force_login(self.w.admin)
        detail = admin.get(reverse("operator:media_detail", args=[self.w.slot.media_id])).content.decode()
        token = re.search(r'name="request_key" value="([^"]+)"', detail[detail.index('id="key-issue"'):]).group(1)
        anonymous = Client()
        for _ in range(settings.AXES_FAILURE_LIMIT):
            anonymous.post(reverse("login"), {"username": self.w.adv.username, "password": "wrong-password-xyz"})
        advertiser = Client()
        advertiser.force_login(self.w.adv)
        screens = {
            "키 발급": (admin.post(reverse("operator:key_issue", args=[self.w.slot.media_id]), {"label": "점검", "request_key": token}), 200),
            "로그인 잠금": (anonymous.post(reverse("login"), {"username": self.w.adv.username, "password": PW}), 429),
            "오류 화면": (advertiser.get(reverse("campaign_detail", args=[uuid.uuid4()])), 404),
        }
        for label, (r, status) in screens.items():
            self.assertEqual(r.status_code, status, label)
            self.assertEqual(self.assert_headers(r, label).report(), [], label)
        error_page = screens["오류 화면"][0].content.decode()
        self.assertIn("<title>찾을 수 없습니다</title>", error_page)  # 제목은 오류 종류(`NotFound.title`), 본문은 화면이 정한 문구
        self.assertIn("<p class=\"muted\">요청한 페이지를 찾을 수 없습니다.</p>", error_page)

    def case_console_screens_meet_the_accessibility_basics(self):
        """콘솔(광고주·로그인·가입) 화면. 관리자 화면의 틀은 Django admin 의 것이라 그 위에 얹은 운영 화면만 같은 기준으로 본다."""
        for user, urls in self.pages():
            client = Client()
            if user is not None:
                client.force_login(user)
            for url in urls:
                if url.startswith("/" + settings.ADMIN_URL_PATH) and "/operator/" not in url:
                    continue
                audit = PageAudit()
                audit.feed(client.get(url).content.decode())
                self.assertEqual(audit.report(), [], url)

    def case_every_advertiser_screen_marks_its_menu(self):
        """주 메뉴의 현재 위치(`aria-current`)는 화면마다 하나 — 광고 만들기·광고 상세는 캠페인에 속한다(6-13c R8)."""
        menus = {"대시보드": ("advertiser_home",), "캠페인": ("campaign_list", "campaign_detail", "campaign_create", "ad_group_detail", "ad_create"),
                 "소재": ("creative_list", "creative_detail"), "포인트": ("points",), "내 정보": ("my_account",)}
        menu_of = {name: menu for menu, names in menus.items() for name in names}
        self.client.force_login(self.w.adv)
        (_, adv), *_ = self.pages()
        for url in adv:
            html = self.client.get(url).content.decode()
            self.assertEqual(re.findall(r'aria-current="page">(?:<svg.*?</svg>)?([^<]+)</a>', html), [menu_of[resolve(url).url_name]], url)  # 메뉴 앞 아이콘(6-21b)

    def case_screens_use_the_screen_terms(self):
        """화면 용어는 "광고"·"구성"이다 — 코드·계약의 광고그룹(`AdGroup`)과 슬롯(`Slot`, 옛 화면 이름 "게재 위치"), 없어진 과금 단위를 화면에 드러내지 않는다
        (6-9e·6-10e·6-10d, 설계 §10 "화면 용어: 광고"·"화면 용어: 구성"). Django admin 의 모델 화면은 범위 밖."""
        for user, urls in self.pages():
            client = Client()
            if user is not None:
                client.force_login(user)
            for url in urls:
                if url.startswith("/" + settings.ADMIN_URL_PATH) and "/operator/" not in url:
                    continue
                html = client.get(url).content.decode()
                for word in ("광고그룹", "게재 위치", "과금 단위"):
                    self.assertNotIn(word, html, (url, word))

    def case_the_design_tokens_have_enough_contrast(self):
        """시안 v2 의 색 토큰(밝은 화면만 — 6-21b)에서 글자·바탕 쌍이 WCAG AA(4.5:1) 이상이다: 본문·흐린 글자, 버튼, 상태 배지·알림 띠, 사이드바."""
        css = (rendering.ROOT / "static/console/app.css").read_text()  # 콘솔 CSS 는 프론트에 있다(6-15)
        self.assertNotIn("prefers-color-scheme", css)  # 다크 모드는 없앴다(설계 §10 "광고주 화면 v2")
        tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", css))
        pairs = [("ink", "paper"), ("ink", "canvas"), ("ink", "quiet"), ("muted", "paper"), ("muted", "canvas"), ("muted", "quiet"),
                 ("paper", "accent"), ("accentdark", "paper"), ("accentdark", "accentsoft"), ("danger", "paper"),  # 버튼(Primary·Tonal)·링크·오류
                 ("positive", "positivesoft"), ("warning", "warningsoft"), ("danger", "dangersoft"), ("blue", "bluesoft"),  # 상태 배지·알림 띠
                 ("muted", "accentsoft"), ("muted", "warningsoft"), ("muted", "dangersoft"),  # 알림 띠 안의 흐린 글자
                 ("paper", "nav"), ("navmuted", "nav"), ("navmuted", "navcard")]  # 사이드바
        for fg, bg in pairs:
            self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5, f"{fg} on {bg}")

    def test_screen_quality(self):
        self.run_cases()


def contrast(a, b):
    """WCAG 2 대비율."""
    def luminance(hex_color):
        if len(hex_color) == 4:  # #rgb
            hex_color = "#" + "".join(c * 2 for c in hex_color[1:])
        channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
