"""tests/tools/mysql_admin.py — 시험·부하용 DB 도우미가 **남의 데이터베이스를 지우지 않는다**(검토 DB-1a P1)."""
import sys
import uuid

from django.test import SimpleTestCase, tag

from tests.support.helpers import BASE_DIR

sys.path.insert(0, str(BASE_DIR / "tests" / "tools"))
import mysql_admin  # noqa: E402


def exists(name):
    conn = mysql_admin.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (name,))
            return cur.fetchone()[0] == 1
    finally:
        conn.close()


@tag("security")
class DatabaseOwnershipTests(SimpleTestCase):
    def test_created_database_is_random_and_dropped_only_when_owned(self):
        a, b = mysql_admin.create_database("ads_t"), mysql_admin.create_database("ads_t")
        self.addCleanup(lambda: [mysql_admin.drop_database(n) for n in (a, b) if exists(n)])
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), len("ads_t_") + 32)  # 이름이 겹칠 수 없을 만큼 길다
        self.assertTrue(exists(a) and exists(b))
        mysql_admin.drop_database(a)
        self.assertFalse(exists(a))
        self.assertTrue(exists(b))

    def test_a_database_this_run_did_not_create_is_never_dropped(self):
        """남이 만든 DB(같은 이름이 이미 있는 경우 포함)는 지우기를 거부하고 데이터가 그대로다."""
        other = f"ads_t_other_{uuid.uuid4().hex}"
        conn = mysql_admin.connect()
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{other}`")
            cur.execute(f"CREATE TABLE `{other}`.marker (id INT PRIMARY KEY)")
            cur.execute(f"INSERT INTO `{other}`.marker VALUES (7)")
        conn.commit()
        self.addCleanup(lambda: (conn.cursor().execute(f"DROP DATABASE IF EXISTS `{other}`"), conn.close()))
        with self.assertRaises(ValueError):
            mysql_admin.drop_database(other)
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM `{other}`.marker")
            self.assertEqual(cur.fetchone()[0], 7)

    def test_create_does_not_replace_an_existing_database(self):
        """무작위 이름이 우연히 겹쳐도 CREATE 가 실패할 뿐 기존 DB 를 지우지 않는다."""
        other = f"ads_t_fixed_{uuid.uuid4().hex}"
        conn = mysql_admin.connect()
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{other}`")
            cur.execute(f"CREATE TABLE `{other}`.marker (id INT PRIMARY KEY)")
        conn.commit()
        self.addCleanup(lambda: (conn.cursor().execute(f"DROP DATABASE IF EXISTS `{other}`"), conn.close()))
        fixed = uuid.UUID(other.rsplit("_", 1)[1])
        original = mysql_admin.uuid.uuid4
        mysql_admin.uuid.uuid4 = lambda: fixed
        try:
            with self.assertRaises(SystemExit):
                mysql_admin.create_database("ads_t_fixed")
        finally:
            mysql_admin.uuid.uuid4 = original
        self.assertTrue(exists(other))
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{other}`")
            self.assertEqual(cur.fetchall(), (("marker",),))
