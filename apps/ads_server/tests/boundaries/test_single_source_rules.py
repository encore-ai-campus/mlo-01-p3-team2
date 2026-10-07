"""규칙의 원본이 한 곳인지 소스로 확인한다(계획 §6.8): 적용 금액·종료 판정은 engine 뿐이다(설계 §4.2·§4.5)."""
import re

from django.test import SimpleTestCase, tag

from .test_layers import LAYERS, project_files


@tag("security")
class SingleSourceRuleTests(SimpleTestCase):
    def test_pricing_and_expiry_rules_are_defined_only_in_engine(self):
        definition = re.compile(r"^\s*def (effect_of|is_expired)\b", re.M)
        clamp = re.compile(r"min\([^)]*\bcap\b|max\([^)]*\bfloor\b|\bbid\w*\s*[<>]=?\s*(floor|cap)\b")
        found, offenders = set(), []
        for module in LAYERS:
            for path in project_files(module):
                text = path.read_text(encoding="utf-8")
                for m in definition.finditer(text):
                    found.add((module, m.group(1)))
                if module != "engine" and clamp.search(text):
                    offenders.append(str(path))
        self.assertEqual(found, {("engine", "effect_of"), ("engine", "is_expired")})  # 검사가 공회전이 아님
        self.assertEqual(offenders, [])
