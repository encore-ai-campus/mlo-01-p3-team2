import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase

from config.env import load_env, load_env_for_web
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

    def test_prod_event_store_is_optional_until_events_are_written(self):
        """DB-2: 이벤트를 아직 쓰지 않으므로 MONGO_HOSTS 가 없어도 기동한다(None). 있으면 읽고, 비밀번호는 설정 문자열에 섞지 않는다."""
        show = "from django.conf import settings; print(settings.EVENT_STORE)"
        r = run_python(show, "config.settings.prod", PROD_ENV)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "None"), r.stderr)
        r = run_python(show, "config.settings.prod", dict(PROD_ENV, MONGO_HOSTS="a:1,b:2", MONGO_USER="u", MONGO_PASSWORD="pw", MONGO_REPLICA_SET="rs0"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("'HOSTS': ['a:1', 'b:2']", r.stdout)
        self.assertIn("'REPLICA_SET': 'rs0'", r.stdout)

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



class WebEntrySettingsTests(SimpleTestCase):
    """6-3a(설계 §10 "웹 진입점의 설정 모듈"): 웹 진입점은 `.env` 의 설정 모듈을 따르지 않는다 — 실제 환경변수에 있으면 그 값, 없으면 prod.
    예시 `.env`(전에는 dev 줄이 있었다)를 복사한 운영 웹 서버가 공개된 개발 키·Secure 쿠키 없이 dev 로 조용히 뜨던 문제(리팩터링 세션 검토 O1)."""

    DEV_DOTENV = "DJANGO_SETTINGS_MODULE=config.settings.dev\nADS_TEST_WEB=from_file\n"

    def dotenv_dir(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / ".env").write_text(self.DEV_DOTENV)
        return directory.name

    def keep_env(self, *names):
        saved = {name: os.environ.get(name) for name in names}
        for name in names:
            os.environ.pop(name, None)
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v) for n, v in saved.items()])

    def test_the_dotenv_settings_module_is_ignored_but_other_values_are_loaded(self):
        self.keep_env("DJANGO_SETTINGS_MODULE", "ADS_TEST_WEB")
        load_env_for_web(Path(self.dotenv_dir()) / ".env")
        self.assertEqual((os.environ["DJANGO_SETTINGS_MODULE"], os.environ["ADS_TEST_WEB"]), ("config.settings.prod", "from_file"))

    def test_a_real_environment_variable_still_chooses_the_module(self):
        self.keep_env("DJANGO_SETTINGS_MODULE", "ADS_TEST_WEB")
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"  # 부하·장애 시험처럼 실제 환경변수로 지정
        load_env_for_web(Path(self.dotenv_dir()) / ".env")
        self.assertEqual(os.environ["DJANGO_SETTINGS_MODULE"], "config.settings.dev")

    def test_wsgi_and_asgi_start_with_prod_even_if_the_dotenv_says_dev(self):
        """실제 진입점 모듈을 새 프로세스에서 불러온다. `.env` 위치만 임시 폴더로 바꾼다(개발자의 `.env` 와 무관하게)."""
        directory = self.dotenv_dir()
        for module in ("config.wsgi", "config.asgi"):
            code = f"import config.env as e, pathlib; e.BASE_DIR = pathlib.Path({directory!r}); import {module}; from django.conf import settings; print(settings.SETTINGS_MODULE)"
            r = run_python(code, None, PROD_ENV)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "config.settings.prod"), (module, r.stderr[-400:]))
            r = run_python(code, "config.settings.dev", DB_ENV)  # 실제 환경변수로 지정하면 그 값
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "config.settings.dev"), (module, r.stderr[-400:]))



class SignupLimitSettingTests(SimpleTestCase):
    """6-3d(설계 §10 "가입 시도 제한"): 가입 시도 상한은 dev·prod 에서 환경값으로 바꿀 수 있다. 기본은 확정값 5, 1 미만·정수 아님은 기동하지 않는다.
    단체 가입(같은 NAT 의 교실)에서 6번째부터 1시간 막히던 문제의 임시방편(리팩터링 세션 검토 O3)."""

    SHOW = "from django.conf import settings; print(settings.SIGNUP_MAX_PER_IP_PER_HOUR)"
    ENVS = (("config.settings.dev", DB_ENV), ("config.settings.prod", PROD_ENV))

    def test_the_default_is_the_confirmed_value_and_the_environment_can_change_it(self):
        for module, env in self.ENVS:
            r = run_python(self.SHOW, module, env)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "5"), (module, r.stderr[-300:]))
            for value in ("40", "1"):  # 1 은 받는다(경계)
                r = run_python(self.SHOW, module, dict(env, SIGNUP_MAX_PER_IP_PER_HOUR=value))
                self.assertEqual((r.returncode, r.stdout.strip()), (0, value), (module, r.stderr[-300:]))

    def test_values_below_one_or_not_integers_refuse_to_start(self):
        for module, env in self.ENVS:
            for bad in ("0", "-3", "many"):
                r = run_python(self.SHOW, module, dict(env, SIGNUP_MAX_PER_IP_PER_HOUR=bad))
                self.assertNotEqual(r.returncode, 0, (module, bad))
                self.assertIn("SIGNUP_MAX_PER_IP_PER_HOUR", r.stderr, (module, bad))
