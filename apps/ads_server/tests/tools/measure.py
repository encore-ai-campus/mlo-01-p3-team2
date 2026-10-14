"""6-18 시험 축소의 측정(계획서 §8.4.19): 제품 코드 커버리지와 고정 변형 목록.

시험을 합치거나 지운 뒤에도 ① 제품 코드에서 덮이던 줄·분기가 그대로 덮이고 ② 기준선에서 잡던 변형을 모두 잡는지 본다.

    python tests/tools/measure.py coverage OUT                # 전체 시험을 커버리지로(시험마다 문맥) → OUT/.coverage, OUT/coverage.json
    python tests/tools/measure.py mutants COV OUT.json        # COV 에서 덮인 줄의 변형 목록(고정 시드 618, 약 300개)
    python tests/tools/measure.py run MUTANTS.json COV OUT.json [--workers 4] [--recheck]
    python tests/tools/measure.py compare BASE_COV BASE_RUN NEW_COV NEW_RUN

변형마다 그 줄을 덮은 시험만 돌린다(`--keepdb --failfast`). `--recheck` 는 살아남은 변형을 전체 시험으로 다시 본다(준비 단계에서만 지나는 줄 등).
일꾼마다 저장소 사본(apps·docs)과 DB(`DB_NAME=ads_mut{n}`, 시험 DB `test_ads_mut{n}`)를 따로 쓴다. 접속 값은 원래 `.env` 를 가리키는 링크로 읽는다.
"""
import argparse
import ast
import copy
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # apps/ads_server
REPO = APP.parent.parent
PACKAGES = ["foundation", "masters", "engine", "assets", "events", "campaigns", "billing", "records", "serving_api", "console", "config"]
SOURCES = [str(APP / p) for p in PACKAGES] + [str(APP.parent / "ads_frontend" / "ui")]  # 프론트 화면 코드도 백엔드 시험이 그린다
TOTAL = 300
SEED = 618
SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
        ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
FAILED = re.compile(r"^(?:FAIL|ERROR): \S+ \(([\w.]+)\)", re.M)


def python():
    return os.environ.get("PYTHON", sys.executable)


def _mysql(*sql):
    sys.path.insert(0, str(APP / "tests" / "tools"))
    from mysql_admin import connect
    conn = connect()
    try:
        with conn.cursor() as cur:
            for q in sql:
                cur.execute(q)
            return cur.fetchall()
    finally:
        conn.close()


def ensure_db(name):
    """`DB_NAME` 의 실제 DB 가 있어야 한다(배포 점검 시험이 새 프로세스에서 그 DB 에 접속한다). 없으면 빈 DB 를 만들고 True — 끝나면 그것만 지운다."""
    if _mysql(f"SHOW DATABASES LIKE '{name}'"):
        return False
    _mysql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs")
    return True


def rel(path):
    return str(Path(path).resolve().relative_to(REPO))


# ---- 커버리지 ----

