"""추가 전용 모델 **전부**에서 같은 PK 새 인스턴스·upsert(키워드·위치 인자 모두)로 기존 행을 덮어쓸 수 없다(설계 §4.4).

Django 의 `bulk_create` 는 모델의 `save()` 를 호출하지 않으므로 `save()` 가드만으로는 이 경로를 막지 못한다.
위치 인자로 넘긴 `update_conflicts` 도 막혀야 한다(과거에는 키워드 전용으로만 검사했다).
"""
from django.db import IntegrityError, transaction
from django.test import TestCase, tag

from billing.models import LedgerEntry
from campaigns.models import AdGroupCreative, Bid, CreativeImage
from foundation.models import AppendOnlyError, AuditLog
from masters import api as masters
from masters.models import BidPolicy, MediaDeactivation
from records.models import Decision
from tests.support.factories import DAY, NOW, SUBJECT, World

OVERWRITE = {"AuditLog": "action", "BidPolicy": "reason", "Bid": "amount", "LedgerEntry": "note", "Decision": "selection_policy", "AdGroupCreative": "linked_at",
             "CreativeImage": "image_bytes", "MediaDeactivation": "deactivated_at"}


def clone_with_same_pk(row, field, value):
    clone = type(row).objects.get(pk=row.pk)
    clone._state.adding = True  # 같은 PK 의 "새" 인스턴스
    setattr(clone, field, value)
    return clone


@tag("security")
class AllAppendOnlyModelsTests(TestCase):
    def rows(self):
        w = World()
        decision = __import__("records.api", fromlist=["decide"]).decide(w.slot.media_id, w.slot.slot_id, subject_id=SUBJECT)
        masters.set_media_active(w.admin, w.slot.media_id, False)  # 매체 비활성화 기록 한 줄
        return {
            "AuditLog": (AuditLog.objects.first(), "overwritten"),
            "BidPolicy": (BidPolicy.objects.first(), "overwritten"),
            "Bid": (Bid.objects.first(), 999),
            "LedgerEntry": (LedgerEntry.objects.first(), "overwritten"),
            "Decision": (Decision.objects.get(decision_id=decision.decision_id), "overwritten"),
            "AdGroupCreative": (AdGroupCreative.objects.first(), NOW + DAY),  # 소재 연결 — 끊거나 바꾸지 않는다
            "CreativeImage": (CreativeImage.objects.first(), 1),  # 소재가 보유한 이미지 — 보유량 상한과 공개 판정의 근거
            "MediaDeactivation": (MediaDeactivation.objects.first(), NOW + DAY),  # 매체를 끈 시각 — 그 전 결정의 반응 판정 근거
        }

    def test_positional_and_keyword_upserts_and_new_instance_saves_cannot_overwrite(self):
        for name, (row, value) in self.rows().items():
            model, field = type(row), OVERWRITE[name]
            original = getattr(row, field)
            conflict_fields = [model._meta.get_field(field)]
            pk = model._meta.pk.name
            calls = {
                "keyword upsert": lambda c: model.objects.bulk_create([c], update_conflicts=True, update_fields=[field], unique_fields=[pk]),
                "positional upsert": lambda c: model.objects.bulk_create([c], None, False, True, conflict_fields, [pk]),
                "positional upsert (batch_size)": lambda c: model.objects.bulk_create([c], 10, False, True, conflict_fields, [pk]),
            }
            for label, call in calls.items():
                with self.assertRaises(AppendOnlyError, msg=(name, label)):
                    call(clone_with_same_pk(row, field, value))
            with self.assertRaises((IntegrityError, AppendOnlyError), msg=(name, "save")), transaction.atomic():
                clone_with_same_pk(row, field, value).save()
            with self.assertRaises(AppendOnlyError, msg=(name, "force_update")):
                clone_with_same_pk(row, field, value).save(force_update=True)
            with self.assertRaises(AppendOnlyError, msg=(name, "update_fields")):
                clone_with_same_pk(row, field, value).save(update_fields=[field])
            with self.assertRaises((IntegrityError, AppendOnlyError), msg=(name, "update_or_create")), transaction.atomic():
                model.objects.update_or_create(pk=row.pk, defaults={field: value})
            self.assertEqual(getattr(model.objects.get(pk=row.pk), field), original, name)  # 원본 행은 그대로

    def test_ignore_conflicts_skips_but_never_overwrites(self):
        for name, (row, value) in self.rows().items():
            model, field = type(row), OVERWRITE[name]
            before = model.objects.count()
            model.objects.bulk_create([clone_with_same_pk(row, field, value)], ignore_conflicts=True)
            model.objects.bulk_create([clone_with_same_pk(row, field, value)], None, True)  # 위치 인자
            self.assertEqual((model.objects.count(), getattr(model.objects.get(pk=row.pk), field) == value), (before, False), name)

    def test_every_append_only_model_is_covered_here(self):
        """이 시험이 다루는 모델 = 프로젝트의 추가 전용 모델 전부(6-16j — 소재 이미지 보유·매체 비활성화 기록이 빠져 있었다). 새 추가 전용 모델은 여기에 더해야 통과한다."""
        from django.apps import apps

        from foundation.models import AppendOnlyModel

        self.assertEqual({m.__name__ for m in apps.get_models() if issubclass(m, AppendOnlyModel)}, set(OVERWRITE))
