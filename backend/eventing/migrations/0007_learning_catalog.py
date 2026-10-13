"""Add learning identities once; leave all published leisure identities intact."""
from uuid import UUID
from django.db import migrations


ROWS = (
    ('python', 'Python', '2f1c4e63-42e8-4672-952f-732f29f28738', '51c344fd-28f8-42f8-b618-619d41954fdb',
     '0a2e7beb-e01b-4c0f-b0b6-85dbe00452d6', 'e2046ecc-2c00-4c72-912c-4dc10479d72e', '1'),
    ('sql', 'SQL', 'eeffc103-cde9-4048-9dd5-7e8c05b8f4d8', '773a96e6-419e-484f-9566-edc65fdb87af',
     '8d2c99bf-eefe-43fd-871e-50122bc417c8', '424c4db5-0a92-42e2-a009-23c675c2b889', '2'),
)


def add_learning(apps, schema_editor):
    alias = schema_editor.connection.alias if schema_editor is not None else 'default'
    Floor = apps.get_model('eventing', 'MapFloor')
    Zone = apps.get_model('eventing', 'MapZone')
    Category = apps.get_model('eventing', 'ContentCategory')
    Content = apps.get_model('eventing', 'ContentItem')
    floor = Floor.objects.using(alias).get(code='campus')
    for subject, name, zone_id, category_id, mc_id, blank_id, classroom in ROWS:
        zone, _ = Zone.objects.using(alias).get_or_create(floor_id=floor.pk, code=f'{subject}-classroom', defaults={
            'zone_uuid': UUID(zone_id), 'zone_type': 'CLASSROOM', 'name': f'{classroom} 강의실 {name} 학습교실'})
        category, _ = Category.objects.using(alias).get_or_create(code=subject, defaults={
            'category_uuid': UUID(category_id), 'domain': 'LEARNING', 'name': f'{name} 학습'})
        for kind, identity, title in [('multiple-choice', mc_id, '객관식'), ('fill-blank', blank_id, '코드 빈칸')]:
            Content.objects.using(alias).get_or_create(code=f'{subject}-{kind}', defaults={
                'content_uuid': UUID(identity), 'category_id': category.pk, 'zone_id': zone.pk,
                'title': f'{name} {title}', 'content_kind': 'QUIZ', 'external_url': None, 'status': 'ACTIVE'})


class Migration(migrations.Migration):
    dependencies = [('eventing', '0006_add_more_game_cards')]
    operations = [migrations.RunPython(add_learning, migrations.RunPython.noop)]
