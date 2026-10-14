"""시험·부하용 MySQL 관리 도우미. 접속 값은 환경변수(DB_*)와 `.env` 에서 읽는다.

    python tests/tools/mysql_admin.py            접속 점검: 서버 8.4 에 닿는지, 시험 DB 를 만들 권한이 있는지(없으면 이유를 말하고 비정상 종료)

    python tests/tools/mysql_admin.py --print-env  `.env` 를 읽어 DB_* 를 셸 `export` 문으로 출력한다(check.sh 가 eval)

`check.sh` 가 맨 앞에서 부른다 — DB 가 없으면 시험을 건너뛰지 않고 여기서 멈춘다.
"""
import os
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from config.env import load_env  # noqa: E402

COLLATION = "utf8mb4_0900_as_cs"  # settings.base.mysql_config 와 같은 값


def connect():
    import MySQLdb

    load_env()
    missing = [n for n in ("DB_USER", "DB_PASSWORD") if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"환경변수 {', '.join(missing)} 가 필요합니다(.env.example, README 'MySQL 시험 환경').")
    try:
        return MySQLdb.connect(host=os.environ.get("DB_HOST", "127.0.0.1"), port=int(os.environ.get("DB_PORT", 3306)),
                               user=os.environ["DB_USER"], passwd=os.environ["DB_PASSWORD"], connect_timeout=5)
    except MySQLdb.Error as exc:
        raise SystemExit(f"MySQL 에 연결하지 못했습니다: {exc}\n시험용 컨테이너가 떠 있는지 확인하세요(README 'MySQL 시험 환경').")


_OWNED = set()  # 이 프로세스가 CREATE 에 성공한 데이터베이스. 이것만 지운다(이름이 겹친 남의 DB 는 건드리지 않는다)


def create_database(prefix):
    """무작위 이름의 새 데이터베이스를 만들어 이름을 돌려준다. 이미 있는 이름이면 지우지 않고 실패한다(CREATE 는 `IF NOT EXISTS` 없이)."""
    import MySQLdb

    name = f"{prefix}_{uuid.uuid4().hex}"
    conn = connect()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE {COLLATION}")
            except MySQLdb.Error as exc:
                raise SystemExit(f"데이터베이스 {name} 을 만들지 못했습니다: {exc}")
        _OWNED.add(name)
    finally:
        conn.close()
    return name


def drop_database(name):
    """이 프로세스가 만든 데이터베이스만 지운다. 만들지 않은 이름이면 거부한다."""
    if name not in _OWNED:
        raise ValueError(f"{name} 은 이 실행이 만든 데이터베이스가 아니라 지우지 않는다")
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        _OWNED.discard(name)
    finally:
        conn.close()


def preflight():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
        if not version.startswith("8.4."):
            raise SystemExit(f"MySQL 8.4 가 필요합니다(지금 {version}).")
    finally:
        conn.close()
    drop_database(create_database("ads_preflight"))  # 생성·삭제 권한 확인: 무작위 이름이라 남의 DB 와 겹치지 않는다
    print(f"MySQL {version} 연결 확인, 데이터베이스 생성·삭제 권한 확인")


def print_env():
    import shlex

    load_env()
    for name in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT"):
        if os.environ.get(name):
            print(f"export {name}={shlex.quote(os.environ[name])}")


if __name__ == "__main__":
    print_env() if sys.argv[1:] == ["--print-env"] else preflight()
