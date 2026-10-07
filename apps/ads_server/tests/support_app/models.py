import uuid

from django.conf import settings
from django.db import models


class OwnedThing(models.Model):
    """소유권 헬퍼 테스트용. 테스트 설정에서만 설치된다."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=20)

    class Meta:
        db_table = "tests_support_ownedthing"
