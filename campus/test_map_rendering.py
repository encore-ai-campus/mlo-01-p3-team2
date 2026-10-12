import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.template import Context, Engine
from django.test import RequestFactory, SimpleTestCase, override_settings

from config import settings as project_settings
from .views import map_view


class MapRenderingTests(SimpleTestCase):
    def map_request(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(
            pk=1,
            is_authenticated=True,
            is_staff=True,
            campus_profile=SimpleNamespace(nickname="encore"),
        )
        return request

    def test_development_template_edit_is_visible_in_the_same_engine(self):
        if not project_settings.DEBUG:
            self.skipTest("Production templates intentionally use a cache.")
        with TemporaryDirectory() as directory:
            template = Path(directory) / "index.html"
            template.write_text("old map markup", encoding="utf-8")
            engine = Engine(
                dirs=[directory],
                loaders=project_settings.TEMPLATES[0]["OPTIONS"]["loaders"],
            )
            self.assertEqual(
                engine.get_template("index.html").render(Context()), "old map markup"
            )
            template.write_text("new map markup", encoding="utf-8")
            self.assertEqual(
                engine.get_template("index.html").render(Context()), "new map markup"
            )

    def test_authenticated_map_updates_script_revision_after_a_live_edit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dist").mkdir()
            script = root / "dist" / "campus.js"
            script.write_text("const version = 1;", encoding="utf-8")
            with override_settings(BASE_DIR=root):
                before = map_view(self.map_request()).content.decode()
                script.write_text("const version = 2;", encoding="utf-8")
                after = map_view(self.map_request()).content.decode()
            pattern = r'src="campus\.js\?v=([0-9a-f]+)"'
            before_revision = re.search(pattern, before)
            after_revision = re.search(pattern, after)
            self.assertIsNotNone(before_revision)
            self.assertIsNotNone(after_revision)
            self.assertNotEqual(before_revision.group(1), after_revision.group(1))
            self.assertIn('id="boothEmbeddedSection"', after)
            self.assertIn('"canZoom": true', after)
