"""NDJSON 점검 결과 파일과 manifest(설계 §10 "NDJSON", 계획 4-2). **데이터를 옮기는 통로가 아니다** — 정합성 점검 결과, 재처리·백필 대상 목록, 테스트 데이터를 담는 파일이다.

**한 번의 게시 = 불변 데이터 파일 하나 + manifest 의 원자적 교체 하나.**
- 데이터 파일 `<이름>.<SHA-256 앞 16자>.ndjson`: 한 줄 = JSON 레코드 하나(UTF-8, 줄바꿈 `\\n`). 이름에 내용의 해시가 들어가므로 **한 번 만들면 바뀌지 않고**, 다른 내용은 다른 파일이 된다(덮어쓰지 않는다).
- manifest `<이름>.manifest.json`: **현재 게시본을 가리키는 포인터**다. 데이터 파일 이름, SHA-256, 행 수, `schema_version`, `source_kind`, `checkpoint`(범위 서술), 만든 시각.
- 순서: 데이터 파일을 완성(임시 파일 → fsync → `os.replace` → 폴더 fsync)한 **뒤에** manifest 를 같은 방식으로 교체한다. 그래서
  · manifest 교체가 실패하거나 중간에 죽어도 이전 manifest 와 이전 데이터 파일이 그대로다(새 데이터 파일은 가리키는 곳 없는 고아로 남는다).
  · 같은 `<이름>` 을 동시에 게시해도 manifest 는 어느 한쪽의 것으로 끝나고, 그 manifest 가 가리키는 데이터 파일은 항상 온전하다(서로 다른 파일이라 덮어쓰지 않는다).
  · manifest 가 가리키는 파일은 언제나 완결이다.
- 오래된 세대의 데이터 파일은 자동으로 지우지 않는다(읽는 쪽이 이전 manifest 를 쥐고 있을 수 있다). 보존 기간은 설계 §7-8 이 열려 있다.
- 검증(`verify`)은 manifest 를 읽고, 그것이 가리키는 파일을 다시 읽어 SHA-256·행 수·줄 형식을 대조한다.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1  # 이 모듈이 만드는 manifest 의 모양. 레코드의 모양은 호출한 쪽의 `schema_version` 이다
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
DATA_FILE = re.compile(r"[A-Za-z0-9_-]{1,64}\.[0-9a-f]{16}\.ndjson")


class NdjsonError(Exception):
    pass


def manifest_path(directory, name):
    return Path(directory) / f"{name}.manifest.json"


def _fsync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)  # 이름 바꾸기(rename) 자체도 디스크에 남긴다
    finally:
        os.close(fd)


def _replace_durably(tmp, final):
    """완성·동기화된 임시 파일을 같은 폴더의 최종 이름으로 바꾸고, 이름 바꾸기도 디스크에 남긴다(폴더 동기화). 데이터 파일과 manifest·세대 사본이 같은 단계를 쓴다."""
    os.replace(tmp, final)
    _fsync_directory(Path(final).parent)


def _publish(path, write):
    """같은 폴더의 임시 파일에 쓰고 동기화한 뒤 최종 이름으로 바꾼다. 실패하면 임시 파일을 지운다."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_durably(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def manifest_sha256(path):
    """manifest 파일(포인터) 바이트의 SHA-256. 세대 연결(`previous_sha256`)과 폴더 밖 고정점(감사 로그)이 이 값을 쓴다."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_body(manifest):
    """게시되는 manifest 파일의 바이트. 같은 manifest 는 항상 같은 바이트다 — 게시한 쪽이 반환값만으로 그 해시를 알 수 있다."""
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def manifest_digest(manifest):
    """`write` 가 반환한 manifest 가 게시된 파일의 SHA-256. 포인터 파일을 다시 읽지 않는다 — 읽는 사이 다른 실행이 바꿨을 수 있다(감사 로그의 고정점은 이 값을 쓴다)."""
    return hashlib.sha256(manifest_body(manifest)).hexdigest()


@contextlib.contextmanager
def run_lock(directory):
    """한 폴더에 여러 파일을 게시하고 그 고정점을 바깥(감사 로그)에 남기는 한 번의 실행을 통째로 직렬화한다. 포인터별 잠금(`.{이름}.lock`, `write`)과는 별개의 파일이라 중첩해도 막히지 않는다.
    로컬 파일시스템 전제(`flock`)."""
    Path(directory).mkdir(parents=True, exist_ok=True)
    with _flock(Path(directory) / ".run.lock"):
        yield


@contextlib.contextmanager
def _flock(path):
    with open(path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _generation_copy(directory, name, digest):
    return Path(directory) / f"{name}.manifest.{digest[:16]}.json"


def write(directory, name, records, source_kind, schema_version, checkpoint=None, now=None, chain=False):
    """레코드(JSON 으로 만들 수 있는 dict 들)를 새 세대의 데이터 파일로 쓰고 manifest 를 그 파일로 교체한다. 반환: manifest(dict).

    `chain=True` 면 manifest 에 직전 게시본 manifest 의 SHA-256(`previous_sha256`, 처음이면 `null`)을 싣고, 각 세대의 manifest 를 내용 해시 이름의 불변 사본으로도 남긴다
    (`<이름>.manifest.<해시 앞 16자>.json`) — 세대 사슬(`verify_chain`)이 거슬러 올라갈 수 있도록. 데이터 파일처럼 사본은 지우거나 바꾸지 않는다.
    """
    if not NAME.fullmatch(name):
        raise NdjsonError(f"이름은 영문·숫자·밑줄·하이픈 1~64자여야 한다: {name!r}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # 먼저 내용을 임시 파일에 모두 쓰고 해시를 낸다 → 최종 파일 이름에 해시가 들어간다
    digest, rows = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(prefix=f"{name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            for record in records:
                line = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                handle.write(line)
                digest.update(line)
                rows += 1
            handle.flush()
            os.fsync(handle.fileno())
        sha256 = digest.hexdigest()
        data_name = f"{name}.{sha256[:16]}.ndjson"
        _replace_durably(tmp, directory / data_name)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    manifest = {
        "manifest_version": SCHEMA_VERSION, "file": data_name, "sha256": sha256, "rows": rows, "schema_version": schema_version,
        "source_kind": source_kind, "checkpoint": checkpoint, "created_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
    }
    pointer = manifest_path(directory, name)
    # 같은 이름의 포인터를 게시하는 쪽끼리 직렬화한다(프로세스 간, `flock`): 직전 세대 읽기 → 이 세대 사본 → 포인터 교체를 한 덩어리로(동시에 게시해도 모든 성공한 세대가 사슬에 이어진다)
    with _flock(Path(directory) / f".{name}.lock"):
        if chain:
            previous = None
            if pointer.exists():
                previous = manifest_sha256(pointer)
                copy = _generation_copy(directory, name, previous)
                if not copy.exists():  # 사슬이 아닌 게시본 위에 처음 사슬을 이을 때: 직전 manifest 도 사본으로 남긴다
                    _publish(copy, lambda handle: handle.write(pointer.read_bytes()))
            manifest["previous_sha256"] = previous
        body = manifest_body(manifest)
        if chain:
            _publish(_generation_copy(directory, name, hashlib.sha256(body).hexdigest()), lambda handle: handle.write(body))  # 포인터를 바꾸기 전에 이 세대의 사본을 먼저 확정한다
        _publish(pointer, lambda handle: handle.write(body))
    return manifest


def read_manifest(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NdjsonError(f"manifest 가 없다(게시되지 않았거나 지워졌다): {path}")
    except json.JSONDecodeError as error:
        raise NdjsonError(f"manifest 를 읽을 수 없다: {error}")


def verify(path):
    """manifest 와 그것이 가리키는 데이터 파일이 맞는지 확인한다. `path` 는 manifest 경로다. 반환: 어긋난 곳의 설명 목록(맞으면 빈 목록)."""
    path = Path(path)
    manifest = read_manifest(path)
    problems = [f"manifest 에 {key} 가 없다" for key in ("file", "sha256", "rows", "schema_version", "source_kind", "created_at") if key not in manifest]
    if problems:
        return problems
    if not DATA_FILE.fullmatch(str(manifest["file"])):
        return [f"manifest 의 file 이 올바른 데이터 파일 이름이 아니다: {manifest['file']!r}"]  # 폴더 밖을 가리키지 못하게
    if not str(manifest["file"]).startswith(path.name.removesuffix(".manifest.json") + "."):
        problems.append(f"manifest {path.name} 가 다른 이름의 데이터 파일을 가리킨다: {manifest['file']}")
    try:
        content = (path.parent / manifest["file"]).read_bytes()
    except FileNotFoundError:
        return problems + [f"가리키는 데이터 파일이 없다: {manifest['file']}"]
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest["sha256"]:
        problems.append("SHA-256 이 manifest 와 다르다(파일이 바뀌었거나 깨졌다)")
    if not manifest["file"].split(".")[1] == manifest["sha256"][:16]:
        problems.append("파일 이름의 해시가 manifest 의 SHA-256 과 다르다")
    lines = content.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    elif content:
        problems.append("마지막 줄이 줄바꿈으로 끝나지 않는다(쓰다 만 파일)")
    if len(lines) != manifest["rows"]:
        problems.append(f"행 수가 manifest 와 다르다(파일 {len(lines)}, manifest {manifest['rows']})")
    for number, line in enumerate(lines, 1):
        try:
            json.loads(line)
        except ValueError:
            problems.append(f"{number}번째 줄이 JSON 이 아니다")
            break
    return problems


def verify_chain(path):
    """세대 사슬 확인: 포인터 manifest 에서 `previous_sha256` 을 따라 처음까지 거슬러 올라가며, 직전 세대 manifest 사본이 있고 SHA-256 이 맞는지 본다.
    반환: 어긋난 곳의 설명 목록. 사슬 전체를 다시 쓰는 것은 막지 못한다 — 그 고정점은 폴더 밖(감사 로그)에 있다(설계 §10 H12)."""
    path = Path(path)
    name = path.name.removesuffix(".manifest.json")
    seen = set()
    current = path.read_bytes()
    while True:
        try:
            manifest = json.loads(current)
        except ValueError:
            return ["manifest 를 읽을 수 없다"]
        previous = manifest.get("previous_sha256")
        if previous is None:
            return []  # 처음 세대
        if previous in seen:
            return ["세대 사슬이 순환한다"]
        seen.add(previous)
        copy = _generation_copy(path.parent, name, previous)
        if not copy.exists():
            return [f"직전 세대 manifest 가 없다: {copy.name}"]
        data = copy.read_bytes()
        if hashlib.sha256(data).hexdigest() != previous:
            return [f"직전 세대 manifest 가 바뀌었다: {copy.name}"]
        current = data
