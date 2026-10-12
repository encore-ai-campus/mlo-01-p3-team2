import secrets
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


def survey_token():
    return secrets.token_urlsafe(32)


class SurveyConnection(models.Model):
    """Owner-authorized Google reader; its access key is never sent to clients."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    endpoint = models.URLField(max_length=500)
    access_key = models.CharField(max_length=128)
    form_id = models.CharField(max_length=128)
    form_url = models.URLField(max_length=500)
    token_parameter = models.CharField(max_length=40)
    connected_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)


class SurveyAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "설문 제출 대기"
        REGISTERED = "registered", "참가 완료"
        CLOSED = "closed", "참여 마감"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="survey_attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    nickname = models.CharField(max_length=20)
    form_id = models.CharField(max_length=128)
    token = models.CharField(max_length=64, unique=True, default=survey_token, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    response_id = models.CharField(max_length=256, null=True, blank=True, unique=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=40, blank=True)
    entry = models.ForeignKey(Entry, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("event", "user"), name="raffle_one_survey_per_account")]
        indexes = [models.Index(fields=("event", "status"), name="raffle_pending_surveys")]
