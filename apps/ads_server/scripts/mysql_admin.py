"""시험·부하용 MySQL 관리 도우미. 접속 값은 환경변수(DB_*)와 `.env` 에서 읽는다.

    python scripts/mysql_admin.py            접속 점검: 서버 8.4 에 닿는지, 시험 DB 를 만들 권한이 있는지(없으면 이유를 말하고 비정상 종료)

    python scripts/mysql_admin.py --print-env  `.env` 를 읽어 DB_* 를 셸 `export` 문으로 출력한다(check.sh 가 eval)

`check.sh` 가 맨 앞에서 부른다 — DB 가 없으면 시험을 건너뛰지 않고 여기서 멈춘다.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
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


def create_database(name):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE {COLLATION}")
    conn.close()


def drop_database(name):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    conn.close()


def preflight():
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        if not version.startswith("8.4."):
            raise SystemExit(f"MySQL 8.4 가 필요합니다(지금 {version}).")
        cur.execute("CREATE DATABASE IF NOT EXISTS ads_preflight")
        cur.execute("DROP DATABASE ads_preflight")
    print(f"MySQL {version} 연결 확인, 데이터베이스 생성·삭제 권한 확인")


def print_env():
    import shlex

    load_env()
    for name in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT"):
        if os.environ.get(name):
            print(f"export {name}={shlex.quote(os.environ[name])}")


if __name__ == "__main__":
    print_env() if sys.argv[1:] == ["--print-env"] else preflight()
