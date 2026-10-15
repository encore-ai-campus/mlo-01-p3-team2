from uuid import uuid4

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('raffle', '0002_surveyconnection_surveyattempt')]
    operations = [migrations.CreateModel(
        name='WinnerContact',
        fields=[
            ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ('image_png', models.BinaryField(editable=False)),
            ('byte_count', models.PositiveIntegerField(default=0, editable=False)),
            ('version', models.UUIDField(default=uuid4, editable=False)),
            ('updated_at', models.DateTimeField(auto_now=True)),
        ],
    )]
