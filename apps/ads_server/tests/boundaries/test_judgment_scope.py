"""판정 사실의 범위(설계 §10 "판정 사실의 범위")를 소스로 지킨다: `records/facts.py` 가 반응을 읽는 곳은 `scoped_reactions` 하나뿐이다.

새 조회가 범위(결정 소유 매체, 개인 슬롯의 보고된 사람)를 빠뜨리면 다른 매체의 보고가 이 결정의 판정을 바꾼다. 시험으로는 빠뜨린 조회마다 반례를 만들어야 하지만,
이 검사는 **반응을 읽는 입구가 하나인지**를 보므로 새 조회가 생겨도 걸린다. 과금이 `processing.py` 에서만 일어나는지 보는 기존 검사와 같은 방식이다.
"""
import ast
import re

from django.test import SimpleTestCase, tag

from tests.helpers import BASE_DIR

from .test_layers import project_files

FACTS = BASE_DIR / "records" / "facts.py"
ENTRANCE = "scoped_reactions"
MANAGERS = {"objects", "_default_manager", "_base_manager"}


def reaction_reads(tree):
    """`{함수 이름: 그 함수가 `Reaction` 매니저에 닿는 횟수}` — 모듈 최상위 함수만 본다(중첩·모듈 수준 접근은 `<module>` 로 센다)."""
    owner, found = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                owner[id(inner)] = node.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MANAGERS and isinstance(node.value, ast.Name) and node.value.id == "Reaction":
            name = owner.get(id(node), "<module>")
            found[name] = found.get(name, 0) + 1
    return found


def callers_of(tree, target):
    names = set()
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == target for c in ast.walk(fn)):
            names.add(fn.name)
    return names


@tag("security")
class JudgmentFactsScopeTests(SimpleTestCase):
    def tree(self):
        return ast.parse(FACTS.read_text(encoding="utf-8"))

    def test_facts_read_reactions_only_through_the_scope_function(self):
        found = reaction_reads(self.tree())
        self.assertEqual(found, {ENTRANCE: 1})  # 검사가 공회전이 아니다: 입구가 정확히 한 번 매니저에 닿는다

    def test_the_lookups_that_judgment_needs_all_use_the_entrance(self):
        """표시 교체 신호·앞 단계(노출·클릭)·인정된 유형 조회가 모두 입구를 거친다(하나라도 빠지면 그 조회는 범위 없이 읽는다)."""
        self.assertEqual(callers_of(self.tree(), ENTRANCE), {"gather", "display_signal"})
        source = FACTS.read_text(encoding="utf-8")
        gather = source[source.index("def gather"):]
        self.assertGreaterEqual(len(re.findall(rf"\b{ENTRANCE}\(", gather)), 3)  # 인정된 유형 · 클릭의 노출 · 전환의 클릭

    def test_the_reaction_model_is_not_reached_by_another_name_in_facts(self):
        """`Reaction` 을 다른 이름으로 가져오거나(`as`), 모델 레지스트리로 얻어 우회하지 못한다."""
        source = FACTS.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"import[^\n]*\bReaction\s+as\b", source))
        self.assertNotIn("get_model(", source)
        self.assertNotIn("connection", source)  # 원시 SQL 우회

    def test_the_basis_is_written_only_by_the_processor(self):
        """판정 근거(`basis`)를 쓰는 곳은 `processing._finish` 하나다(모델 정의 제외). 다른 곳이 쓰면 '한 번 쓰고 바꾸지 않는다'가 깨진다."""
        write = re.compile(r"\bbasis\s*=(?!=)")
        sites = {path.name for path in project_files("records") if "migrations" not in path.parts and write.search(path.read_text(encoding="utf-8"))}
        self.assertEqual(sites, {"models.py", "processing.py"})
