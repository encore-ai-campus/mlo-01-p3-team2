"""Replace the initial UUIDv5 seeds with UUIDv4 catalog identities."""
import copy
import json
from uuid import UUID, uuid5

from django.db import migrations

NAMESPACE = UUID("f3054e00-1250-4c1d-9657-baffcee5d2ea")
CATALOG_IDS = {
    ("class-group", "mlo-1"): "11447094-0d6e-4a23-af95-046197f09176",
    ("class-group", "mlo-2"): "f6ca7b43-bc09-4c82-a7e4-f1a48bdc21f3",
    ("class-group", "mlo-3"): "2cc41077-6fe6-402f-8be4-9e6a534059ca",
    ("class-group", "skn-34"): "fa054023-6ca8-46a7-9d49-87ac49be7cc6",
    ("class-group", "skn-36"): "03fb0fa9-26a1-4865-b434-0aaebc83b5c8",
    ("class-group", "unassigned"): "31a2cc4c-ddd8-4c6a-bcd0-846dbe774f32",
    ("floor", "campus"): "e389216d-067b-4716-aebd-43173921983a",
    ("floor", "rooftop"): "b4845343-2701-481f-8cb3-1ce4290fea3f",
    ("zone", "class34-board"): "3726e06f-bebc-47b1-a647-0a955beddcd6",
    ("zone", "psych-booth"): "909faffa-23de-4fda-9c26-5b46c8a8e783",
    ("zone", "game-booth"): "0ad110a0-1fcf-42fd-b093-18b938e92ab0",
    ("category", "game"): "4162b8c2-cd2a-4274-b8a6-b08474b16a33",
    ("category", "psychology"): "f67b0df1-c073-4455-9f98-005bf6882f55",
    ("content", "gomoku"): "911510a3-5f0d-42f5-b5ec-3ed0ac4bfebe",
    ("content", "war"): "a68383ec-8dd0-4357-9503-be68e525e886",
    ("content", "psych-test"): "f5a32338-1b5a-40d5-a30f-195e7011cf21",
}


def rekey_catalog(apps, schema_editor):
    Outbox = apps.get_model("eventing", "EventOutbox")
    published_ids = {
        value for raw in Outbox.objects.filter(published_at__isnull=False).values_list("raw_data", flat=True)
        for key, value in raw.items() if key.endswith("_uuid") and isinstance(value, str)
    }
    replacements = {}
    plan = (
        ("class-group", "ClassGroup", "class_group_uuid", ()),
        ("floor", "MapFloor", "floor_uuid", (("MapZone", "floor_id"), ("ChatMessage", "floor_id"))),
        ("zone", "MapZone", "zone_uuid", (("ContentItem", "zone_id"),)),
        ("category", "ContentCategory", "category_uuid", (("ContentCategory", "parent_id"), ("ContentItem", "category_id"))),
        ("content", "ContentItem", "content_uuid", ()),
    )
    for kind, model_name, primary_key, references in plan:
        Model = apps.get_model("eventing", model_name)
        for (id_kind, code), new_id in CATALOG_IDS.items():
            if id_kind != kind:
                continue
            old_id = uuid5(NAMESPACE, f"{kind}:{code}")
            old = Model.objects.filter(pk=old_id).first()
            if old is None:
                continue
            values = {
                field.attname: getattr(old, field.attname)
                for field in Model._meta.local_fields if not field.primary_key
            }
            # Clone under the original code before switching references. This
            # keeps every intermediate state valid on MySQL as well as SQLite.
            Model.objects.filter(pk=old_id).update(code="legacy-" + old_id.hex[:8])
            replacement = Model.objects.create(**{primary_key: UUID(new_id), **values})
            timestamps = {
                field.attname: values[field.attname] for field in Model._meta.local_fields
                if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False)
            }
            if timestamps:
                Model.objects.filter(pk=replacement.pk).update(**timestamps)
            for child_name, foreign_key in references:
                Child = apps.get_model("eventing", child_name)
                Child.objects.filter(**{foreign_key: old_id}).update(**{foreign_key: replacement.pk})
            # Preserve any identity that has already escaped to Kafka.
            if str(old_id) in published_ids:
                if hasattr(old, "status"):
                    Model.objects.filter(pk=old_id).update(status="HIDDEN" if kind == "content" else "INACTIVE")
            else:
                Model.objects.filter(pk=old_id).delete()
            replacements[str(old_id)] = new_id

    for row in Outbox.objects.filter(published_at__isnull=True).iterator(chunk_size=500):
        raw = {
            key: replacements.get(value, value) if isinstance(value, str) and key.endswith("_uuid") else value
            for key, value in row.raw_data.items()
        }
        if raw == row.raw_data:
            continue
        payload = copy.deepcopy(row.payload_json)
        if payload is not None:
            try:
                import xxhash
            except ImportError:
                payload = None
            else:
                payload["raw_data"] = raw
                encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                payload["raw_manifest"]["fingerprint"] = xxhash.xxh3_64(encoded).hexdigest()
        Outbox.objects.filter(pk=row.pk, published_at__isnull=True).update(raw_data=raw, payload_json=payload)


class Migration(migrations.Migration):
    dependencies = [("eventing", "0002_seed_raw_catalog")]
    operations = [migrations.RunPython(rekey_catalog)]
