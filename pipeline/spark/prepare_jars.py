"""Download the user-pinned JARs; refuse any checksum mismatch."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def prepare(directory, verify_only=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "runtime_lock.json").read_text())
    verified = []
    for item in lock["spark_connector_jars"]:
        path = directory / Path(item["path"]).name
        if not path.exists():
            if verify_only:
                raise FileNotFoundError(path.name)
            with urlopen("https://repo.maven.apache.org/maven2/" + item["path"], timeout=60) as response:
                payload = response.read()
            actual = hashlib.sha256(payload).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(f"Checksum mismatch: {path.name}; expected={item['sha256']} actual={actual}")
            path.write_bytes(payload)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.name}; expected={item['sha256']} actual={actual}")
        verified.append({"name": path.name, "sha256": actual})
    return verified


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default=str(ROOT / "jars"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory, args.verify_only), indent=2))
