"""노출 전송 전에 소유권·반응 ID·요청 시각을 영속 저장한다.

전송할 작업의 예약과 재시도 일정을 보관한다. HTTP·결과 GET은 담당하지 않는다.
Django 모델은 함수 호출 시에만
가져오므로 저장소를 대체하는 단위 테스트와 표준 라이브러리 클라이언트가 분리된다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from uuid import UUID, uuid4



@dataclass(frozen=True, slots=True)
class StoredImpression:
    decision_id: str
    reaction_id: str
    subject_id: str
    occurred_at: str
    delivery_state: str
    status: str | None = None
    reason_code: str | None = None
    request_id: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    last_http_status: int | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None


class DecisionNotFound(Exception):
    """현재 사용자에게 발급한 결정이 없으며 타 사용자 존재 여부도 공개하지 않는다."""


class NoAdForDecision(Exception):
    """광고 없는 결정에는 노출을 생성할 수 없다."""


def _uuid(value: str | UUID) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise ValueError("식별자는 UUID여야 합니다.")
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("식별자는 UUID여야 합니다.") from error


def _utc_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value
    ):
        raise ValueError("시각은 UTC Z 형식이어야 합니다.")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("시각은 유효한 UTC 시각이어야 합니다.") from error


def _snapshot(record) -> StoredImpression:
    return StoredImpression(
        decision_id=str(record.decision_id),
        reaction_id=str(record.reaction_id),
        subject_id=str(record.subject_id),
        occurred_at=record.occurred_at,
        delivery_state=record.delivery_state,
        status=record.status,
        reason_code=record.reason_code,
        request_id=record.request_id,
        attempts=record.attempts,
        next_attempt_at=record.next_attempt_at,
        last_error=record.last_error,
        last_http_status=record.last_http_status,
        lease_token=None if record.lease_token is None else str(record.lease_token),
        lease_expires_at=record.lease_expires_at,
    )


def _aware_time(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field}는 시간대가 있는 시각이어야 합니다.")
    return value.astimezone(timezone.utc)


def _lease_end(now: datetime, lease_seconds: float) -> datetime:
    try:
        valid = (not isinstance(lease_seconds, bool) and isinstance(lease_seconds, (int, float))
                 and math.isfinite(lease_seconds) and lease_seconds > 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("전송 임대 시간은 유한한 양수여야 합니다.")
    try:
        expires = now + timedelta(seconds=lease_seconds)
    except OverflowError:
        raise ValueError("전송 임대 시간이 허용 범위를 넘었습니다.") from None
    if expires <= now:
        raise ValueError("전송 임대 시간은 시계 정밀도보다 길어야 합니다.")
    return expires





def reserve_impression(
    decision_id: str | UUID, owner_id: str | UUID, occurred_at: str,
    *, now: datetime | None = None, lease_seconds: float = 60,
) -> tuple[StoredImpression, bool]:
    from django.db import transaction

    from ..models import Impression, IssuedDecision

    decision_uuid = _uuid(decision_id)
    owner_uuid = _uuid(owner_id)
    _utc_time(occurred_at)
    current_time = _aware_time(now if now is not None else datetime.now(timezone.utc), "now")
    expires = _lease_end(current_time, lease_seconds)
    # 반환 뒤 즉시 HTTP를 보내므로 외부 트랜잭션 안에서 미커밋 기록을 반환하지 않는다.
    with transaction.atomic(durable=True):
        try:
            decision = IssuedDecision.objects.get(
                decision_id=decision_uuid, owner_id=owner_uuid
            )
        except IssuedDecision.DoesNotExist as error:
            raise DecisionNotFound("사용자에게 발급한 광고 결정이 없습니다.") from error
        if not decision.has_ad:
            raise NoAdForDecision("광고 없는 결정은 노출을 보고할 수 없습니다.")
        # OneToOne 고유 제약과 get_or_create가 중복 요청에서도 최초 기록을 유지한다.
        record, created = Impression.objects.get_or_create(
            decision=decision,
            defaults={
                # 현재 비밀로 가명을 다시 만들지 않고 결정 발급 당시 값을 고정한다.
                "subject_id": decision.subject_id, "occurred_at": occurred_at,
                "attempts": 1, "lease_token": uuid4, "lease_expires_at": expires,
            },
        )
        return _snapshot(record), created


def claim_due_impression(*, now: datetime, lease_seconds: float = 60) -> StoredImpression | None:
    """미확인 또는 임대가 만료된 기록 하나를 새 임대로 확보한 뒤 커밋한다."""
    from django.db import transaction
    from django.db.models import F, Q

    from ..models import Impression

    current_time = _aware_time(now, "now")
    expires = _lease_end(current_time, lease_seconds)
    due = (
        Q(delivery_state="UNCONFIRMED")
        & (Q(next_attempt_at__lte=current_time) | Q(next_attempt_at__isnull=True))
    ) | (
        Q(delivery_state="SENDING")
        & (Q(lease_expires_at__lte=current_time) | Q(lease_expires_at__isnull=True))
        & (Q(next_attempt_at__lte=current_time) | Q(next_attempt_at__isnull=True))
    )
    while True:
        with transaction.atomic(durable=True):
            candidate = Impression.objects.filter(due).order_by(
                "next_attempt_at", "reaction_id"
            ).values_list("reaction_id", flat=True).first()
            if candidate is None:
                return None
            # 읽은 뒤 다른 작업자가 선점해도 조건부 UPDATE에 성공한 한 작업자만 보낸다.
            claimed = Impression.objects.filter(due, reaction_id=candidate).update(
                delivery_state="SENDING", attempts=F("attempts") + 1,
                next_attempt_at=None, lease_token=uuid4(), lease_expires_at=expires,
            )
            if claimed:
                return _snapshot(Impression.objects.get(reaction_id=candidate))
        # 경합에서 졌으면 트랜잭션을 끝낸 뒤 최신 상태에서 다른 작업을 찾는다.


def claim_blocked_401_impression(
    reaction_id: str | UUID, *, now: datetime, lease_seconds: float = 60,
) -> StoredImpression | None:
    """명시한 401 차단 기록만 기존 요청 내용 그대로 새 전송 임대로 확보한다."""
    from django.db import transaction
    from django.db.models import F, Q

    from ..models import Impression

    reaction_uuid = _uuid(reaction_id)
    current_time = _aware_time(now, "now")
    expires = _lease_end(current_time, lease_seconds)
    # 조건을 UPDATE에 함께 적용해 다른 작업자의 임대나 뒤늦은 접수 확인을 덮지 않는다.
    with transaction.atomic(durable=True):
        claimed = Impression.objects.filter(
            Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=current_time),
            reaction_id=reaction_uuid, delivery_state="BLOCKED",
            last_http_status=401, status__isnull=True,
        ).update(
            delivery_state="SENDING", attempts=F("attempts") + 1,
            next_attempt_at=None, lease_token=uuid4(), lease_expires_at=expires,
        )
        if not claimed:
            return None
        # 반응 ID·결정 ID·가명·발생 시각은 변경하지 않고 커밋 후 전송할 스냅샷만 반환한다.
        return _snapshot(Impression.objects.get(reaction_id=reaction_uuid))


def finish_impression(
    reaction_id: str | UUID,
    *,
    delivery_state: str,
    status: str | None = None,
    reason_code: str | None = None,
    request_id: str | None = None,
    lease_token: str | UUID | None = None,
    next_attempt_at: datetime | None = None,
    last_error: str | None = None,
    last_http_status: int | None = None,
) -> StoredImpression:
    from django.db.models import Case, DateTimeField, F, Value, When

    from ..models import Impression

    if delivery_state not in {"ACKNOWLEDGED", "UNCONFIRMED", "BLOCKED"}:
        raise ValueError("지원하지 않는 노출 전송 상태입니다.")
    if status not in {None, "RECEIVED", "ACCEPTED", "REJECTED"}:
        raise ValueError("지원하지 않는 반응 처리 상태입니다.")
    if any(value is not None and not isinstance(value, str) for value in (reason_code, request_id)):
        raise ValueError("반응 메타데이터는 문자열이어야 합니다.")
    if last_error is not None and (
        not isinstance(last_error, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", last_error)
    ):
        raise ValueError("최근 오류는 정해진 진단 코드여야 합니다.")
    if last_http_status is not None and (type(last_http_status) is not int or not 100 <= last_http_status <= 599):
        raise ValueError("최근 HTTP 상태는 유효한 상태 번호여야 합니다.")
    next_at = None if next_attempt_at is None else _aware_time(next_attempt_at, "next_attempt_at")
    if delivery_state == "UNCONFIRMED" and next_at is None:
        # 이전 호출자도 기록을 잃지 않게 즉시 재시도 가능한 상태로 남긴다.
        next_at = datetime.now(timezone.utc)
    if delivery_state != "UNCONFIRMED":
        next_at = None
    reaction_uuid = _uuid(reaction_id)
    token = None if lease_token is None else _uuid(lease_token)
    records = Impression.objects.filter(reaction_id=reaction_uuid)
    schedule = next_at
    if delivery_state == "UNCONFIRMED":
        # 오래된 전송의 Retry-After도 유효하다. 상태·임대를 바꾸지 않고 최소 대기만 늘린다.
        # SQL에서 최댓값을 정해야 다른 전송의 더 긴 대기를 경쟁 갱신으로 덮어쓰지 않는다.
        schedule = Case(
            When(next_attempt_at__isnull=True, then=Value(next_at)),
            When(next_attempt_at__lt=next_at, then=Value(next_at)),
            default=F("next_attempt_at"),
            output_field=DateTimeField(),
        )
        records.filter(delivery_state__in=("SENDING", "UNCONFIRMED")).update(
            next_attempt_at=schedule,
        )
    if delivery_state == "ACKNOWLEDGED":
        # 오래된 임대의 2xx라도 같은 불변 요청의 접수 확인이므로 뒤늦은 실패보다 우선한다.
        records = records.exclude(delivery_state="ACKNOWLEDGED")
    else:
        records = records.filter(delivery_state="SENDING", lease_token=token)
    records.update(
        delivery_state=delivery_state,
        status=status,
        reason_code=reason_code,
        request_id=request_id,
        next_attempt_at=schedule, last_error=last_error, last_http_status=last_http_status,
        lease_token=None, lease_expires_at=None,
    )
    return _snapshot(Impression.objects.get(reaction_id=reaction_uuid))


class ImpressionNotReady(Exception):
    """접수 완료되지 않은 노출은 판정 조회 대상으로 삼지 않는다."""


def get_impression(*, decision_id: str | UUID, owner_id: str | UUID) -> StoredImpression:
    """사용자 소유의 기존 노출만 읽으며 새 기록을 만들지 않는다."""
    from ..models import Impression
    from django.db.models import F

    try:
        record = Impression.objects.get(
            decision_id=_uuid(decision_id), decision__owner_id=_uuid(owner_id),
            subject_id=F("decision__subject_id"), decision__has_ad=True,
        )
    except Impression.DoesNotExist:
        raise DecisionNotFound("사용자에게 발급한 노출 기록이 없습니다.") from None
    return _snapshot(record)


def update_result(*, decision_id: str | UUID, owner_id: str | UUID,
                  reaction_id: str | UUID, status: str, reason_code: str | None,
                  request_id: str | None) -> StoredImpression:
    """판정만 조건부 갱신한다. 이미 확정된 판정과 전송 정보는 보존한다."""
    from django.db.models import Q
    from ..models import Impression

    if status not in ("RECEIVED", "ACCEPTED", "REJECTED"):
        raise ValueError("지원하지 않는 반응 처리 상태입니다.")
    if any(value is not None and not isinstance(value, str) for value in (reason_code, request_id)):
        raise ValueError("반응 메타데이터는 문자열이어야 합니다.")
    record = get_impression(decision_id=decision_id, owner_id=owner_id)
    if record.reaction_id != str(_uuid(reaction_id)):
        raise DecisionNotFound("사용자에게 발급한 노출 기록이 없습니다.")
    if record.delivery_state != "ACKNOWLEDGED":
        raise ImpressionNotReady("접수 완료된 노출만 조회할 수 있습니다.")
    # 조회 중 다른 호출이 판정을 확정해도 늦은 응답이 그 결과를 덮지 않는다.
    Impression.objects.filter(
        Q(status__isnull=True) | Q(status="RECEIVED"),
        reaction_id=_uuid(reaction_id), delivery_state="ACKNOWLEDGED",
    ).update(status=status, reason_code=reason_code, request_id=request_id)
    return get_impression(decision_id=decision_id, owner_id=owner_id)
