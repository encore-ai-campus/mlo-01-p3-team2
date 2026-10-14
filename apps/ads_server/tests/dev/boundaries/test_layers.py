from django.test import SimpleTestCase, tag

from tests.support.helpers import BASE_DIR

from .checker import find_engine_violations, find_fk_violations, find_violations

# **층 정의는 여기 하나다**(설계 §6.2). 위 → 아래 방향으로만 import 하고, 같은 층끼리는 서로 모른다.
# 모듈을 옮기거나 새로 만들면 이 딕셔너리만 고친다. config(조립)·tests 는 검사에서 제외한다.
LAYERS = {
    "foundation": 0,
    "masters": 1, "engine": 1, "assets": 1, "events": 1,
    "campaigns": 2, "billing": 2,
    "records": 3,
    "serving_api": 4, "console": 4,
}


def project_files(module):
    root = BASE_DIR / module
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts] if root.is_dir() else []


@tag("security")
class LayerRuleTests(SimpleTestCase):
    def test_layer_rules(self):
        problems = []
        for module in LAYERS:
            for path in project_files(module):
                for v in find_violations(module, path.read_text(encoding="utf-8"), LAYERS):
                    problems.append(f"{path.relative_to(BASE_DIR)}: {v}")
        self.assertEqual(problems, [])

    def test_only_api_imports_across_modules(self):
        # test_layer_rules 가 R2 도 함께 검사한다. 여기서는 실제로 존재하는 모듈 간 import 가 있음을 확인(검사가 공회전이 아님).
        found = set()
        for module in LAYERS:
            for path in project_files(module):
                src = path.read_text(encoding="utf-8")
                for other in LAYERS:
                    if other != module and (f"from {other}.api" in src or f"import {other}.api" in src):
                        found.add((module, other))
        self.assertIn(("console", "foundation"), found)

    def test_every_project_module_is_registered(self):
        """새 모듈이 LAYERS 에 등록되지 않은 채 생기면 검사를 피해 갈 수 있다."""
        unregistered = [
            d.name for d in BASE_DIR.iterdir()
            if d.is_dir() and (d / "apps.py").exists() and d.name not in LAYERS and d.name != "tests"
        ]
        self.assertEqual(unregistered, [])

    def test_engine_is_pure(self):
        for path in project_files("engine"):
            self.assertEqual(find_engine_violations(path.read_text(encoding="utf-8"), LAYERS), [], str(path))

    def test_foreign_keys_use_label_strings(self):
        for module in LAYERS:
            models = BASE_DIR / module / "models.py"
            if models.exists():
                self.assertEqual(find_fk_violations(models.read_text(encoding="utf-8")), [], str(models))


@tag("security")
class CheckerDetectsViolationsTests(SimpleTestCase):
    """검사기가 실제로 위반을 잡는지 가짜 소스로 확인한다(공회전 방지)."""

    def violations(self, module, source):
        return find_violations(module, source, LAYERS)

    def test_other_modules_internals_are_forbidden(self):
        self.assertTrue(self.violations("console", "from foundation.models import User"))
        self.assertTrue(self.violations("console", "import foundation.accounts"))
        self.assertTrue(self.violations("console", "from foundation import models"))
        self.assertTrue(self.violations("console", "import foundation"))

    def test_api_imports_are_allowed(self):
        for src in ("from foundation.api import X", "import foundation.api", "from foundation import api",
                    "from campaigns.api import Y"):
            self.assertEqual(self.violations("console", src), [], src)

    def test_upward_and_same_layer_imports_are_forbidden(self):
        self.assertTrue(self.violations("foundation", "from console.api import X"))  # 아래가 위를 import
        self.assertTrue(self.violations("assets", "from engine.api import X"))  # 같은 층
        self.assertTrue(self.violations("campaigns", "from billing.api import X"))  # 같은 층
        self.assertTrue(self.violations("assets", "from records.api import X"))  # 위 층

    def test_relative_and_external_imports_are_ignored(self):
        self.assertEqual(self.violations("console", "from .models import X\nfrom ..forms import Y\nimport json, django"), [])

    def test_engine_purity_checker(self):
        self.assertTrue(find_engine_violations("import django", LAYERS))
        self.assertTrue(find_engine_violations("from django.db import models", LAYERS))
        self.assertTrue(find_engine_violations("from foundation.api import x", LAYERS))
        self.assertTrue(find_engine_violations("from config import settings", LAYERS))
        self.assertEqual(find_engine_violations("import json, random\nfrom dataclasses import dataclass\nfrom .models import X", LAYERS), [])

    def test_foreign_key_checker(self):
        self.assertEqual(find_fk_violations('class A(models.Model):\n    u = models.ForeignKey("foundation.User", on_delete=models.CASCADE)'), [])
        self.assertEqual(find_fk_violations("class A(models.Model):\n    u = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)"), [])
        self.assertEqual(find_fk_violations("class B(models.Model): pass\nclass A(models.Model):\n    b = models.ForeignKey(B, on_delete=models.CASCADE)"), [])
        self.assertTrue(find_fk_violations("from foundation.models import User\nclass A(models.Model):\n    u = models.ForeignKey(User, on_delete=models.CASCADE)"))
