"""Read submitted Google responses from the local server, then register entries."""
from datetime import timedelta
import json
import logging
import re
import threading
import time
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import get_nickname
from . import service
from .live import publish_change
from .models import Entry, Event, SurveyAttempt, SurveyConnection

logger = logging.getLogger(__name__)
_sync_lock = threading.Lock()
_next_poll = 0
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class SurveyError(service.RaffleError):
    def __init__(self, message="설문 제출 결과를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.", status=503):
        super().__init__(message, status)


def valid_form_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and not url.username and not url.password
                and url.port in (None, 443) and url.hostname == "docs.google.com"
                and bool(re.fullmatch(r"/forms/d/(?:e/)?[A-Za-z0-9_-]+/viewform", url.path.rstrip("/"))))
    except ValueError:
        return False


def survey_url():
    value = settings.CAMPUS_RAFFLE_SURVEY_URL.strip()
    if valid_form_url(value):
        return value
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.hostname == "forms.gle" and not url.username
                and not url.password and url.port in (None, 443) and url.path.strip("/")):
            return value
    except ValueError:
        pass
    return ""


def valid_endpoint(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.hostname == "script.google.com" and not url.username
                and not url.password and url.port in (None, 443) and not url.query and not url.fragment
                and bool(re.fullmatch(r"/macros/s/[A-Za-z0-9_-]+/exec", url.path)))
    except ValueError:
        return False


class GoogleRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        url = urlsplit(new_url)
        if (url.scheme != "https" or url.hostname not in {"script.google.com", "script.googleusercontent.com"}
                or url.username or url.password or url.port not in (None, 443)):
            raise SurveyError("Google 연결 배포 설정을 확인해 주세요.")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def google_request(connection, action, **extra):
    if not valid_endpoint(connection.endpoint):
        raise SurveyError("Google 연결 주소를 확인해 주세요.", 400)
    payload = {"version": 1, "action": action, "accessKey": connection.access_key, **extra}
    request = Request(connection.endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with build_opener(GoogleRedirect()).open(request, timeout=settings.CAMPUS_RAFFLE_SURVEY_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError
        return result
    except (URLError, OSError, ValueError, RecursionError):
        # Never expose request bodies, shared keys, or Google response data.
        raise SurveyError("Google 연결 주소·연결 키·배포 권한을 확인해 주세요.") from None


def metadata(result):
    try:
        checked_at = parse_datetime(result.get("checkedAt", ""))
    except (TypeError, ValueError):
        raise SurveyError() from None
    if (type(result.get("version")) is not int or result["version"] != 1
            or result.get("formId") != settings.CAMPUS_RAFFLE_SURVEY_FORM_ID
            or not valid_form_url(result.get("formUrl"))
            or not isinstance(result.get("tokenParameter"), str)
            or not re.fullmatch(r"entry\.[0-9]{1,20}", result["tokenParameter"])
            or checked_at is None or timezone.is_naive(checked_at)):
        raise SurveyError("연결된 Google 설문 정보를 확인해 주세요.")
    expected = survey_url()
    if expected and urlsplit(expected).hostname == "docs.google.com":
        if urlsplit(result["formUrl"]).path.rstrip("/") != urlsplit(expected).path.rstrip("/"):
            raise SurveyError("이벤트에 설정된 설문과 연결한 설문이 달라요.")
    return checked_at


def connect(endpoint, access_key):
    if not valid_endpoint(endpoint) or not isinstance(access_key, str) or not KEY_PATTERN.fullmatch(access_key):
        raise SurveyError("Google 웹 앱 주소와 연결 키를 확인해 주세요.", 400)
    candidate = SurveyConnection(endpoint=endpoint, access_key=access_key)
    result = google_request(candidate, "info")
    checked_at = metadata(result)
    if result.get("acceptingResponses") is not True:
        raise SurveyError("Google 설문을 게시하고 응답 접수를 열어 주세요.", 400)
    with transaction.atomic():
        candidate, _ = SurveyConnection.objects.update_or_create(pk=1, defaults={
            "endpoint": endpoint, "access_key": access_key, "form_id": result["formId"],
            "form_url": result["formUrl"], "token_parameter": result["tokenParameter"],
            "connected_at": timezone.now(), "last_checked_at": checked_at, "last_error": "",
        })
        transaction.on_commit(publish_change)
    return candidate


def view_state(user=None, event_id=None):
    connection = SurveyConnection.objects.filter(pk=1).first()
    attempt = (SurveyAttempt.objects.filter(event_id=event_id, user=user).first()
               if user is not None and event_id is not None else None)
    data = {"configured": bool(survey_url() and connection and connection.form_id == settings.CAMPUS_RAFFLE_SURVEY_FORM_ID),
            "status": attempt.status if attempt else None,
            "checkIntervalSeconds": settings.CAMPUS_RAFFLE_SURVEY_POLL_SECONDS,
            "lastCheckedAt": service.iso(connection.last_checked_at) if connection else None}
    if user is not None and user.is_staff:
        data["endpoint"] = connection.endpoint if connection else ""
        data["error"] = connection.last_error if connection else ""
    return data


def prefilled_url(connection, token):
    url = urlsplit(connection.form_url)
    query = [(key, value) for key, value in parse_qsl(url.query) if not key.startswith("entry.") and key != "usp"]
    query += [("usp", "pp_url"), (connection.token_parameter, token)]
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ""))


