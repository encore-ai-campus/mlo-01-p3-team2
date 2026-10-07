"""저장소. 구현이 갈아끼워지는 곳(로컬 파일 → 이후 객체 저장소)이라 인터페이스를 둔다(설계 §6.2)."""
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol

NAME_RE = re.compile(r"[0-9a-f]{64}\.(?:jpg|png)")


class AssetStorage(Protocol):
    def put(self, name: str, data: bytes) -> None: ...
    def open(self, name: str) -> BinaryIO: ...
    def exists(self, name: str) -> bool: ...


class LocalFileStorage:
    """`<root>/<해시 앞 2자>/<해시>.<ext>`. 사용자 입력 이름은 어디에도 쓰지 않는다."""

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, name):
        if not NAME_RE.fullmatch(name or ""):  # 경로 조작 방지: 형식에 맞는 이름만 경로가 된다
            raise ValueError("올바르지 않은 소재 이름입니다.")
        return self.root / name[:2] / name

    def put(self, name, data):
        final = self._path(name)
        if final.is_file():  # 내용 해시가 같으면 같은 파일이다(중복 제거)
            return
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        fd, tmp = tempfile.mkstemp(dir=final.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o640)
            os.replace(tmp, final)  # 원자적 확정: 반쯤 쓴 파일이 최종 경로에 나타나지 않는다
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    def open(self, name):
        return open(self._path(name), "rb")

    def exists(self, name):
        try:
            return self._path(name).is_file()
        except ValueError:
            return False
