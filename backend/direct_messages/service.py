from django.conf import settings
from django.db.models import Q
from accounts.models import get_avatar, get_nickname
from .models import Conversation, Message


def enabled():
    return settings.CAMPUS_DM_ENABLED


def can_start(user):
    return bool(enabled() and user.is_authenticated and user.is_active)


def conversations(user):
    return Conversation.objects.filter(Q(first_user=user)|Q(second_user=user))


def can_use(user):
    return can_start(user)


def unread(user):
    return Message.objects.filter(recipient=user, read_at__isnull=True).count()


def identity(user):
    profile = getattr(user,'campus_profile',None)
    return {'id':str(profile.user_uuid) if profile else None,'nickname':get_nickname(user),
            'avatar':get_avatar(user),'cohort':profile.cohort if profile else ''}


def configuration(user):
    return {'enabled':enabled(),'viewerId':str(user.pk),'canStart':can_start(user),'hasInbox':can_use(user)}
