"""Component-test client: backend presentation data rendered by the real frontend.

No server uses this adapter. It keeps existing account/HTML regression assertions
while transport is tested independently in frontend.pages and the browser suite.
"""
import importlib.util
from pathlib import Path

from django.conf import settings
from django.template import Context
from django.test import Client, TestCase

UI_ROOT = Path(__file__).resolve().parents[2] / "frontend"
spec = importlib.util.spec_from_file_location("campus_ui_test_renderer", UI_ROOT / "pages/rendering.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class PresentationClient(Client):
    def request(self, **request):
        response = super().request(**request)
        if response.get("Content-Type", "").startswith("application/json"):
            data = response.json()
            if isinstance(data, dict) and "presentation" in data:
                presentation = data["presentation"]
                response.content, context = renderer.render_document(presentation, UI_ROOT, settings.DEBUG)
                response["Content-Type"] = "text/html; charset=utf-8"
                response.context = Context(context)
                response.templates = [renderer.template_engine(UI_ROOT, settings.DEBUG).get_template(presentation["template"])]
        return response


class PresentationTestCase(TestCase):
    client_class = PresentationClient
