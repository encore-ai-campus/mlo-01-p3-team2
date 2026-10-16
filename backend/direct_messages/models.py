import uuid
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dm_first_conversations')
    second_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dm_second_conversations')
    updated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['first_user','second_user'], name='dm_unique_user_pair'),
            models.CheckConstraint(condition=models.Q(first_user__lt=models.F('second_user')), name='dm_ordered_user_pair'),
        ]


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_direct_messages')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_direct_messages')
    request_id = models.UUIDField()
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at','id']
        constraints = [models.UniqueConstraint(fields=['sender','request_id'], name='dm_unique_send_request')]
        indexes = [
            models.Index(fields=['conversation','created_at'], name='dm_conversation_time'),
            models.Index(fields=['recipient','read_at'], name='dm_unread_recipient'),
        ]
