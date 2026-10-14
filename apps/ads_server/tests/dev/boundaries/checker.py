"""경계 검사기 (설계 R1·R2·R6). ast 로 import 를 읽는다. 층 정의는 test_layers.py 의 LAYERS 딕셔너리 **하나**다."""
import ast

STDLIB_ONLY_FORBIDDEN_ROOTS = {"django"}  # engine 은 django·프로젝트 모듈을 import 하지 않는다


def imports_of(source):
    """(모듈 전체 경로, 가져온 이름들). 상대 import 는 같은 모듈 안이므로 제외한다."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, ()
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, tuple(a.name for a in node.names)


def find_violations(module, source, layers):
    """module 의 소스가 R1(아래 방향만, 같은 층끼리도 금지)·R2(다른 모듈은 api 만)를 어기는 import 목록."""
    violations = []
    own_layer = layers[module]
    for full, names in imports_of(source):
        parts = full.split(".")
        top = parts[0]
        if top == module or top not in layers:
            continue
        if layers[top] >= own_layer:
            violations.append(f"R1: {module}(층 {own_layer}) 이 {top}(층 {layers[top]}) 을 import 한다: {full}")
        only_api = (len(parts) >= 2 and parts[1] == "api") or (len(parts) == 1 and names == ("api",))
        if not only_api:
            violations.append(f"R2: {module} 이 {top} 의 내부를 import 한다(api 만 허용): {full} {names or ''}".strip())
    return violations


def find_engine_violations(source, layers):
    """engine 순수성: django·프로젝트 모듈(및 config)을 import 하지 않는다."""
    bad = []
    for full, _names in imports_of(source):
        top = full.split(".")[0]
        if top in STDLIB_ONLY_FORBIDDEN_ROOTS or top in layers or top == "config":
            bad.append(f"engine 이 {full} 을 import 한다")
    return bad


def find_fk_violations(source):
    """models.py 의 FK/O2O/M2M 첫 인자는 라벨 문자열이거나 settings.AUTH_USER_MODEL 이거나 같은 파일의 클래스여야 한다(R3)."""
    tree = ast.parse(source)
    local_classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
            "ForeignKey", "OneToOneField", "ManyToManyField",
        ):
            target = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "to"), None)
            ok = (
                isinstance(target, ast.Constant) and isinstance(target.value, str)
                or (isinstance(target, ast.Attribute) and ast.unparse(target) == "settings.AUTH_USER_MODEL")
                or (isinstance(target, ast.Name) and target.id in local_classes)
            )
            if not ok:
                bad.append(f"라인 {node.lineno}: 다른 앱 모델을 라벨 문자열 없이 참조한다: {ast.unparse(target) if target else '?'}")
    return bad
