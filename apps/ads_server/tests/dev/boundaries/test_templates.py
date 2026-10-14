"""템플릿 규칙(위협 모델 T9): 백엔드·프론트의 모든 템플릿에 인라인 스크립트·스타일·이벤트 속성·javascript: 가 없다 — CSP 가 막을 것을 처음부터 쓰지 않는다.
6-18e 에서 test_http_security 에서 나눔(소스 파일 대조라 개발용)."""
import re

from django.test import SimpleTestCase, tag

from tests.support.helpers import BASE_DIR


@tag("security")
class TemplateRuleTests(SimpleTestCase):
    def test_no_inline_script_or_style_in_templates(self):
        patterns = {
            "인라인 <script>": re.compile(r"<script(?![^>]*\bsrc=)", re.I),
            "<style> 블록": re.compile(r"<style\b", re.I),
            "style= 속성": re.compile(r"\sstyle\s*=", re.I),
            "이벤트 핸들러 속성": re.compile(r"\son[a-z]+\s*=", re.I),
            "javascript: URL": re.compile(r"javascript:", re.I),
        }
        files = [p for app in ("console", "foundation") for p in (BASE_DIR / app).rglob("*.html")]
        files += (BASE_DIR.parent / "ads_frontend/ui/templates").rglob("*.html")  # 6-15 뒤 우리 화면의 템플릿은 프론트에 있다(6-16i, R23)
        self.assertGreater(len(files), 25)  # 백엔드 1(관리자 첫 화면) + 프론트 29
        for path in files:
            text = path.read_text(encoding="utf-8")
            for label, rx in patterns.items():
                self.assertIsNone(rx.search(text), f"{path.relative_to(BASE_DIR.parent)}: {label}")
