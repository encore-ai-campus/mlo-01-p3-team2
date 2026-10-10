"""NDJSON 점검 결과 파일과 manifest(설계 §10 "NDJSON", 계획 4-2). **데이터를 옮기는 통로가 아니다** — 정합성 점검 결과, 재처리·백필 대상 목록, 테스트 데이터를 담는 파일이다.

- 데이터 파일 `<이름>.ndjson`: 한 줄 = JSON 레코드 하나(UTF-8, 줄바꿈 `\\n`).
- manifest `<이름>.manifest.json`: 데이터 파일의 SHA-256, 행 수, `schema_version`, `source_kind`, 재개 위치(`checkpoint`), 만든 시각.
- **원자적 확정**: 둘 다 임시 파일에 쓰고 디스크에 동기화한 뒤 `os.replace` 로 바꾼다. 데이터 파일을 먼저, manifest 를 나중에 확정하므로 **manifest 가 있으면 데이터 파일은 완결**이다.
  중간에 죽어도 반쯤 쓰인 파일이 최종 이름으로 남지 않는다.
- 검증(`verify`)은 파일을 다시 읽어 SHA-256·행 수를 manifest 와 대조한다.
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1  # 이 모듈이 만드는 manifest 의 모양. 레코드의 모양은 호출한 쪽의 `schema_version` 이다


class NdjsonError(Exception):
    pass


def manifest_path(data_path):
    path = Path(data_path)
    return path.with_name(path.stem + ".manifest.json")


def _replace_atomically(path, write):
    """같은 폴더의 임시 파일에 쓰고 동기화한 뒤 최종 이름으로 바꾼다. 실패하면 임시 파일을 지운다."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write(data_path, records, source_kind, schema_version, checkpoint=None, now=None):
    """레코드(JSON 으로 만들 수 있는 dict 들)를 NDJSON 으로 쓰고 manifest 를 확정한다. 반환: manifest(dict)."""
    data_path = Path(data_path)
    digest, rows = hashlib.sha256(), 0

    def write_data(handle):
        nonlocal rows
        for record in records:
            line = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            handle.write(line)
            digest.update(line)
            rows += 1

    _replace_atomically(data_path, write_data)
    manifest = {
        "manifest_version": SCHEMA_VERSION, "file": data_path.name, "sha256": digest.hexdigest(), "rows": rows, "schema_version": schema_version,
        "source_kind": source_kind, "checkpoint": checkpoint, "created_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
    }
    _replace_atomically(manifest_path(data_path), lambda handle: handle.write((json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")))
    return manifest


def read_manifest(data_path):
    try:
        return json.loads(manifest_path(data_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NdjsonError(f"manifest 가 없다(데이터 파일이 완결되지 않았을 수 있다): {manifest_path(data_path)}")
    except json.JSONDecodeError as error:
        raise NdjsonError(f"manifest 를 읽을 수 없다: {error}")


def verify(data_path):
    """데이터 파일이 manifest 와 맞는지 확인한다. 반환: 어긋난 곳의 설명 목록(맞으면 빈 목록)."""
    manifest = read_manifest(data_path)
    data_path = Path(data_path)
    problems = [f"manifest 에 {key} 가 없다" for key in ("file", "sha256", "rows", "schema_version", "source_kind", "created_at") if key not in manifest]
    if problems:
        return problems
    if manifest["file"] != data_path.name:
        problems.append(f"manifest 는 {manifest['file']} 의 것이다(파일 이름 {data_path.name})")
    try:
        content = data_path.read_bytes()
    except FileNotFoundError:
        return problems + [f"데이터 파일이 없다: {data_path}"]
    if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        problems.append("SHA-256 이 manifest 와 다르다(파일이 바뀌었거나 깨졌다)")
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
