"""규칙의 원본이 한 곳인지 소스로 확인한다(계획 §6.8): 적용 금액·종료 판정은 engine 뿐이다(설계 §4.2·§4.5)."""
import re

from django.conf import settings
from django.test import SimpleTestCase, tag

from .test_layers import LAYERS, project_files
from tests.support.cases import Cases


@tag("security")
class SingleSourceRuleTests(Cases, SimpleTestCase):
    def case_pricing_and_expiry_rules_are_defined_only_in_engine(self):
        definition = re.compile(r"^\s*def (effect_of|is_expired)\b", re.M)
        clamp = re.compile(r"min\([^)]*\bcap\b|max\([^)]*\bfloor\b|\bbid\w*\s*[<>]=?\s*(floor|cap)\b")
        found, offenders = set(), []
        frontend = [("frontend", p) for p in (settings.BASE_DIR.parent / "ads_frontend" / "ui").rglob("*.py")]  # 콘솔에서 옮긴 서식 필터도(6-16i, R23)
        for module, path in [(m, p) for m in LAYERS for p in project_files(m)] + frontend:
            text = path.read_text(encoding="utf-8")
            for m in definition.finditer(text):
                found.add((module, m.group(1)))
            if module != "engine" and clamp.search(text):
                offenders.append(str(path))
        self.assertEqual(found, {("engine", "effect_of"), ("engine", "is_expired")})  # 검사가 공회전이 아님
        self.assertEqual(offenders, [])

    def case_only_the_reaction_processor_charges_and_only_it_changes_reaction_status(self):
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

    def test_single_source_rule(self):
        self.run_cases()
