"""배포 후 점검 명령 `ops_check`(설계 §10 "시험 구성" ⑤, 6-18d): 건강한 백엔드에서는 모두 OK, 점검마다 깨진 상태를 만들면 그 줄만 FAIL 이고 종료 코드 1."""
import io
from contextlib import contextmanager, nullcontext
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings, tag

from billing import api as billing
from console.management.commands.ops_check import CHECKS
from events import store
from tests.support.factories import make_advertiser
from tests.support.mongo_support import MongoDatabaseMixin, unreachable_store

PROD_LIKE = dict(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SILENCED_SYSTEM_CHECKS=["security.W004", "security.W008"])  # prod.py 의 배포 점검 관련 값


@contextmanager
def unapplied_migration():
    """마지막으로 적용한 billing 마이그레이션 기록을 잠시 지운다(끝나면 되돌린다)."""
    with connection.cursor() as cur:
        cur.execute("SELECT id, app, name, applied FROM django_migrations WHERE app = 'billing' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.execute("DELETE FROM django_migrations WHERE id = %s", [row[0]])
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("INSERT INTO django_migrations (id, app, name, applied) VALUES (%s, %s, %s, %s)", row)


@contextmanager
def tampered_ledger():
    billing.grant_signup(make_advertiser())
    with connection.cursor() as cur:  # ORM 우회 — 운영자 실수·DB 직접 수정 모사(test_billing_ledger 와 같은 방법)
        cur.execute("UPDATE billing_wallet SET balance = balance + 5")
    yield


@tag("security")
class OpsCheckTests(MongoDatabaseMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        store.ensure()  # 이 시험의 무작위 데이터베이스에 컬렉션·색인

    def run_check(self):
        out = io.StringIO()
        try:
            call_command("ops_check", stdout=out)
        except CommandError:
            return 1, out.getvalue().splitlines()
        return 0, out.getvalue().splitlines()

    def test_a_healthy_backend_passes_every_check(self):
        with override_settings(**PROD_LIKE):
            code, lines = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertEqual([line.split(":")[0] for line in lines], [f"OK   {name}" for name, _ in CHECKS])

    def test_each_broken_part_fails_only_its_own_line_and_the_command(self):
        cases = {  # 나머지 점검은 그대로 통과해야 한다 — 한 점검의 실패가 다른 점검을 가리거나 끌고 가지 않는다
            "배포 설정": (nullcontext(), False),  # 시험 설정은 배포 설정이 아니다(HSTS·HTTPS 이동 경고)
            "DB·마이그레이션": (unapplied_migration(), True),
            "MongoDB 이벤트 저장소": (unreachable_store(), True),
            "반응 처리": (mock.patch("records.api.inbox_status", return_value={"received": 1, "held": 0, "stuck": 1, "oldest_age_seconds": 3.0}), True),
            "outbox": (mock.patch("events.api.outbox_status", return_value={"pending": 2, "oldest_age_seconds": 601.0}), True),
            "파일 저장소": (override_settings(MEDIA_ROOT="/nonexistent-ads-media"), True),
            "원장 대조": (tampered_ledger(), True),  # 마지막 — 고친 원장은 시험이 끝날 때 비워진다
        }
        for name, (broken, prod_like) in cases.items():
            with self.subTest(name), override_settings(**(PROD_LIKE if prod_like else {})), broken:
                code, lines = self.run_check()
                self.assertEqual(code, 1, lines)
                failed = [line for line in lines if line.startswith("FAIL")]
                self.assertEqual(len(failed), 1, lines)
                self.assertTrue(failed[0].startswith(f"FAIL {name}: ") and len(failed[0]) > len(f"FAIL {name}: ") + 5, failed)
