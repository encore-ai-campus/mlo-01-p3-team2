import uuid
from django.db import migrations, models

def populate(apps, schema_editor):
    Answer = apps.get_model('learning', 'UserAnswer')
    for answer in Answer.objects.using(schema_editor.connection.alias).all().iterator():
        Answer.objects.using(schema_editor.connection.alias).filter(pk=answer.pk).update(attempt_uuid=uuid.uuid4())

class Migration(migrations.Migration):
    dependencies = [('learning', '0001_initial')]
    operations = [
        migrations.AddField('question', 'subject', models.CharField(max_length=10, choices=[('python','Python'),('sql','SQL')], default='python')),
        migrations.AddField('question', 'question_code', models.CharField(max_length=32, null=True, blank=True)),
        migrations.AddField('learningsession', 'subject', models.CharField(max_length=10, choices=[('python','Python'),('sql','SQL')], default='python')),
        migrations.AddField('useranswer', 'attempt_uuid', models.UUIDField(null=True, editable=False)),
        migrations.AddField('useranswer', 'submission_request_uuid', models.UUIDField(null=True, blank=True, unique=True)),
        migrations.AddField('useranswer', 'response_snapshot', models.JSONField(default=dict, blank=True, editable=False)),
        migrations.RunPython(populate, migrations.RunPython.noop),
        migrations.AlterField('useranswer', 'attempt_uuid', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
        migrations.RemoveIndex('question','question_pool_idx'),
        migrations.AddIndex('question',models.Index(fields=['subject','difficulty','question_type','is_active'],name='question_subject_pool_idx')),
        migrations.AddConstraint('question',models.UniqueConstraint(fields=['subject','question_code'], name='subject_question_code_unique')),
        migrations.AddConstraint('question',models.CheckConstraint(condition=models.Q(subject__in=['python','sql']), name='question_subject_valid')),
        migrations.AddConstraint('learningsession',models.CheckConstraint(condition=models.Q(subject__in=['python','sql']), name='session_subject_valid')),
    ]
