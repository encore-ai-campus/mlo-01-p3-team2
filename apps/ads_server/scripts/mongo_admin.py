"""시험용 MongoDB 접속 점검. 접속 값은 환경변수(MONGO_*)와 `.env` 에서 읽는다.

    python scripts/mongo_admin.py     서버 8.x 에 닿는지, 무작위 이름의 시험 데이터베이스에 쓸 수 있는지(끝나면 그 이름만 지운다)

`check.sh` 가 `mysql_admin.py` 바로 뒤에 부른다 — MongoDB 가 없으면 시험을 건너뛰지 않고 여기서 멈춘다.
"""
import os
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.env import load_env  # noqa: E402


def preflight():
    load_env()
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    import django

    django.setup()
    from pymongo.errors import PyMongoError

    from events import mongo

    name = f"ads_events_preflight_{uuid.uuid4().hex}"
    try:
        version = mongo.client().server_info()["version"]
        if not version.startswith("8."):
            raise SystemExit(f"MongoDB 8.x 가 필요합니다(지금 {version}).")
        mongo.client()[name]["probe"].insert_one({"_id": uuid.uuid4()})
        mongo.client().drop_database(name)
    except PyMongoError as exc:
        raise SystemExit(f"MongoDB 에 연결하거나 쓰지 못했습니다: {type(exc).__name__}: {str(exc)[:200]}\n"
                         "시험용 컨테이너가 떠 있는지, .env 의 MONGO_* 가 맞는지 확인하세요(README 'MongoDB 시험 환경').")
    finally:
        mongo.close()
    print(f"MongoDB {version} 연결 확인, 데이터베이스 쓰기·삭제 확인")


if __name__ == "__main__":
    preflight()
