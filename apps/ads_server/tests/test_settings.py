import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from config.env import load_env
from tests.helpers import PROD_ENV, run_python

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

    def test_prod_requires_allowed_hosts_database_path_and_admin_path(self):
        for missing in ("ALLOWED_HOSTS", "DATABASE_PATH", "ADMIN_URL_PATH"):
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
        r = run_python("from django.conf import settings; print(settings.DEBUG)", "config.settings.dev")
        self.assertEqual(r.stdout.strip(), "False", r.stderr)

    def test_debug_can_be_enabled_in_dev_only(self):
        r = run_python("from django.conf import settings; print(settings.DEBUG)", "config.settings.dev",
                       {"DJANGO_DEBUG": "1"})
        self.assertEqual(r.stdout.strip(), "True", r.stderr)

    def test_test_settings_ignore_environment(self):
        code = "from django.conf import settings as s; print(s.SECRET_KEY.startswith('test-only'), s.DATABASES['default']['NAME'])"
        r = run_python(code, "config.settings.test",
                       {"SECRET_KEY": "from-env", "DATABASE_PATH": "/tmp/should-not-be-used.sqlite3"})
        self.assertEqual(r.stdout.strip(), "True :memory:", r.stderr)


class TimeAndDatabaseTests(SimpleTestCase):
    def test_timezone_is_utc(self):
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, "UTC")

    def test_sqlite_pragmas(self):
        """파일 DB 에서 WAL·synchronous=FULL·busy_timeout·즉시 시작 트랜잭션이 적용된다."""
        with tempfile.TemporaryDirectory() as d:
            code = (
                "import django; django.setup()\n"
                "from django.db import connection as c\n"
                "cur = c.cursor()\n"
                "for p in ('journal_mode', 'synchronous', 'busy_timeout'):\n"
                "    cur.execute('PRAGMA ' + p); print(p, cur.fetchone()[0])\n"
                "print('transaction_mode', c.transaction_mode)\n"
            )
            r = run_python(code, "config.settings.dev", {"DATABASE_PATH": str(Path(d) / "t.sqlite3")})
        out = dict(line.split(" ", 1) for line in r.stdout.strip().splitlines())
        self.assertEqual(out.get("journal_mode"), "wal", r.stderr)
        self.assertEqual(out.get("synchronous"), "2")  # 2 = FULL
        self.assertEqual(out.get("busy_timeout"), str(settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000))
        self.assertEqual(out.get("transaction_mode"), "IMMEDIATE")


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
