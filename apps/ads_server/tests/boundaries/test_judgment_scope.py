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


WRITES_WITH_KEYWORD = {"update", "create", "get_or_create", "update_or_create", "bulk_create"}  # `basis=`(또는 `**{"basis": …}`)를 받으면 쓰기
# 아래 두 표의 위치 인덱스는 Django `QuerySet` 시그니처의 순서다(self 제외) — 키워드로 넘기든 위치로 넘기든 같은 인자를 본다
WRITES_WITH_DEFAULTS = {"get_or_create": (("defaults", 0),), "update_or_create": (("defaults", 0), ("create_defaults", 1))}  # 이 dict 에 "basis" 키가 있으면 쓰기
WRITES_WITH_FIELDS = {"bulk_update": ("fields", 1), "bulk_create": ("update_fields", 4)}  # 이 필드 목록에 "basis" 가 있으면 쓰기


def _argument(call, name, index):
    """호출에서 이름 `name`(위치 `index`)으로 넘긴 인자. 없으면 `None`."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return call.args[index] if len(call.args) > index else None


def _has_basis_key(node):
    return isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "basis" for k in node.keys)


def _sets_basis(call):
    return any(k.arg == "basis" or (k.arg is None and _has_basis_key(k.value)) for k in call.keywords)


def basis_writes(tree):
    """판정 근거를 쓰는 꼴(계획 4-4b, 외부 검토 Step 4-4 보완). 줄 번호 목록을 돌려준다.

    - `basis=`·`**{"basis": …}` 를 받는 `update`·`create`·`get_or_create`·`update_or_create`·`bulk_create`, `Reaction(basis=…)` 생성
    - `get_or_create`·`update_or_create` 의 `defaults`·`create_defaults` dict 의 `"basis"` 키
    - `bulk_update` 의 `fields`, `bulk_create` 의 `update_fields` 목록의 `"basis"`(키워드든 위치 인자든)
    - `.basis =`·`.basis +=` 대입

    쿼리셋이 `Reaction` 인지는 정적으로 가리지 않는다 — 이 꼴의 쓰기가 있는 파일 자체를 제한한다. 읽은 값을 다른 함수에 키워드로 넘기는 것은 쓰기가 아니다.
    정적 검사라 값으로 만든 인자(`update(**fields)`)까지는 보지 못한다."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "basis" and isinstance(node.ctx, ast.Store):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Reaction" and _sets_basis(node):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method = node.func.attr
            defaults = [_argument(node, name, index) for name, index in WRITES_WITH_DEFAULTS.get(method, ())]
            fields = _argument(node, *WRITES_WITH_FIELDS[method]) if method in WRITES_WITH_FIELDS else None
            if ((method in WRITES_WITH_KEYWORD and _sets_basis(node)) or any(_has_basis_key(d) for d in defaults)
                    or (fields is not None and any(isinstance(c, ast.Constant) and c.value == "basis" for c in ast.walk(fields)))):
                lines.append(node.lineno)
    return lines


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
        """판정 근거(`basis`)를 쓰는 곳은 `processing._finish` 하나다. 다른 곳이 쓰면 '한 번 쓰고 바꾸지 않는다'가 깨진다.
        글자(`basis=`)가 아니라 실제 쓰기의 꼴을 본다(`basis_writes`) — 읽은 값을 키워드 인자로 넘기는 것은 쓰기가 아니다. 모델 정의는 쓰기 꼴이 아니므로 저절로 빠지고, 마이그레이션은 보지 않는다."""
        sites = {path.name for path in project_files("records") if "migrations" not in path.parts and basis_writes(ast.parse(path.read_text(encoding="utf-8")))}
        self.assertEqual(sites, {"processing.py"})  # 검사가 공회전이 아니다: 실제로 쓰는 곳 하나를 찾는다


class BasisWriteFormsTests(SimpleTestCase):
    """`basis_writes` 가 무엇을 쓰기로 보는지(외부 검토 Step 4-4 P2: `bulk_create` 의 위치 인자 `update_fields` 를 놓쳤다). 소스 조각을 직접 넣어 본다."""

    WRITES = [
        'Reaction.objects.filter(pk=1).update(basis={})',
        'Reaction.objects.create(basis={})',
        'Reaction.objects.get_or_create(pk=1, basis={})',
        'Reaction.objects.update_or_create(pk=1, basis={})',
        'Reaction.objects.update_or_create(pk=1, defaults={"basis": {}})',
        'Reaction.objects.update_or_create(pk=1, create_defaults={"basis": {}})',
        'Reaction.objects.update_or_create({"basis": {}}, pk=1)',  # 위치 인자 defaults
        'Reaction.objects.update_or_create(None, {"basis": {}}, pk=1)',  # 위치 인자 create_defaults
        'Reaction.objects.get_or_create({"basis": {}}, pk=1)',
        'Reaction.objects.filter(pk=1).update(**{"basis": {}})',
        'Reaction.objects.bulk_create([row], basis={})',
        'Reaction.objects.bulk_create([row], update_conflicts=True, update_fields=["basis"])',
        'Reaction.objects.bulk_create([row], None, False, True, ["basis"])',  # 위치 인자: update_fields 는 다섯 번째
        'Reaction.objects.bulk_update([row], ["basis"])',
        'Reaction.objects.bulk_update([row], fields=("status", "basis"))',
        'Reaction(pk=1, basis={})',
        'row.basis = {}',
        'row.status, row.basis = 1, {}',
        'row.basis += {}',
    ]
    READS = [
        'events.record_reaction(basis=row.basis)',
        'Reaction.objects.filter(basis=x).count()',
        'Reaction.objects.values("basis")',
        'x = row.basis',
        'Reaction.objects.bulk_create([row], 500)',  # 두 번째 위치 인자는 batch_size
        'Reaction.objects.bulk_create([row], None, False, True, ["status"])',
        'Reaction.objects.bulk_update([row], ["status"], 500)',
        'Reaction.objects.update_or_create(pk=1, defaults={"status": 1})',
        'dict(basis=row.basis)',
        'Reaction.objects.get_or_create({"status": 1}, pk=1)',
        'Reaction.objects.bulk_update([row], fields=["status"])',
    ]

    def test_each_write_form_is_found(self):
        for source in self.WRITES:
            with self.subTest(source):
                self.assertTrue(basis_writes(ast.parse(source)))

    def test_reads_and_other_fields_are_not_writes(self):
        for source in self.READS:
            with self.subTest(source):
                self.assertEqual(basis_writes(ast.parse(source)), [])
