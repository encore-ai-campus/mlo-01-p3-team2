from uuid import uuid4

from django.conf import settings
from django.db import models


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "준비 중"
        OPEN = "open", "참여 가능"
        DRAWN = "drawn", "추첨 완료"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    title = models.CharField(max_length=100, default="옥상 기프티콘 이벤트")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    opens_at = models.DateTimeField(null=True, blank=True)
    draw_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    drawn_at = models.DateTimeField(null=True, blank=True)
    animation_seconds = models.PositiveSmallIntegerField(default=10)
    winner_entry = models.ForeignKey("Entry", null=True, blank=True, on_delete=models.SET_NULL, related_name="won_events")
    winner_nickname = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Entry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    # Keep the participation-time name and result even if an account is later removed.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    nickname = models.CharField(max_length=20)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("joined_at", "id")
        constraints = [models.UniqueConstraint(fields=("event", "user"), name="raffle_once_per_account")]


class Control(models.Model):
    """One current event and one lock/revision shared by entries and draws."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    current_event = models.ForeignKey(Event, null=True, on_delete=models.SET_NULL)
    revision = models.PositiveBigIntegerField(default=0)
