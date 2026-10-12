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

    def test_only_the_reaction_processor_charges_and_only_it_changes_reaction_status(self):
        """과금은 반응 처리(`records/processing.py`)에서만 호출하고, 반응의 상태는 그 파일의 `_finish` 에서만 바꾼다(설계 §4.4)."""
        call = re.compile(r"\bcharge_for_reaction\(")
        status_write = re.compile(r"\bReaction\.objects\b[^\n]*\.update\([^)]*\bstatus\s*=|\.status\s*=\s*['\"A-Z]")
        charge_sites, status_sites = set(), set()
        for module in LAYERS:
            for path in project_files(module):
                text = path.read_text(encoding="utf-8")
                if module != "billing" and call.search(text):
                    charge_sites.add(path.name)
                if module == "records" and status_write.search(text):
                    status_sites.add(path.name)
        self.assertEqual(charge_sites, {"processing.py"})
        self.assertEqual(status_sites, {"processing.py"})
