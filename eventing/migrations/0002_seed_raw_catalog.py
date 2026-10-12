from uuid import UUID, uuid5

from django.db import migrations


NAMESPACE = UUID("f3054e00-1250-4c1d-9657-baffcee5d2ea")


def stable(kind, code):
    return uuid5(NAMESPACE, f"{kind}:{code}")


def seed_catalog(apps, schema_editor):
    ClassGroup = apps.get_model("eventing", "ClassGroup")
    MapFloor = apps.get_model("eventing", "MapFloor")
    MapZone = apps.get_model("eventing", "MapZone")
    ContentCategory = apps.get_model("eventing", "ContentCategory")
    ContentItem = apps.get_model("eventing", "ContentItem")

    groups = (
        ("mlo-1", "MLO 1기"), ("mlo-2", "MLO 2기"), ("mlo-3", "MLO 3기"),
        ("skn-34", "SKN 34기"), ("skn-36", "SKN 36기"), ("unassigned", "미지정"),
    )
    for code, name in groups:
        ClassGroup.objects.update_or_create(
            class_group_uuid=stable("class-group", code),
            defaults={"code": code, "name": name, "status": "ACTIVE"},
        )

    floors = (("campus", "18층 캠퍼스"), ("rooftop", "옥상"))
    for code, name in floors:
        MapFloor.objects.update_or_create(
            floor_uuid=stable("floor", code), defaults={"code": code, "name": name}
        )

    zones = (
        ("campus", "class34-board", "CLASSROOM", "3·4 강의실 게시판"),
        ("rooftop", "psych-booth", "CONTENT", "심리 테스트 존"),
        ("rooftop", "game-booth", "CONTENT", "게임 부스"),
    )
    for floor_code, code, zone_type, name in zones:
        floor = MapFloor.objects.get(floor_uuid=stable("floor", floor_code))
        MapZone.objects.update_or_create(
            zone_uuid=stable("zone", code),
            defaults={"floor": floor, "code": code, "zone_type": zone_type, "name": name},
        )

    categories = (("game", "LEARNING", "게임 콘텐츠"), ("psychology", "REST", "심리 테스트"))
    category_rows = {}
    for code, domain, name in categories:
        category_rows[code], _ = ContentCategory.objects.update_or_create(
            category_uuid=stable("category", code),
            defaults={"code": code, "domain": domain, "name": name, "parent_id": None},
        )

    contents = (
        ("gomoku", "game", "오목", "EXTERNAL_LINK", "https://vidkidz.tistory.com/192#waflashContainer", "game-booth"),
        ("war", "game", "전쟁시대", "EXTERNAL_LINK", "https://vidkidz.tistory.com/51#waflashContainer", "game-booth"),
        ("psych-test", "psychology", "심심테스트", "EXTERNAL_LINK", "https://simsimtest.com/", "psych-booth"),
    )
    for code, category_code, title, kind, url, zone_code in contents:
        zone = MapZone.objects.get(zone_uuid=stable("zone", zone_code))
        ContentItem.objects.update_or_create(
            content_uuid=stable("content", code),
            defaults={
                "code": code,
                "category": category_rows[category_code],
                "content_kind": kind,
                "title": title,
                "external_url": url,
                "zone": zone,
                "status": "ACTIVE",
                "published_at": None,
            },
        )


def unseed_catalog(apps, schema_editor):
    ContentItem = apps.get_model("eventing", "ContentItem")
    ContentCategory = apps.get_model("eventing", "ContentCategory")
    MapZone = apps.get_model("eventing", "MapZone")
    MapFloor = apps.get_model("eventing", "MapFloor")
    ClassGroup = apps.get_model("eventing", "ClassGroup")
    ContentItem.objects.filter(code__in=["gomoku", "war", "psych-test"]).delete()
    ContentCategory.objects.filter(code__in=["game", "psychology"]).delete()
    MapZone.objects.filter(code__in=["class34-board", "psych-booth", "game-booth"]).delete()
    MapFloor.objects.filter(code__in=["campus", "rooftop"]).delete()
    ClassGroup.objects.filter(code__in=["mlo-1", "mlo-2", "mlo-3", "skn-34", "skn-36", "unassigned"]).delete()


class Migration(migrations.Migration):
    dependencies = [("eventing", "0001_initial")]

    operations = [migrations.RunPython(seed_catalog, unseed_catalog)]
