"""Preserve integer keys/history; add per-row UUIDs, a wallet and grant ledger."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_identity(apps, schema_editor):
    alias = schema_editor.connection.alias
    Question = apps.get_model('learning', 'Question')
    Choice = apps.get_model('learning', 'QuestionChoice')
    Answer = apps.get_model('learning', 'UserAnswer')
    Content = apps.get_model('eventing', 'ContentItem')
    for Model, field in [(Question, 'question_uuid'), (Choice, 'choice_uuid')]:
        for pk in Model.objects.using(alias).filter(**{f'{field}__isnull': True}).values_list('pk', flat=True).iterator():
            Model.objects.using(alias).filter(pk=pk).update(**{field: uuid.uuid4()})
    content_ids = dict(Content.objects.using(alias).filter(content_kind='QUIZ').values_list('code', 'pk'))
    for answer in Answer.objects.using(alias).select_related('session_question__session', 'session_question__question').iterator():
        session, question = answer.session_question.session, answer.session_question.question
        selected = None
        if question.question_type == 'multiple_choice':
            matches = [c.pk for c in Choice.objects.using(alias).filter(question_id=question.pk)
                       if c.choice_text.strip() == answer.submitted_answer.strip()]
            if len(matches) == 1:
                selected = matches[0]
        code = f'{question.subject}-{question.question_type.replace("_", "-")}'
        Answer.objects.using(alias).filter(pk=answer.pk).update(user_id=session.user_id,
            selected_choice_id=selected, content_id=content_ids.get(code))
    # No events, points, response snapshots or existing attempt UUIDs are rewritten.


def initialize_wallets(apps, schema_editor):
    alias = schema_editor.connection.alias
    Profile = apps.get_model('accounts', 'Profile')
    Wallet = apps.get_model('learning', 'PointWallet')
    for identity in Profile.objects.using(alias).values_list('user_uuid', flat=True).iterator():
        Wallet.objects.using(alias).get_or_create(profile_id=identity, defaults={'balance': 0})


class Migration(migrations.Migration):
    dependencies = [('learning', '0002_subject_submission_identity'), ('eventing', '0007_learning_catalog'),
                    ('accounts', '0005_profile_user_uuid'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField('question', 'question_uuid', models.UUIDField(null=True, editable=False)),
        migrations.AddField('questionchoice', 'choice_uuid', models.UUIDField(null=True, editable=False)),
        migrations.AlterField('useranswer', 'submission_request_uuid', models.UUIDField(null=True, blank=True)),
        migrations.AddField('useranswer', 'user', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True,
            on_delete=django.db.models.deletion.PROTECT, related_name='learning_answers')),
        migrations.AddField('useranswer', 'platform_session', models.ForeignKey(to='eventing.platformsession', null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField('useranswer', 'content', models.ForeignKey(to='eventing.contentitem', null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField('useranswer', 'selected_choice', models.ForeignKey(to='learning.questionchoice', null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT)),
        migrations.RunPython(backfill_identity, migrations.RunPython.noop),
        migrations.AlterField('question', 'question_uuid', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
        migrations.AlterField('questionchoice', 'choice_uuid', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
        migrations.AlterField('useranswer', 'user', models.ForeignKey(to=settings.AUTH_USER_MODEL,
            on_delete=django.db.models.deletion.PROTECT, related_name='learning_answers')),
        migrations.AddConstraint('useranswer', models.UniqueConstraint(fields=('user', 'submission_request_uuid'), name='answer_user_request_unique')),
        migrations.CreateModel('PointWallet', fields=[
            ('profile', models.OneToOneField(to='accounts.profile', to_field='user_uuid', db_column='user_uuid', primary_key=True,
                serialize=False, on_delete=django.db.models.deletion.PROTECT, related_name='point_wallet')),
            ('balance', models.PositiveBigIntegerField(default=0)),
            ('updated_at', models.DateTimeField(auto_now=True)),
        ], options={'constraints': [models.CheckConstraint(condition=models.Q(balance__gte=0), name='learning_wallet_nonnegative')]}),
        migrations.CreateModel('PointLedger', fields=[
            ('ledger_uuid', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('profile', models.ForeignKey(to='accounts.profile', to_field='user_uuid', db_column='user_uuid',
                on_delete=django.db.models.deletion.PROTECT, related_name='point_ledger')),
            ('answer', models.OneToOneField(to='learning.useranswer', to_field='attempt_uuid', db_column='attempt_uuid',
                on_delete=django.db.models.deletion.PROTECT, related_name='point_grant')),
            ('delta', models.PositiveBigIntegerField()), ('balance_after', models.PositiveBigIntegerField()),
            ('granted_at', models.DateTimeField(auto_now_add=True)),
        ], options={'ordering': ['granted_at', 'ledger_uuid'], 'constraints': [
            models.CheckConstraint(condition=models.Q(delta__gt=0), name='learning_ledger_positive'),
            models.CheckConstraint(condition=models.Q(balance_after__gte=0), name='learning_ledger_nonnegative')]}),
        migrations.RunPython(initialize_wallets, migrations.RunPython.noop),
    ]
