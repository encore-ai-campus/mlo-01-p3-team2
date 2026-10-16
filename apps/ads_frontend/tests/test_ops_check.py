"""프론트 배포 후 점검 = 운영 환경 시험 `ops_check`(계획서 §8.4.20, 6-19b, 6-19d 에서 다섯으로): 건강하면 모두 OK, 점검마다 깨진 상태에서 그 줄만 FAIL 이고 종료 코드 1."""
import io
import json
import shutil
import tempfile
from contextlib import contextmanager
from importlib import metadata
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from tests.test_transport import BackendCase, FakeBackend
from ui.management.commands.ops_check import CHECKS

JSON = [("Content-Type", "application/json")]
HEALTH = (200, JSON, json.dumps({"status": "ok"}).encode())
LOGIN = (200, JSON, json.dumps({"presentation": {"template": "console/login.html", "context": {
    "user": {"is_authenticated": False}, "messages": [], "csrf_token": "token-from-the-backend", "next": ""}}}).encode())


@contextmanager
def backend_routes(**routes):
    saved = FakeBackend.routes
    FakeBackend.routes = routes
    try:
        yield
    finally:
        FakeBackend.routes = saved


class OpsCheckTests(BackendCase):
    def setUp(self):
        super().setUp()
        FakeBackend.routes = {"/api/media/v1/health": HEALTH, "/accounts/login/": LOGIN}
        roots = [tempfile.mkdtemp(prefix="ads-frontend-ops-static-") for _ in range(2)]
        for root in roots:
            self.addCleanup(shutil.rmtree, root, True)
        self.collected, self.empty = roots
        static = override_settings(STATIC_ROOT=self.collected)
        static.enable()
        self.addCleanup(static.disable)
        call_command("collectstatic", interactive=False, verbosity=0)

    def run_check(self):
        out = io.StringIO()
        try:
            call_command("ops_check", stdout=out)
        except CommandError:
            return 1, out.getvalue().splitlines()
        return 0, out.getvalue().splitlines()

    def test_a_healthy_frontend_passes_every_check(self):
        code, lines = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertEqual([line.split(":")[0] for line in lines], [f"OK   {name}" for name, _ in CHECKS])
        self.assertEqual([r["path"] for r in FakeBackend.seen], ["/api/media/v1/health", "/accounts/login/"])  # 화면은 실제로 백엔드에 물었다

    def test_each_broken_part_fails_only_its_own_line_and_the_command(self):
        down = (200, JSON, json.dumps({"status": "down"}).encode())

        def django_at(version):
            return mock.patch("ui.management.commands.ops_check._installed", side_effect=lambda name: version if name == "Django" else metadata.version(name))
        cases = [  # (점검, 어떻게 깨졌나, 깨뜨리기) — 나머지 점검은 그대로 통과해야 한다
            ("설정", "DEBUG", override_settings(DEBUG=True)),
            ("의존성", "같은 6.1 이지만 요구보다 낮은 Django(~=6.1.2 에 6.1.1)", django_at("6.1.1")),
            ("의존성", "호환 범위를 넘은 Django(~=6.1.x 에 7.0.0)", django_at("7.0.0")),
            ("정적 파일", "collectstatic 안 함", override_settings(STATIC_ROOT=self.empty)),
            ("백엔드", "health 가 JSON 이 아님", backend_routes(**{"/accounts/login/": LOGIN})),
            ("백엔드", "health 가 200 이지만 down", backend_routes(**{"/api/media/v1/health": down, "/accounts/login/": LOGIN})),
            ("화면 한 장", "화면 데이터가 아닌 응답", backend_routes(**{"/api/media/v1/health": HEALTH})),
        ]
        for name, how, broken in cases:
            with self.subTest(f"{name}: {how}"), broken:
                code, lines = self.run_check()
                self.assertEqual(code, 1, lines)
                failed = [line for line in lines if line.startswith("FAIL")]
                self.assertEqual(len(failed), 1, lines)
                self.assertTrue(failed[0].startswith(f"FAIL {name}: ") and len(failed[0]) > len(f"FAIL {name}: ") + 5, failed)
