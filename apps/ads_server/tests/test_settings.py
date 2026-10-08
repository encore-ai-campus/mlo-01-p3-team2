import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase

from config.env import load_env
from tests.helpers import DB_ENV, PROD_ENV, run_python

SHOW_SECRET = "from django.conf import settings; print(settings.SECRET_KEY)"


class ProdSettingsTests(SimpleTestCase):
    def test_prod_requires_secret_key(self):
        env = {k: v for k, v in PROD_ENV.items() if k != "SECRET_KEY"}
        r = run_python(SHOW_SECRET, "config.settings.prod", env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SECRET_KEY", r.stderr)

    def test_prod_rejects_dev_default_key(self):
        from config.settings.base import INSECURE_DEV_KEY

        r = run_python(SHOW_SECRET, "config.settings.prod", dict(PROD_ENV, SECRET_KEY=INSECURE_DEV_KEY))
        self.assertNotEqual(r.returncode, 0)

    def test_prod_rejects_short_key(self):
        r = run_python(SHOW_SECRET, "config.settings.prod", dict(PROD_ENV, SECRET_KEY="short"))
        self.assertNotEqual(r.returncode, 0)

    def test_prod_requires_allowed_hosts_database_and_admin_path(self):
        for missing in ("ALLOWED_HOSTS", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "ADMIN_URL_PATH", "MEDIA_ROOT", "ASSET_PUBLIC_BASE_URL"):
            env = {k: v for k, v in PROD_ENV.items() if k != missing}
            r = run_python(SHOW_SECRET, "config.settings.prod", env)
            self.assertNotEqual(r.returncode, 0, missing)

    def test_prod_starts_with_valid_env(self):
        r = run_python(SHOW_SECRET, "config.settings.prod", PROD_ENV)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_prod_debug_cannot_be_enabled_by_env(self):
        r = run_python("from django.conf import settings; print(settings.DEBUG)", "config.settings.prod",
                       dict(PROD_ENV, DJANGO_DEBUG="1"))
        self.assertEqual(r.stdout.strip(), "False", r.stderr)


class DevAndTestSettingsTests(SimpleTestCase):
    def test_debug_default_false(self):
        r = run_python("from django.conf import settings; print(settings.DEBUG)", "config.settings.dev", DB_ENV)
        self.assertEqual(r.stdout.strip(), "False", r.stderr)

    def test_debug_can_be_enabled_in_dev_only(self):
        r = run_python("from django.conf import settings; print(settings.DEBUG)", "config.settings.dev",
                       dict(DB_ENV, DJANGO_DEBUG="1"))
        self.assertEqual(r.stdout.strip(), "True", r.stderr)

    def test_test_settings_ignore_everything_but_the_database_target(self):
        """동작을 바꾸는 값(SECRET_KEY·관리자 경로)은 무시하고, 접속 대상(DB_*)만 환경에서 읽는다."""
        code = ("from django.conf import settings as s; d = s.DATABASES['default']; "
                "print(s.SECRET_KEY.startswith('test-only'), s.ADMIN_URL_PATH, d['NAME'], d['HOST'])")
        r = run_python(code, "config.settings.test", dict(DB_ENV, SECRET_KEY="from-env", ADMIN_URL_PATH="from-env/"))
        self.assertEqual(r.stdout.strip(), "True test-admin/ ads_x db.example.com", r.stderr)

    def test_dev_requires_database_credentials(self):
        for missing in ("DB_USER", "DB_PASSWORD"):
            r = run_python("from django.conf import settings; settings.DATABASES", "config.settings.dev",
                           {k: v for k, v in DB_ENV.items() if k != missing})
            self.assertNotEqual(r.returncode, 0, missing)
            self.assertIn(missing, r.stderr)


class TimeAndDatabaseTests(SimpleTestCase):
    def test_timezone_is_utc(self):
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, "UTC")


class MysqlSessionTests(TestCase):
    """연결이 계획 S5·S7 의 세션 설정으로 열린다(잘림은 오류, 격리 수준, 문자셋·정렬)."""

    def test_session_settings(self):
        with connection.cursor() as cur:
            cur.execute("SELECT @@sql_mode, @@transaction_isolation, @@character_set_connection, @@collation_database, @@time_zone")
            sql_mode, isolation, charset, collation, tz = cur.fetchone()
        self.assertIn("STRICT_ALL_TABLES", sql_mode)
        self.assertEqual(isolation, "READ-COMMITTED")
        self.assertEqual(charset, "utf8mb4")
        self.assertEqual(collation, "utf8mb4_0900_as_cs")  # 대소문자·악센트를 구분한다(기본 _ai_ci 는 구분하지 않아 유일 제약이 달라진다)
        self.assertEqual(connection.timezone_name, "UTC")

    def test_commit_is_durable_on_this_server(self):
        """수신 2xx 의 약속은 커밋이 디스크에 내려간 뒤다(T25). 서버가 커밋마다 로그를 내리지 않게 설정돼 있으면 알린다."""
        with connection.cursor() as cur:
            cur.execute("SELECT @@innodb_flush_log_at_trx_commit, @@sync_binlog, @@log_bin")
            flush, sync_binlog, log_bin = cur.fetchone()
        self.assertEqual(flush, 1)
        if log_bin:
            self.assertEqual(sync_binlog, 1)


class DotenvTests(SimpleTestCase):
    def _env_cleanup(self, name):
        old = os.environ.pop(name, None)
        self.addCleanup(lambda: os.environ.pop(name, None) if old is None else os.environ.__setitem__(name, old))

    def test_dotenv_loaded_when_present(self):
        self._env_cleanup("ADS_TEST_ONE")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("ADS_TEST_ONE=from_file\n")
            load_env(p)
        self.assertEqual(os.environ["ADS_TEST_ONE"], "from_file")

    def test_real_env_overrides_dotenv(self):
        self._env_cleanup("ADS_TEST_TWO")
        os.environ["ADS_TEST_TWO"] = "from_real_env"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("ADS_TEST_TWO=from_file\n")
            load_env(p)
        self.assertEqual(os.environ["ADS_TEST_TWO"], "from_real_env")

    def test_missing_dotenv_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            load_env(Path(d) / "does-not-exist.env")  # 예외가 없어야 한다
