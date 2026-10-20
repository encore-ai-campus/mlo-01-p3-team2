"""저장소 HEAD 에서 각 서버에 필요한 파일만 묶는다.

    python tools/build_release.py OUT     # OUT/ads_server-<커밋>.tar.gz(백 서버), OUT/ads_frontend-<커밋>.tar.gz(프론트 서버)

실행·개발 도구(`tools/`)·문서(README)·개발 설정·상대 앱은 넣지 않는다.
커밋한 것(HEAD)만 들어간다 — 커밋하지 않은 변경이 있으면 알린다.
"""
import io
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BUNDLES = {  # 이름: (저장소 안 폴더, 뺄 것 — "/" 로 끝나면 폴더)
    "ads_server": ("apps/ads_server", ("tests/", "tools/", "README.md", ".gitignore", "config/settings/dev.py", "config/settings/test.py")),
    "ads_frontend": ("apps/ads_frontend", ("tests/", "README.md", ".gitignore", "config/settings_test.py")),
}
FORBIDDEN = ("from tests", "import tests")  # 묶음 안의 코드가 뺀 시험 코드를 가져오면 서버에서 깨진다


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def build(out):
    commit = git("rev-parse", "--short", "HEAD").decode().strip()
    if git("status", "--porcelain", "--untracked-files=no", "--", *(root for root, _ in BUNDLES.values())):
        print("알림: 커밋하지 않은 변경은 묶음에 들어가지 않는다(HEAD 기준)")
    out.mkdir(parents=True, exist_ok=True)
    for name, (root, excluded) in BUNDLES.items():
        source = tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD", "--", root)))
        target, problems, count = out / f"{name}-{commit}.tar.gz", [], 0
        with tarfile.open(target, "w:gz") as tar:
            for member in source.getmembers():
                rel = member.name[len(root) + 1:]
                if not member.isfile() or any(rel == e or rel.startswith(e) for e in excluded):
                    continue
                data = source.extractfile(member).read()
                if rel.endswith(".py") and any(line.lstrip().startswith(FORBIDDEN) for line in data.decode().splitlines()):
                    problems.append(rel)
                member.name, member.size = f"{name}/{rel}", len(data)
                tar.addfile(member, io.BytesIO(data))
                count += 1
        if problems:
            target.unlink()
            raise SystemExit(f"{name}: 묶음 안의 코드가 시험 코드를 가져온다 — {problems}")
        print(f"{target}  파일 {count}개")
    return commit


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]).resolve())
