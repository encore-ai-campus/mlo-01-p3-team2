"""추가 전용 모델 **전부**에서 같은 PK 새 인스턴스·upsert(키워드·위치 인자 모두)로 기존 행을 덮어쓸 수 없다(설계 §4.4).

Django 의 `bulk_create` 는 모델의 `save()` 를 호출하지 않으므로 `save()` 가드만으로는 이 경로를 막지 못한다.
위치 인자로 넘긴 `update_conflicts` 도 막혀야 한다(과거에는 키워드 전용으로만 검사했다).
"""
from django.db import IntegrityError, transaction
from django.test import TestCase, tag

from billing import api as billing
from billing.models import LedgerEntry
from campaigns.models import Bid
from foundation.api import record_audit
from foundation.models import AppendOnlyError, AuditLog
from masters.models import BidPolicy
from records.models import Decision
from tests.factories import World

OVERWRITE = {"AuditLog": "action", "BidPolicy": "reason", "Bid": "amount", "LedgerEntry": "note", "Decision": "selection_policy"}


def clone_with_same_pk(row, field, value):
    clone = type(row).objects.get(pk=row.pk)
    clone._state.adding = True  # 같은 PK 의 "새" 인스턴스
    setattr(clone, field, value)
    return clone


@tag("security")
class AllAppendOnlyModelsTests(TestCase):
    def rows(self):
        w = World()
        decision = __import__("records.api", fromlist=["decide"]).decide(w.slot.media_id, w.slot.slot_id)
        return {
            "AuditLog": (AuditLog.objects.first(), "overwritten"),
            "BidPolicy": (BidPolicy.objects.first(), "overwritten"),
            "Bid": (Bid.objects.first(), 999),
            "LedgerEntry": (LedgerEntry.objects.first(), "overwritten"),
            "Decision": (Decision.objects.get(decision_id=decision.decision_id), "overwritten"),
        }

    def test_positional_and_keyword_upserts_and_new_instance_saves_cannot_overwrite(self):
        for name, (row, value) in self.rows().items():
            model, field = type(row), OVERWRITE[name]
            original = getattr(row, field)
            conflict_fields = [model._meta.get_field(field)]
            calls = {
                "keyword upsert": lambda c: model.objects.bulk_create([c], update_conflicts=True, update_fields=[field], unique_fields=["id"]),
                "positional upsert": lambda c: model.objects.bulk_create([c], None, False, True, conflict_fields, ["id"]),
                "positional upsert (batch_size)": lambda c: model.objects.bulk_create([c], 10, False, True, conflict_fields, ["id"]),
            }
            for label, call in calls.items():
                with self.assertRaises(AppendOnlyError, msg=(name, label)):
                    call(clone_with_same_pk(row, field, value))
            with self.assertRaises((IntegrityError, AppendOnlyError), msg=(name, "save")), transaction.atomic():
                clone_with_same_pk(row, field, value).save()
            with self.assertRaises(AppendOnlyError, msg=(name, "force_update")):
                clone_with_same_pk(row, field, value).save(force_update=True)
            self.assertEqual(getattr(model.objects.get(pk=row.pk), field), original, name)  # 원본 행은 그대로

    def test_ignore_conflicts_skips_but_never_overwrites(self):
        for name, (row, value) in self.rows().items():
            model, field = type(row), OVERWRITE[name]
            before = model.objects.count()
            model.objects.bulk_create([clone_with_same_pk(row, field, value)], ignore_conflicts=True)
            model.objects.bulk_create([clone_with_same_pk(row, field, value)], None, True)  # 위치 인자
            self.assertEqual((model.objects.count(), getattr(model.objects.get(pk=row.pk), field) == value), (before, False), name)

    def test_models_really_are_all_append_only_models(self):
        from foundation.models import AppendOnlyModel

        for model in (AuditLog, BidPolicy, Bid, LedgerEntry, Decision):
            self.assertTrue(issubclass(model, AppendOnlyModel), model.__name__)
        self.assertIsNotNone(record_audit)
        self.assertIsNotNone(billing)
