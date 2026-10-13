"""One authenticated browser session per account; a new login replaces the previous one."""
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
import time

from django.db import OperationalError, connection, transaction

from eventing.events import start_platform_session
from .models import ActiveLogin


def session_is_current(key, user_id):
    owner = ActiveLogin.objects.filter(user_id=user_id).first()
    if owner is None:
        # Sessions created before this feature claim ownership once. A stale key
        # never reclaims it, even if the latest session has expired or logged out.
        if not get_user_model().objects.filter(pk=user_id, is_active=True).exists():
            return False
        owner, _ = ActiveLogin.objects.get_or_create(user_id=user_id, defaults={"session_key": key})
    return owner.session_key == key


def replace_login(session, user, now):
    # SQLite cannot upgrade two concurrent read transactions into writers. Retry
    # the complete transaction, never a partly committed ownership change.
    for attempt in range(4):
        try:
            return _replace_login(session, user, now)
        except OperationalError as error:
            if connection.vendor != "sqlite" or "locked" not in str(error).lower() or attempt == 3:
                raise
            time.sleep(.05 * (attempt + 1))


def _replace_login(session, user, now):
    from .session_policy import expire_record, notify_expiry

    if not session.session_key:
        session.create()
    with transaction.atomic():
        # Lock an existing account row as well as its optional ownership row, so
        # simultaneous first logins cannot both become current on MySQL.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        previous = ActiveLogin.objects.select_for_update().filter(user=user).first()
        previous_key = previous.session_key if previous else None
        ActiveLogin.objects.update_or_create(user=user, defaults={"session_key": session.session_key})
        if previous_key and previous_key != session.session_key:
            old = Session.objects.select_for_update().filter(session_key=previous_key).first()
            if old is not None:
                data = old.get_decoded()
                if str(data.get(SESSION_KEY)) == str(user.pk):
                    expire_record(old, data, "replaced", now=now, notify=False)
            # Notify only after commit: the old socket must observe the revoked
            # key, and a failed new login must not close the previous login.
            transaction.on_commit(lambda: notify_expiry(previous_key, "replaced"), robust=True)
        start_platform_session(user, session, now=now)
        session.save()
