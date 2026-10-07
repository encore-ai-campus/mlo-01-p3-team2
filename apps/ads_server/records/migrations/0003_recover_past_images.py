"""교체되어 지금은 소재가 가리키지 않는 **과거 이미지**의 보유 관계(campaigns.CreativeImage)를 복구한다.

campaigns 0003 은 현재 이미지만 채운다. 이미 교체된 이미지는 파일이 디스크에 남아 있고 과거 결정(`Decision.snapshot.image_name`)이 그 URL 을
계속 가리키므로, 보유 관계가 없으면 캠페인이 살아 있어도 그 URL 이 404 가 되고 보유 총량 쿼터에도 빠진다. 복구 근거는 두 가지다.

1. 과거 결정의 `creative_id` + `snapshot.image_name`
2. 감사 로그 `creative.created`·`creative.image_replaced` 의 대상 소재와 `detail.image`

실제 파일이 없거나(지워졌거나 다른 저장소) 소재가 없으면 건너뛴다(없는 파일은 보유할 수 없다). 파일 크기는 저장소에서 읽는다.
이미 있는 관계는 건드리지 않는다(멱등).
"""
import uuid

from django.db import migrations

AUDIT_ACTIONS = ("creative.created", "creative.image_replaced")


def _size(storage, name):
    try:
        with storage.open(name) as f:
            f.seek(0, 2)
            return f.tell()
    except (OSError, ValueError):
        return None


def recover(apps, schema_editor):
    from assets.api import get_storage  # 파일 크기를 읽는 데만 쓴다(마이그레이션 시점의 설정을 따른다)

    Creative = apps.get_model("campaigns", "Creative")
    CreativeImage = apps.get_model("campaigns", "CreativeImage")
    Decision = apps.get_model("records", "Decision")
    AuditLog = apps.get_model("foundation", "AuditLog")

    found = {}  # (소재 ID, 이미지 이름) → 처음 쓰인 시각

    def note(creative_id, name, when):
        if isinstance(name, str) and name:
            key = (creative_id, name)
            if key not in found or when < found[key]:
                found[key] = when

    for creative_id, snapshot, decided_at in Decision.objects.filter(creative_id__isnull=False).values_list("creative_id", "snapshot", "decided_at"):
        note(creative_id, (snapshot or {}).get("image_name"), decided_at)
    for target_id, detail, created_at in AuditLog.objects.filter(target_type="campaigns.creative", action__in=AUDIT_ACTIONS).values_list("target_id", "detail", "created_at"):
        try:
            note(uuid.UUID(target_id), (detail or {}).get("image"), created_at)
        except ValueError:
            continue

    creatives = set(Creative.objects.values_list("pk", flat=True))
    known = set(CreativeImage.objects.values_list("creative_id", "image_name"))
    storage = get_storage()
    for (creative_id, name), when in sorted(found.items(), key=lambda kv: kv[1]):
        if creative_id not in creatives or (creative_id, name) in known:
            continue
        size = _size(storage, name)
        if size is None:
            continue
        CreativeImage.objects.create(creative_id=creative_id, image_name=name, image_bytes=size, created_at=when)


class Migration(migrations.Migration):
    dependencies = [
        ("records", "0002_decision_bid_ids"),
        ("campaigns", "0003_creative_images"),
        ("foundation", "0003_auditlog"),
    ]

    operations = [migrations.RunPython(recover, migrations.RunPython.noop)]
