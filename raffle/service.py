"""Server-authoritative entries, configurable deadlines, and one persisted winner."""
import math
import secrets
import time
from functools import wraps

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import get_nickname
from .live import publish_change
from .models import Control, Entry, Event, SurveyAttempt

BUZZER_POINT = (1540, 384)
ENTRY_RADIUS = 50  # Small allowance for the existing 100-ms movement reports.


class RaffleError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def iso(value):
    return value.isoformat() if value else None


def retry_locked(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        for attempt in range(6):
            try:
                return operation(*args, **kwargs)
            except OperationalError as exc:
                if connection.vendor != "sqlite" or "locked" not in str(exc).lower() or attempt == 5:
                    raise
                time.sleep(.02 * 2**attempt)
    return wrapped


@retry_locked
def snapshot(user=None):
    # A consistent read prevents a newer entry list being paired with an older revision.
    with transaction.atomic():
        control = Control.objects.select_related("current_event").get(pk=1)
        event = control.current_event
        data = {"revision": control.revision, "serverNow": iso(timezone.now()),
                "event": None, "participants": [], "myEntryId": None,
                "canManage": bool(user and user.is_staff), "popupGraceSeconds": 60}
        from .survey import view_state
        data["survey"] = view_state(user, event.pk if event else None)
        if event is None:
            return data
        entries = list(event.entries.all())
        data["event"] = {"id": str(event.pk), "title": event.title, "status": event.status,
                         "opensAt": iso(event.opens_at), "drawAt": iso(event.draw_at),
                         "openedAt": iso(event.opened_at), "drawnAt": iso(event.drawn_at),
                         "animationSeconds": event.animation_seconds,
                         "winner": {"entryId": str(event.winner_entry_id), "nickname": event.winner_nickname}
                         if event.winner_entry_id else None}
        data["participants"] = [{"id": str(entry.pk), "nickname": entry.nickname} for entry in entries]
        if user:
            data["myEntryId"] = next((str(entry.pk) for entry in entries if entry.user_id == user.pk), None)
        return data


def locked_control():
    # Start with a write, not select_for_update (which does not lock on SQLite).
    # This serializes entry acceptance, deadline transitions and duplicate draw requests.
    Control.objects.filter(pk=1).update(revision=F("revision") + 1)
    return Control.objects.select_related("current_event").get(pk=1)


def require_target(control, expected_id):
    current_id = str(control.current_event_id) if control.current_event_id else None
    if expected_id != current_id:
        raise RaffleError("이벤트가 변경됐어요. 새로 확인해 주세요.")


def valid_buzzer_position(position):
    try:
        return (position["floor"] == "rooftop"
                and all(type(position[key]) in (int, float) and math.isfinite(position[key]) for key in ("x", "y"))
                and math.hypot(position["x"] - BUZZER_POINT[0], position["y"] - BUZZER_POINT[1]) < ENTRY_RADIUS)
    except (KeyError, TypeError):
        return False


@retry_locked
def join(user, position, expected_id):
    if not valid_buzzer_position(position):
        raise RaffleError("옥상 이벤트 부저 가까이에서 참여해 주세요.", 403)
    with transaction.atomic():
        control = locked_control()
        require_target(control, expected_id)
        event = control.current_event
        now = timezone.now()
        if event is None or event.status != Event.Status.OPEN or (event.draw_at and now >= event.draw_at):
            raise RaffleError("지금은 이벤트 참여 시간이 아니에요.")
        entry, created = Entry.objects.get_or_create(event=event, user=user, defaults={"nickname": get_nickname(user)})
        if created:
            transaction.on_commit(publish_change)
        return str(entry.pk), created


def draw_locked(event, now):
    if event.status == Event.Status.DRAWN:
        return False
    entries = list(event.entries.all())
    winner = secrets.choice(entries) if entries else None
    event.status, event.drawn_at = Event.Status.DRAWN, now
    event.winner_entry = winner
    event.winner_nickname = winner.nickname if winner else ""
    event.save(update_fields=("status", "drawn_at", "winner_entry", "winner_nickname"))
    event.survey_attempts.filter(status=SurveyAttempt.Status.PENDING).update(status=SurveyAttempt.Status.CLOSED, closed_reason="not_submitted")
    return True


@retry_locked
def control_event(action, expected_id, *, title=None, opens_at=None, draw_at=None):
    if action == "draw":
        from .survey import prepare_manual_draw
        prepare_manual_draw(expected_id)
    now = timezone.now()
    with transaction.atomic():
        control = locked_control()
        require_target(control, expected_id)
        event = control.current_event
        if action == "prepare":
            if event and event.status != Event.Status.DRAWN:
                raise RaffleError("현재 이벤트를 먼저 진행해 주세요.")
            event = Event.objects.create(title=title or "옥상 기프티콘 이벤트", animation_seconds=settings.CAMPUS_RAFFLE_ANIMATION_SECONDS)
            control.current_event = event
            control.save(update_fields=("current_event",))
        elif action == "open":
            if event is None:
                event = Event.objects.create(animation_seconds=settings.CAMPUS_RAFFLE_ANIMATION_SECONDS)
                control.current_event = event
                control.save(update_fields=("current_event",))
            if event.status != Event.Status.DRAFT:
                raise RaffleError("이미 참여가 시작됐거나 추첨이 완료된 이벤트예요.")
            if event.draw_at and now >= event.draw_at:
                raise RaffleError("추첨 예약 시간을 다시 설정해 주세요.")
            event.status, event.opened_at, event.opens_at = Event.Status.OPEN, now, None
            event.save(update_fields=("status", "opened_at", "opens_at"))
        elif action == "draw":
            if event is None or event.status == Event.Status.DRAFT:
                raise RaffleError("참여를 먼저 시작해 주세요.")
            # Retrying the same event returns its original winner.
            if event.status != Event.Status.DRAWN:
                draw_locked(event, now)
        elif action == "schedule":
            if event is None or event.status == Event.Status.DRAWN:
                raise RaffleError("준비 중이거나 참여 중인 이벤트만 예약할 수 있어요.")
            if opens_at and (event.status != Event.Status.DRAFT or opens_at <= now):
                raise RaffleError("참여 시작은 준비 중인 이벤트의 미래 시간으로 설정해 주세요.", 400)
            if draw_at and (draw_at <= now or (opens_at and draw_at <= opens_at)):
                raise RaffleError("추첨은 참여 시작 이후의 미래 시간으로 설정해 주세요.", 400)
            event.title = title or event.title
            event.opens_at, event.draw_at = opens_at, draw_at
            event.save(update_fields=("title", "opens_at", "draw_at"))
        else:
            raise RaffleError("지원하지 않는 이벤트 조작이에요.", 400)
        transaction.on_commit(publish_change)


@retry_locked
def advance_due(now=None):
    now = now or timezone.now()
    candidate = Control.objects.select_related("current_event").get(pk=1).current_event
    if candidate is None or candidate.status == Event.Status.DRAWN:
        return False
    due_draw = candidate.draw_at and now >= candidate.draw_at
    due_open = candidate.status == Event.Status.DRAFT and candidate.opens_at and now >= candidate.opens_at
    if not (due_draw or due_open):
        return False
    if due_draw:
        from .survey import ready_for_scheduled_draw
        if not ready_for_scheduled_draw(candidate):
            return False
    with transaction.atomic():
        control = locked_control()
        event = control.current_event
        if event is None or event.status == Event.Status.DRAWN:
            return False
        changed = False
        if event.status == Event.Status.DRAFT and event.opens_at and now >= event.opens_at:
            event.status, event.opened_at = Event.Status.OPEN, now
            event.save(update_fields=("status", "opened_at"))
            changed = True
        if event.draw_at and now >= event.draw_at:
            changed = draw_locked(event, now) or changed
        if changed:
            transaction.on_commit(publish_change)
        return changed
