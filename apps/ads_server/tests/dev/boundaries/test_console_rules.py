"""콘솔에는 비즈니스 규칙이 없다(설계 §6.6, 계획 §8.1.1): 콘솔은 서비스 `api` 를 부르고 결과를 그리기만 한다.

층 규칙(R1·R2, test_layers)은 "다른 모듈은 `api` 만"까지 본다. 여기서는 콘솔이 그 너머로 규칙을 만들 수 있는 통로를 막는다:
트랜잭션·모델·원시 SQL(`django.db`), 금액 계산(`engine`), 모델 매니저로 직접 조회(`X.objects`).
"""
import ast

from django.conf import settings
from django.test import SimpleTestCase, tag

from .checker import imports_of
from .test_layers import project_files
from tests.support.cases import Cases

MANAGERS = {"objects", "_default_manager", "_base_manager"}


def console_violations(source):
    found = []
    for full, _names in imports_of(source):
        if full == "django.db" or full.startswith("django.db.") or full.split(".")[0] == "engine":
            found.append(f"import {full}")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in MANAGERS:
            found.append(f"{node.lineno}행: 모델 매니저 직접 사용 .{node.attr}")
    return found


@tag("security")
class ConsoleHasNoRulesTests(Cases, SimpleTestCase):
    def case_console_only_calls_services(self):
        files = project_files("console")
        self.assertGreater(len(files), 3)  # 검사가 공회전이 아니다
        problems = {str(p.name): v for p in files if (v := console_violations(p.read_text(encoding="utf-8")))}
        self.assertEqual(problems, {})

    def case_the_frontend_has_no_rules_either(self):
        """6-16i(R23): 프론트는 그리기만 한다(설계 §6.6 "6-15 분리") — 콘솔에서 옮긴 서식 필터(`console_format`·`console_chart`)를 포함한 프론트 파일에도 같은 통로가 없다."""
        files = list((settings.BASE_DIR.parent / "ads_frontend" / "ui").rglob("*.py"))
        self.assertGreater(len(files), 5)
        self.assertTrue(any(p.name == "console_format.py" for p in files))
        problems = {str(p.name): v for p in files if (v := console_violations(p.read_text(encoding="utf-8")))}
        self.assertEqual(problems, {})

    def case_the_rule_sees_each_form(self):
        for source in ("from django.db import transaction", "import django.db.models", "from django.db.models import Q",
                       "from engine.api import apply_bid", "User.objects.count()", "Campaign._default_manager.all()"):
            with self.subTest(source):
                self.assertTrue(console_violations(source))
        for source in ("from django import forms", "from campaigns.api import create_ad", "objects = []", "x.objects_count"):
            with self.subTest(source):
                self.assertEqual(console_violations(source), [])

    def test_console_has_no_rules(self):
        self.run_cases()
