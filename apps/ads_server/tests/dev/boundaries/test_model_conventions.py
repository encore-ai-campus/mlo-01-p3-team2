from django.apps import apps
from django.test import SimpleTestCase, tag

from .test_layers import LAYERS
from tests.support.cases import Cases


def project_app_configs():
    return [cfg for cfg in apps.get_app_configs() if cfg.name in LAYERS]


@tag("security")
class ModelConventionTests(Cases, SimpleTestCase):
    def case_app_labels_fixed(self):
        configs = project_app_configs()
        self.assertTrue(configs)
        for cfg in configs:
            self.assertIn("label", type(cfg).__dict__, f"{cfg.name}: AppConfig 에 label 이 명시돼 있지 않다")
            self.assertEqual(cfg.label, cfg.name)  # 폴더·패키지 이름이 바뀌어도 label 은 그대로 둔다

    def case_all_models_have_explicit_db_table(self):
        checked = 0
        for cfg in project_app_configs():
            for model in cfg.get_models():
                checked += 1
                self.assertIn("db_table", model._meta.original_attrs, f"{model.__name__}: Meta.db_table 이 명시돼 있지 않다")
                self.assertTrue(model._meta.db_table.startswith(cfg.label + "_"), f"{model.__name__}: {model._meta.db_table}")
        self.assertGreater(checked, 0)

    def case_every_primary_key_is_a_uuid7_and_nothing_auto_increments(self):
        """PK 규칙(설계 §4·DRD R-2): 모든 PK 는 UUIDv7, 자동 증가 열 없음. 순서가 필요한 곳은 시각 열이나 원장 `seq` 다.
        예외는 outbox 의 `event_id` 하나(원천 행에서 결정적으로 만든 UUIDv5, 설계 §10 "PK 규칙") — 기본값이 있으면 빠뜨린 코드에 무작위 ID 가 들어간다."""
        import uuid

        from django.db import models

        checked = 0
        for cfg in project_app_configs():
            for model in cfg.get_models():
                checked += 1
                pk = model._meta.pk
                where = f"{model.__name__}.{pk.name}"
                self.assertIsInstance(pk, models.UUIDField, f"{where}: PK 는 UUID 여야 한다")
                if model._meta.label == "events.EventOutbox":
                    self.assertFalse(pk.has_default(), f"{where}: 원천 행에서 만든 값만 받는다 — 기본값을 두지 않는다")
                else:
                    self.assertIs(pk.default, uuid.uuid7, f"{where}: 기본값은 uuid.uuid7 이어야 한다(시각이 앞에 오는 v7)")
                self.assertFalse(pk.auto_created, f"{where}: 암묵적으로 만들어진 `id` PK 다 — 명시적으로 정의해야 한다")
                self.assertIsNone(model._meta.auto_field, f"{model.__name__}: 자동 증가 열이 있다")
                self.assertFalse(
                    [f.name for f in model._meta.local_fields if f.unique and not f.primary_key and isinstance(f, models.UUIDField)],
                    f"{model.__name__}: UUID 를 PK 와 별개의 유일 열로 두지 않는다(식별자는 PK 하나)",
                )
        self.assertGreater(checked, 0)

    def test_model_convention(self):
        self.run_cases()
