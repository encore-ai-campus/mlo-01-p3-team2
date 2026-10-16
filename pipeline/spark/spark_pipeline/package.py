"""Distribute only Python application code from the Driver to Executors."""
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def package_code(destination):
    destination = Path(destination)
    with ZipFile(destination, "w") as archive:
        for source in sorted(Path(__file__).parent.glob("*.py")):
            entry = ZipInfo("spark_pipeline/" + source.name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(entry, source.read_bytes(), compress_type=ZIP_DEFLATED)
    return hashlib.sha256(destination.read_bytes()).hexdigest()
