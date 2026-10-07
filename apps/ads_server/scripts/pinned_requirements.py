"""requirements.txt 의 **설치된 의존성 전체(전이 포함)** 를 `name==version` 으로 출력한다. pip-audit 입력용(scripts/check.sh)."""
import re, sys
from importlib.metadata import PackageNotFoundError, requires, version
from packaging.requirements import Requirement
seen, todo = {}, []
for line in open("requirements.txt", encoding="utf-8"):
    line = line.split("#")[0].strip()
    if line:
        todo.append(Requirement(line).name)
while todo:
    name = todo.pop()
    key = re.sub(r"[-_.]+", "-", name).lower()
    if key in seen: continue
    try: seen[key] = version(name)
    except PackageNotFoundError: seen[key] = None; continue
    for r in requires(name) or []:
        req = Requirement(r)
        if req.marker is not None and not req.marker.evaluate({"extra": ""}): continue
        todo.append(req.name)
for k in sorted(seen):
    if seen[k]: print(f"{k}=={seen[k]}")
