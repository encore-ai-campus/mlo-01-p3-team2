"""Step 3-3 화면 전수 점검: 실제 데이터로 모든 화면을 그려 보안 헤더·CSP 위반·접근성 기본을 본다.

- 헤더: CSP(`script-src 'self'`)·클릭재킹 차단·`nosniff`·리퍼러 정책·로그인 화면의 캐시 금지.
- CSP 위반이 될 마크업: 인라인 스크립트(데이터 블록 제외)·`style` 속성·`on…` 이벤트 속성. 브라우저가 막아 화면이 깨지거나 기능이 죽는다.
- 접근성 기본: `<html lang>`, 이미지 대체 글, 입력 칸의 이름표(label·aria-label), 버튼의 이름, 주요 영역(`main`).
- 색 대비: 디자인 토큰(`console/static/console/app.css`)의 글자·배경 쌍이 라이트·다크 모두 WCAG AA(4.5:1) 이상.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import Client, TestCase, tag
from django.urls import reverse

from campaigns import api as campaigns
from tests.factories import World

INPUTS_NEEDING_NAMES = {"text", "password", "number", "url", "email", "search", "date", "datetime-local", "file", "checkbox", "radio", None}


class PageAudit(HTMLParser):
    """마크업에서 규칙 위반을 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems, self.labels_for, self.inputs, self.lang, self.main = [], set(), [], None, False
        self.label_depth, self.button_text, self.in_button, self.button_attrs, self.script_open = 0, "", False, {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
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
        return problems


@tag("security")
class ScreenQualityTests(TestCase):
    def setUp(self):
        self.w = World(ends_in=None)
        self.suspended = campaigns.create_campaign(self.w.adv, "<b>중단된 캠페인</b>", self.w.campaign.starts_at, None, 1000)
        campaigns.suspend_campaign(self.w.admin, self.suspended.campaign_id, "<i>사유</i>")
        campaigns.create_review_request(self.w.adv, self.suspended.campaign_id, "고쳤습니다")

    def pages(self):
        adv = [reverse(n, args=a) for n, a in (
            ("advertiser_home", []), ("campaign_list", []), ("campaign_detail", [self.w.campaign.campaign_id]),
            ("campaign_detail", [self.suspended.campaign_id]), ("ad_group_detail", [self.w.group.ad_group_id]), ("ad_create", []),
            ("points", []), ("my_account", []),
        )] + [reverse("ad_create") + "?unit=IMPRESSION"]
        admin = [reverse(n, args=a) for n, a in (
            ("admin:index", []), ("operator:media_list", []), ("operator:media_detail", [self.w.slot.media_id]),
            ("operator:slot_policy", [self.w.slot.slot_id]), ("operator:policy_bulk", []), ("operator:campaign_monitor", []),
            ("operator:review_queue", []), ("operator:advertiser_list", []), ("operator:advertiser_detail", [self.w.adv.pk]),
            ("admin:foundation_user_change", [self.w.adv.pk]), ("admin:foundation_auditlog_changelist", []),
        )]
        anonymous = [reverse("login"), reverse("signup")]
        return [(self.w.adv, adv), (self.w.admin, admin), (None, anonymous)]

    def test_every_screen_has_the_security_headers_and_no_csp_violations(self):
        checked = 0
        for user, urls in self.pages():
            client = Client()
            if user is not None:
                client.force_login(user)
            for url in urls:
                r = client.get(url)
                self.assertEqual(r.status_code, 200, url)
                csp = r.get("Content-Security-Policy", "")
                self.assertIn("script-src 'self'", csp, url)
                self.assertIn("frame-ancestors 'none'", csp, url)
                self.assertEqual(r.get("X-Frame-Options"), "DENY", url)
                self.assertEqual(r.get("X-Content-Type-Options"), "nosniff", url)
                self.assertTrue(r.get("Referrer-Policy"), url)
                self.assertIn("no-store", r.get("Cache-Control", ""), url)
                audit = PageAudit()
                audit.feed(r.content.decode())
                markup = [p for p in audit.problems if not p.startswith("대체 글")]
                self.assertEqual(markup, [], url)
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_console_screens_meet_the_accessibility_basics(self):
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

    def test_the_design_tokens_have_enough_contrast_in_both_themes(self):
        css = Path(finders.find("console/app.css")).read_text()
        token = re.compile(r"--([\w-]+):\s*(#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b)")
        head, dark_block = css.split("@media (prefers-color-scheme: dark)", 1)
        light = dict(token.findall(head))
        dark = {**light, **dict(token.findall(dark_block.split("}\n}")[0]))}
        pairs = [("text", "bg"), ("text", "surface"), ("muted", "surface"), ("muted", "bg"), ("accent", "surface"), ("accent-text", "accent"),
                 ("danger", "surface"), ("text", "ok-bg"), ("text", "warn-bg"), ("text", "error-bg"), ("muted", "ok-bg"), ("muted", "warn-bg"), ("muted", "error-bg")]  # 알림·오류 상자 안의 흐린 글자
        for name, tokens in (("light", light), ("dark", dark)):
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5, f"{name}: {fg} on {bg}")


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
