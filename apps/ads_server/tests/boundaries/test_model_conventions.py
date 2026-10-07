from django.apps import apps
from django.test import SimpleTestCase, tag

from .test_layers import LAYERS


def project_app_configs():
    return [cfg for cfg in apps.get_app_configs() if cfg.name in LAYERS]


@tag("security")
class ModelConventionTests(SimpleTestCase):
    def test_app_labels_fixed(self):
        configs = project_app_configs()
        self.assertTrue(configs)
        for cfg in configs:
            self.assertIn("label", type(cfg).__dict__, f"{cfg.name}: AppConfig 에 label 이 명시돼 있지 않다")
            self.assertEqual(cfg.label, cfg.name)  # 폴더·패키지 이름이 바뀌어도 label 은 그대로 둔다

    def test_all_models_have_explicit_db_table(self):
        checked = 0
        for cfg in project_app_configs():
            for model in cfg.get_models():
                checked += 1
                self.assertIn("db_table", model._meta.original_attrs, f"{model.__name__}: Meta.db_table 이 명시돼 있지 않다")
                self.assertTrue(model._meta.db_table.startswith(cfg.label + "_"), f"{model.__name__}: {model._meta.db_table}")
        self.assertGreater(checked, 0)
