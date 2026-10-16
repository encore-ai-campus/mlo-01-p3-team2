"""백엔드와 프론트(apps/ads_frontend)가 어긋나지 않는지(설계 §6.6 "6-15 분리"). 프론트는 백엔드 코드를 가져오지 않으므로 같은 것을 데이터로 따로 갖는다 —
경로·URL 이름(`ui/routes.py`), 화면 이름표(`ui/labels.py`), KST 표시(`ui/templatetags/kst.py`, 백엔드 Django admin 도 쓴다). 화면 데이터는 그 밖의 값이
새지 않게 막는 시험은 운영용 `tests/ops/test_presentation_data.py` 에 있다(6-18e)."""
import ast
import json
from datetime import datetime, timezone

from django.conf import settings
from django.contrib import admin
from django.test import SimpleTestCase

from billing.api import EntryType
from campaigns.api import CampaignStatus, ReviewStatus
from console import urls as console_urls
from console.operator import urls as operator_urls
from foundation.templatetags.kst import kst as backend_kst
from masters.api import Audience
from tests.support.helpers import BASE_DIR, run_python
import tests.support.presentation  # noqa: F401 — 프론트 경로를 sys.path 에 둔다(아래 ui import 보다 먼저)
from ui import labels, routes
from ui.templatetags.kst import kst as frontend_kst
from tests.support.cases import Cases


def table(urlpatterns):
    return sorted((p.pattern._route, p.name) for p in urlpatterns)


class FrontendSyncTests(Cases, SimpleTestCase):
    def case_frontend_routes_match_the_backend(self):
        """프론트의 경로 표 = 백엔드의 콘솔·운영 경로(양쪽 모두 빠짐없이), 관리 사이트는 관리 템플릿·운영 화면이 거는 이름의 경로가 같다."""
        self.assertEqual(sorted(routes.CONSOLE), table(console_urls.urlpatterns))
        self.assertEqual(sorted(routes.OPERATOR), table(operator_urls.urlpatterns))
        site = {}
        for p in admin.site.get_urls():
            if getattr(p, "name", None):
                site[p.name] = str(p.pattern)
            for q in getattr(p, "url_patterns", ()):  # 모델별 하위 경로(이름 없는 URLResolver) 안의 이름 — 비밀번호 초기화 등
                if getattr(q, "name", None):
                    site[q.name] = str(p.pattern) + str(q.pattern)
        for route, name in routes.ADMIN:
            self.assertEqual(site[name], route, name)

    def case_the_frontend_does_not_import_backend_code(self):
        """프론트는 따로 배포한다 — 백엔드 앱(모델·서비스)을 가져오지 않고 같은 것은 데이터로 갖는다."""
        backend = {d.name for d in BASE_DIR.iterdir() if (d / "__init__.py").exists()} - {"config", "tests"}  # config 는 프론트에도 같은 이름이 있다
        for path in (BASE_DIR.parent / "ads_frontend").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                for name in names:
                    self.assertNotIn(name.split(".")[0], backend, f"{path.relative_to(BASE_DIR.parent)}: {name}")

    def case_the_frontend_sends_the_same_security_headers_as_the_backend(self):
        """6-16i(R22): 프론트가 그린 HTML 의 보안 헤더·CSP 는 프론트가 붙인다(위협 모델 T46 ⑤ "같은 값"). 프론트는 따로 배포되는 앱이라 새 프로세스에서
        그 설정을 실제로 읽어 백엔드 설정과 대조한다."""
        names = ("SECURE_CSP", "SECURE_CONTENT_TYPE_NOSNIFF", "X_FRAME_OPTIONS", "SECURE_REFERRER_POLICY", "SECURE_CROSS_ORIGIN_OPENER_POLICY")
        code = f"import json, django; django.setup(); from django.conf import settings as s; print(json.dumps({{n: getattr(s, n) for n in {names!r}}}))"
        done = run_python(code, "config.settings_test", cwd=BASE_DIR.parent / "ads_frontend")
        self.assertEqual(done.returncode, 0, done.stderr)
        frontend = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(frontend, json.loads(json.dumps({n: getattr(settings, n) for n in names})))

    def case_frontend_labels_match_the_backend_choices(self):
        for data, choices in ((labels.AUDIENCES, Audience), (labels.CAMPAIGN_STATUSES, CampaignStatus), (labels.ENTRY_TYPES, EntryType),
                              (labels.REVIEW_STATUSES, ReviewStatus)):
            self.assertEqual(data, {k: str(v) for k, v in choices.choices}, choices.__name__)

    def case_the_frontend_and_backend_show_the_same_kst_time(self):
        for value in (datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc), datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)):
            self.assertEqual(frontend_kst(value), backend_kst(value))
            self.assertEqual(frontend_kst(value, "%Y-%m-%d"), backend_kst(value, "%Y-%m-%d"))

    def test_frontend_sync(self):
        self.run_cases()
