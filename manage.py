"""Compatibility entry point for backend management commands."""
from pathlib import Path
import os
import runpy
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
    if (root / "db.sqlite3").is_file():
        os.environ.setdefault("CAMPUS_DATA_DIR", str(root))
    sys.path.insert(0, str(root / "backend"))
    runpy.run_path(str(root / "backend/manage.py"), run_name="__main__")