@service.retry_locked
def begin(user, position, expected_id):
    connection = SurveyConnection.objects.filter(pk=1).first()
    if not survey_url() or connection is None or connection.form_id != settings.CAMPUS_RAFFLE_SURVEY_FORM_ID:
        raise SurveyError("설문 응답 연결을 준비 중입니다. 관리자에게 문의해 주세요.")
    with transaction.atomic():
        control = service.locked_control()
        service.require_target(control, expected_id)
        event, now = control.current_event, timezone.now()
        if not user.is_active:
            raise service.RaffleError("다시 로그인해 주세요.", 401)
        if event is None or event.status != Event.Status.OPEN or (event.draw_at and now >= event.draw_at):
            raise service.RaffleError("지금은 이벤트 참여 시간이 아니에요.")
        if Entry.objects.filter(event=event, user=user).exists():
            raise service.RaffleError("이미 이벤트 참가 명단에 등록됐어요.")
        attempt = SurveyAttempt.objects.filter(event=event, user=user).first()
        if attempt is None:
            if not service.valid_buzzer_position(position):
                raise service.RaffleError("옥상 이벤트 부저 가까이에서 참여해 주세요.", 403)
            attempt = SurveyAttempt.objects.create(event=event, user=user, nickname=get_nickname(user), form_id=connection.form_id)
        if attempt.status != SurveyAttempt.Status.PENDING:
            raise service.RaffleError("이미 처리된 설문 참여입니다.")
        transaction.on_commit(publish_change)
        return prefilled_url(connection, attempt.token)


def validated_responses(result, connection, tokens):
    checked_at = metadata(result)
    if result["formId"] != connection.form_id or result["tokenParameter"] != connection.token_parameter:
        raise SurveyError("Google 설문 연결 설정이 변경됐어요. 다시 연결해 주세요.")
    responses = result.get("responses")
    if not isinstance(responses, list) or len(responses) > len(tokens):
        raise SurveyError()
    seen_tokens, seen_ids, records = set(), set(), []
    try:
        for row in responses:
            if not isinstance(row, dict):
                raise ValueError
            token, response_id = row.get("token"), row.get("responseId")
            submitted_at = parse_datetime(row.get("submittedAt", ""))
            if (not isinstance(token, str) or token not in tokens or token in seen_tokens
                    or not isinstance(response_id, str) or not 1 <= len(response_id) <= 256 or response_id in seen_ids
                    or submitted_at is None or timezone.is_naive(submitted_at) or submitted_at > checked_at):
                raise ValueError
            seen_tokens.add(token)
            seen_ids.add(response_id)
            records.append({"token": token, "response_id": response_id, "submitted_at": submitted_at})
    except (ValueError, TypeError):
        raise SurveyError() from None
    return checked_at, records