def run_coverage(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rc = out / "rc"
    rc.write_text("[run]\nbranch = True\ndynamic_context = test_function\nomit = */migrations/*\n"
                  f"data_file = {out / '.coverage'}\nsource =\n" + "".join(f"    {s}\n" for s in SOURCES), encoding="utf-8")
    env = {**os.environ, "DB_NAME": os.environ.get("DB_NAME", "ads_cov")}
    created = ensure_db(env["DB_NAME"])
    started = time.time()
    try:
        done = subprocess.run([python(), "-m", "coverage", "run", f"--rcfile={rc}", "manage.py", "test", "--noinput"], cwd=APP, env=env)
    finally:
        if created:
            _mysql(f"DROP DATABASE IF EXISTS `{env['DB_NAME']}`")
    print(f"시험 {'통과' if done.returncode == 0 else '실패'} ({time.time() - started:.0f}초)")
    summarize(out)
    return done.returncode


def summarize(out):
    """줄·분기 덮임을 파일마다 저장한다(문맥 없이). 비교는 이 파일로 한다."""
    import coverage
    cov = coverage.Coverage(data_file=str(Path(out) / ".coverage"))
    cov.load()
    data, files, totals = cov.get_data(), {}, defaultdict(int)
    for f in sorted(data.measured_files()):
        analysis = cov._analyze(f)
        n = analysis.numbers
        covered = sorted(set(analysis.statements) - set(analysis.missing))
        source = Path(f).read_text(encoding="utf-8").splitlines()
        files[rel(f)] = {"statements": n.n_statements, "covered": covered, "covered_text": [source[ln - 1].strip() for ln in covered],
                         "branches": n.n_branches, "covered_branches": n.n_branches - n.n_missing_branches}
        totals["statements"] += n.n_statements
        totals["covered"] += len(covered)
        totals["branches"] += n.n_branches
        totals["covered_branches"] += n.n_branches - n.n_missing_branches
    (Path(out) / "coverage.json").write_text(json.dumps({"totals": totals, "files": files}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"줄 {totals['covered']}/{totals['statements']} · 분기 {totals['covered_branches']}/{totals['branches']}")


def tests_by_line(cov_dir):
    """{파일(저장소 기준): {줄: {시험 ID}}} — 시험 함수 안에서 지난 줄만(가져올 때 지난 줄은 문맥이 비어 있다)."""
    import coverage
    data = coverage.CoverageData(str(Path(cov_dir) / ".coverage"))
    data.read()
    out = {}
    for f in data.measured_files():
        out[rel(f)] = {ln: {c for c in ctx if c} for ln, ctx in data.contexts_by_lineno(f).items()}
    return out


# ---- 변형 ----

def _char_col(line, byte_col):
    return len(line.encode("utf-8")[:byte_col].decode("utf-8"))


def _span(lines, node):
    return [node.lineno, _char_col(lines[node.lineno - 1], node.col_offset), node.end_lineno, _char_col(lines[node.end_lineno - 1], node.end_col_offset)]


def sites(path, covered_lines):
    """함수 안의, 시험이 덮은 줄에서 만들 수 있는 변형: 비교 뒤집기·and/or·조건 부정·정수 +1·덧셈/뺄셈·호출 문장 빼기."""
    src = Path(path).read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    found = {}
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        body = ast.Module(body=fn.body, type_ignores=[])
        for node in ast.walk(body):
            if getattr(node, "lineno", None) not in covered_lines:
                continue
            target, after, kind = node, None, None
            if isinstance(node, ast.Compare) and type(node.ops[0]) in SWAP:
                new = copy.deepcopy(node)
                new.ops[0] = SWAP[type(node.ops[0])]()
                after, kind = ast.unparse(new), "compare"
            elif isinstance(node, ast.BoolOp):
                new = copy.deepcopy(node)
                new.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
                after, kind = ast.unparse(new), "boolop"
            elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
                target = node.test
                after, kind = f"not ({ast.get_source_segment(src, node.test)})", "negate"
            elif isinstance(node, ast.Constant) and type(node.value) is int:
                after, kind = str(node.value + 1), "int+1"
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
                new = copy.deepcopy(node)
                new.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
                after, kind = ast.unparse(new), "add/sub"
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                after, kind = "pass", "drop-call"
            if kind is None:
                continue
            span = _span(lines, target)
            before = ast.get_source_segment(src, target)
            if before is None or before == after:
                continue
            found[tuple(span)] = {"file": rel(path), "span": span, "kind": kind, "before": before, "after": after}
    return list(found.values())


def apply(src, m):
    """변형을 넣는다. 제품 코드에 줄이 더해져 자리가 밀렸으면 가까운(±30줄) 같은 원문 자리를 찾는다."""
    lines = src.splitlines(keepends=True)
    l1, c1, l2, c2 = m["span"]
    for shift in sorted(range(-30, 31), key=abs):
        if not 1 <= l1 + shift <= len(lines):
            continue
        start = sum(len(x) for x in lines[:l1 + shift - 1]) + c1
        end = start + len(m["before"])
        if src[start:end] == m["before"]:
            return src[:start] + m["after"] + src[end:]
    raise ValueError(f"{m['id']}: 원문이 바뀌었다 — {m['file']}:{l1}")


def make_mutants(cov_dir, out):
    by_line = tests_by_line(cov_dir)
    pool = defaultdict(list)
    for f, lines in sorted(by_line.items()):
        if not f.endswith(".py"):
            continue
        tested = {ln for ln, ids in lines.items() if ids}
        for m in sites(REPO / f, tested):
            try:
                ast.parse(apply((REPO / f).read_text(encoding="utf-8"), {**m, "id": "?"}))
            except SyntaxError:
                continue
            pool[Path(f).parts[2] if f.startswith("apps/ads_server/") else "frontend"].append(m)
    total = sum(len(v) for v in pool.values())
    rng, chosen = random.Random(SEED), []
    for pkg in sorted(pool):  # 패키지마다 자리 수에 비례, 최소 8개
        items = sorted(pool[pkg], key=lambda m: (m["file"], m["span"]))
        chosen += rng.sample(items, min(len(items), max(8, round(TOTAL * len(items) / total))))
    chosen.sort(key=lambda m: (m["file"], m["span"]))
    for i, m in enumerate(chosen, 1):
        m["id"] = f"m{i:03d}"
    Path(out).write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"자리 {total}개 중 {len(chosen)}개: " + ", ".join(f"{k} {sum(1 for m in chosen if (Path(m['file']).parts[2] if m['file'].startswith('apps/ads_server/') else 'frontend') == k)}" for k in sorted(pool)))


# ---- 실행 ----

def _copy(dest):
    (dest / "apps").mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", ".env", "media", "staticfiles", ".coverage*")
    for sub in ("apps/ads_server", "apps/ads_frontend", "docs/ads-server"):
        shutil.copytree(REPO / sub, dest / sub, ignore=ignore)
    if (APP / ".env").exists():
        (dest / "apps/ads_server/.env").symlink_to(APP / ".env")


def _labels(m, by_line):
    lines = by_line.get(m["file"], {})
    ids = set().union(*(lines.get(ln, set()) for ln in range(m["span"][0], m["span"][2] + 1)))
    if len(ids) > 300:  # 많으면 모듈 단위로(명령 줄 길이)
        ids = {i.rsplit(".", 2)[0] for i in ids}
    return sorted(ids)


def _run_one(copy_dir, n, m, labels, timeout):
    path = copy_dir / m["file"]
    original = path.read_text(encoding="utf-8")
    path.write_text(apply(original, m), encoding="utf-8")
    started = time.time()
    try:
        done = subprocess.run([python(), "manage.py", "test", "--keepdb", "--failfast", "--noinput", "-v", "1", *labels],
                              cwd=copy_dir / "apps/ads_server", env={**os.environ, "DB_NAME": f"ads_mut{n}"},
                              capture_output=True, text=True, timeout=timeout)
        failed = FAILED.search(done.stderr)
        status = "survived" if done.returncode == 0 else "killed"
        by = failed.group(1) if failed else (None if done.returncode == 0 else done.stderr.strip().splitlines()[-1][:200])
    except subprocess.TimeoutExpired:
        status, by = "killed", "timeout"
    finally:
        path.write_text(original, encoding="utf-8")
    return {"status": status, "by": by, "seconds": round(time.time() - started, 1), "labels": len(labels)}


def run_mutants(mutants_file, cov_dir, out, workers=4, recheck=False, only=None):
    mutants = json.loads(Path(mutants_file).read_text(encoding="utf-8"))
    if only:
        mutants = [m for m in mutants if m["id"] in only]
    by_line = tests_by_line(cov_dir)
    results = json.loads(Path(out).read_text(encoding="utf-8")) if Path(out).exists() else {}
    todo = queue.Queue()
    for m in mutants:
        if m["id"] not in results or (recheck and results[m["id"]]["status"] == "survived" and not results[m["id"]].get("full")):
            todo.put(m)
    lock, work = threading.Lock(), Path(tempfile.mkdtemp(prefix="measure-"))
    created = [n for n in range(1, workers + 1) if ensure_db(f"ads_mut{n}")]
    print(f"변형 {todo.qsize()}개, 일꾼 {workers}, 사본 {work}")

    def worker(n):
        copy_dir = work / f"w{n}"
        _copy(copy_dir)
        warm = subprocess.run([python(), "manage.py", "test", "--keepdb", "--noinput", "-v", "0", "tests.ops.test_engine_pricing"],
                              cwd=copy_dir / "apps/ads_server", env={**os.environ, "DB_NAME": f"ads_mut{n}"}, capture_output=True, text=True)
        if warm.returncode != 0:  # 변형 없이 실패하면 환경 문제다 — 이 일꾼의 결과는 믿을 수 없다
            print(f"일꾼 {n}: 변형 없는 시험이 실패해 멈춘다\n{warm.stderr[-2000:]}", flush=True)
            return
        while True:
            try:
                m = todo.get_nowait()
            except queue.Empty:
                return
            full = recheck and m["id"] in results
            labels = ["tests"] if full else _labels(m, by_line)
            r = _run_one(copy_dir, n, m, labels, timeout=1800 if full else 600)
            r["full"] = full
            with lock:
                results[m["id"]] = r
                Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
                print(f"{m['id']} {r['status']:<8} {r['seconds']:>6}s 시험 {r['labels']:>4}  {m['file']}:{m['span'][0]} {m['kind']}", flush=True)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(1, workers + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    shutil.rmtree(work, ignore_errors=True)
    # 이 명령이 --keepdb 로 남긴 시험 DB 와 여기서 만든 빈 DB 만 지운다(이름이 ads_mut{n} 에서 정해진다)
    _mysql(*[f"DROP DATABASE IF EXISTS `test_ads_mut{n}`" for n in range(1, workers + 1)], *[f"DROP DATABASE IF EXISTS `ads_mut{n}`" for n in created])
    killed = sum(1 for r in results.values() if r["status"] == "killed")
    print(f"잡음 {killed} / {len(results)}")


def compare(base_cov, base_run, new_cov, new_run):
    """기준선보다 나빠진 곳만 보인다: 덮이지 않게 된 줄, 기준선에서 잡던 변형 중 지금 살아남은 것. 둘 다 없으면 종료 코드 0."""
    b = json.loads((Path(base_cov) / "coverage.json").read_text(encoding="utf-8"))["files"]
    n = json.loads((Path(new_cov) / "coverage.json").read_text(encoding="utf-8"))["files"]
    def lost_lines(f, v):  # 줄의 내용으로 비교한다(제품 코드에 줄이 더해져 번호가 밀려도 같은 줄이다). 내용이 없으면 번호로
        new = n.get(f, {})
        if "covered_text" in v and "covered_text" in new:
            now = {line.strip() for line in (REPO / f).read_text(encoding="utf-8").splitlines()} if (REPO / f).exists() else set()
            return sorted(t for t in (Counter(v["covered_text"]) - Counter(new["covered_text"])).elements() if t in now)  # 고친·지운 줄은 덮일 수 없다
        return sorted(set(v["covered"]) - set(new.get("covered", [])))
    lost = {f: lost_lines(f, v) for f, v in b.items()}
    lost = {f: v for f, v in lost.items() if v}
    br = json.loads(Path(base_run).read_text(encoding="utf-8"))
    nr = json.loads(Path(new_run).read_text(encoding="utf-8"))
    missed = sorted(i for i, r in br.items() if r["status"] == "killed" and nr.get(i, {}).get("status") != "killed")
    for f, v in lost.items():
        print(f"덮이지 않게 된 줄 {f}: {v}")
    for i in missed:
        print(f"기준선에서 잡던 변형을 놓침: {i} ({nr.get(i, {}).get('status', '돌리지 않음')})")
    print(f"덮이지 않게 된 줄 {sum(len(v) for v in lost.values())} · 놓친 변형 {len(missed)}")
    return 1 if lost or missed else 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("coverage").add_argument("out")
    s = sub.add_parser("mutants")
    s.add_argument("cov")
    s.add_argument("out")
    s = sub.add_parser("run")
    s.add_argument("mutants")
    s.add_argument("cov")
    s.add_argument("out")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--recheck", action="store_true")
    s.add_argument("--only", nargs="*")
    s = sub.add_parser("compare")
    for a in ("base_cov", "base_run", "new_cov", "new_run"):
        s.add_argument(a)
    a = p.parse_args()
    if a.cmd == "coverage":
        return run_coverage(a.out)
    if a.cmd == "mutants":
        return make_mutants(a.cov, a.out)
    if a.cmd == "run":
        return run_mutants(a.mutants, a.cov, a.out, a.workers, a.recheck, a.only)
    return compare(a.base_cov, a.base_run, a.new_cov, a.new_run)


if __name__ == "__main__":
    sys.exit(main())
