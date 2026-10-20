from django.db import migrations, models


def preserve_existing_accounts(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    Profile.objects.using(schema_editor.connection.alias).filter(setup_complete=True).update(guide_completed=True)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0007_preserve_json_precision')]
    operations = [
        migrations.AddField('profile', 'guide_completed', models.BooleanField(default=False)),
        migrations.RunPython(preserve_existing_accounts, migrations.RunPython.noop),
    ]