@service.retry_locked
def accept_submission(connection, record):
    """Only the authenticated Google reader calls this; no browser completion API."""
    with transaction.atomic():
        control = service.locked_control()
        attempt = SurveyAttempt.objects.select_related("event", "user").filter(token=record["token"]).first()
        if attempt is None or attempt.status != SurveyAttempt.Status.PENDING:
            return False
        if attempt.form_id != connection.form_id:
            raise SurveyError()
        if SurveyAttempt.objects.filter(response_id=record["response_id"]).exists():
            raise SurveyError("이미 처리된 Google 응답입니다.")
        event, submitted = attempt.event, record["submitted_at"]
        reason = ""
        if submitted < attempt.requested_at:
            reason = "before_request"
        elif event.draw_at and submitted >= event.draw_at:
            reason = "after_deadline"
        elif event.status != Event.Status.OPEN or control.current_event_id != event.pk:
            reason = "event_closed"
        elif attempt.user is None or not attempt.user.is_active:
            reason = "account_unavailable"
        attempt.response_id, attempt.submitted_at = record["response_id"], submitted
        attempt.verified_at, attempt.closed_reason = timezone.now(), reason
        if reason:
            attempt.status = SurveyAttempt.Status.CLOSED
            attempt.save()
            transaction.on_commit(publish_change)
            return False
        entry, created = Entry.objects.get_or_create(event=event, user=attempt.user, defaults={"nickname": attempt.nickname})
        attempt.status, attempt.entry = SurveyAttempt.Status.REGISTERED, entry
        attempt.save()
        transaction.on_commit(publish_change)
        return created


def synchronize(*, required_after=None, wait=False):
    acquired = _sync_lock.acquire(timeout=settings.CAMPUS_RAFFLE_SURVEY_REQUEST_TIMEOUT_SECONDS + 1) if wait else _sync_lock.acquire(blocking=False)
    if not acquired:
        raise SurveyError("설문 제출 확인 중입니다. 잠시 후 다시 시도해 주세요.")
    connection = None
    try:
        pending = list(SurveyAttempt.objects.filter(status=SurveyAttempt.Status.PENDING, event__status=Event.Status.OPEN)
                       .order_by("requested_at").values("token", "requested_at"))
        if not pending:
            return 0
        connection = SurveyConnection.objects.filter(pk=1).first()
        if connection is None:
            raise SurveyError("설문 연결을 먼저 설정해 주세요.")
        registered = 0
        checked_at = None
        for offset in range(0, len(pending), 100):
            batch = pending[offset:offset + 100]
            tokens = {row["token"] for row in batch}
            since = min(row["requested_at"] for row in batch) - timedelta(seconds=1)
            result = google_request(connection, "responses", tokens=sorted(tokens), since=since.isoformat())
            checked_at, records = validated_responses(result, connection, tokens)
            if required_after and checked_at < required_after:
                raise SurveyError("참여 마감 시점의 설문을 확인 중입니다. 잠시 후 다시 추첨해 주세요.")
            for record in records:
                registered += int(accept_submission(connection, record))
        SurveyConnection.objects.filter(pk=1).update(last_checked_at=checked_at, last_error="")
        return registered
    except SurveyError as error:
        if connection:
            SurveyConnection.objects.filter(pk=1).update(last_error=error.message)
        raise
    finally:
        _sync_lock.release()


def poll_due():
    global _next_poll
    now = time.monotonic()
    if now < _next_poll:
        return
    _next_poll = now + settings.CAMPUS_RAFFLE_SURVEY_POLL_SECONDS
    try:
        synchronize()
    except SurveyError:
        logger.warning("Google survey confirmation unavailable; pending entries will be retried")


def prepare_manual_draw(expected_id):
    """Freeze entry requests before checking every pending submission."""
    with transaction.atomic():
        control = service.locked_control()
        service.require_target(control, expected_id)
        event = control.current_event
        if event is None or event.status != Event.Status.OPEN:
            return
        now = timezone.now()
        if event.draw_at is None or event.draw_at > now:
            event.draw_at = now
            event.save(update_fields=("draw_at",))
            transaction.on_commit(publish_change)
        deadline = event.draw_at
    synchronize(required_after=deadline, wait=True)


def ready_for_scheduled_draw(event):
    if not SurveyAttempt.objects.filter(event=event, status=SurveyAttempt.Status.PENDING).exists():
        return True
    try:
        synchronize(required_after=event.draw_at, wait=True)
        return True
    except SurveyError:
        logger.warning("Rooftop draw deferred until submitted surveys can be confirmed")
        return False
