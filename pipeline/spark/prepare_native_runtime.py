"""Optional native fallback: download the official Kafka distribution into ignored artifacts."""
import shutil
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    runtime = ROOT / "artifacts/native-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    archive = runtime / "kafka_2.13-4.3.1.tgz"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        with urlopen("https://archive.apache.org/dist/kafka/4.3.1/kafka_2.13-4.3.1.tgz", timeout=60) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        temporary.rename(archive)
    with tarfile.open(archive) as package:
        package.extractall(runtime, filter="data")
    print(runtime / "kafka_2.13-4.3.1")
