"""정적 파일은 Django 가 서빙한다(Step 6-5e, 설계 §10 "정적 파일 서빙"): 앞단 nginx 는 통로만 맡고, `collectstatic` 으로 모은 파일을 WhiteNoise 가 내준다.
6-15 부터 콘솔·운영 화면의 CSS·JS 는 프론트(apps/ads_frontend)에 있고 프론트가 서빙한다(프론트 시험) — 백엔드에는 Django admin 의 것만 남는다.

전에는 웹서버(인프라)가 `STATIC_ROOT` 를 서빙하기로 했고, `DEBUG=False` 인 Django 는 정적 파일을 내주지 않아 nginx 가 통로만 맡으면 관리자·콘솔 화면의 CSS·JS 가 404 였다.
"""
import shutil
import tempfile

from django.core.management import call_command
from django.test import Client, TestCase, override_settings, tag
from tests.support.cases import Cases


@tag("security")
class StaticFilesServedByDjangoTests(Cases, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = tempfile.mkdtemp(prefix="ads-static-")
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        with override_settings(STATIC_ROOT=cls.root):
            call_command("collectstatic", "--noinput", verbosity=0)

    def get(self, path):
        with override_settings(STATIC_ROOT=self.root):  # WhiteNoise 는 처음 요청 때(미들웨어를 만들 때) 이 폴더를 읽는다
            return Client().get(path)

    def case_collected_admin_files_are_served_without_login(self):
        for path, kind in (("/static/admin/css/base.css", "text/css"), ("/static/admin/js/theme.js", "text/javascript")):
            r = self.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertTrue(r["Content-Type"].startswith(kind), (path, r["Content-Type"]))
            self.assertEqual(r["X-Content-Type-Options"], "nosniff", path)  # 보안 헤더 미들웨어 안쪽에서 나간다

    def case_a_file_that_was_not_collected_is_404(self):
        self.assertEqual(self.get("/static/console/missing.css").status_code, 404)

    def test_static_files_served_by_django(self):
        self.run_cases()
