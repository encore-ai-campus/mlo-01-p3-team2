"""반응 처리(설계 §4.4, 계획 2-5). 수신함의 `RECEIVED` 를 규칙 체인과 과금 정책으로 `ACCEPTED`/`REJECTED` 로 바꾼다.

- **반응 하나 = 트랜잭션 하나**: 규칙 판정 → 과금(원장·잔액·일 소진액) → 상태 변경이 함께 커밋되거나 함께 되돌려진다.
  중간에 실패하면 반응은 `RECEIVED` 로 남고 과금도 없다. 다시 처리해도 과금은 한 번이다(`reaction_ref` 유일).
- **시각은 반응의 `received_at`**: 예산 일과 원장 시각이 처리 시각(자정 뒤 재처리 등)이 아니라 접수 시각 기준으로 일관된다.
- **과금액은 결정에 기록된 `applied_amount`**: 결정 이후 입찰·정책이 바뀌어도 다시 계산하지 않는다.
- 여러 프로세스가 동시에 돌려도 안전하다(행을 `RECEIVED` 일 때만 집고, 상태는 조건부 UPDATE 로 바꾼다). 단일 관리 프로세스가 기본 운영 방식이다.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from billing import api as billing

from . import basis as judgment_basis
from . import facts as fact_gathering
from .models import Decision, Reaction, ReactionStatus
from .rules import MANDATORY_RULES, Hold, run_rules

logger = logging.getLogger(__name__)

PENDING = "PENDING"  # 처리 결과가 아니라 "앞 단계 반응을 기다린다"는 뜻(상태는 `RECEIVED` 그대로)


def _now(now=None):
    return now if now is not None else timezone.now()


def reaction_ref(media_id, reaction_id):
    """과금 멱등 키. 같은 반응은 항상 같은 키다(처리를 몇 번·어느 시각에 해도 바뀌지 않는다)."""
    return f"{media_id}:{reaction_id}"


def _finish(row, status, now, basis, reason=None, rule=None, person=None):
    """상태를 바꾸는 **유일한 곳**. 아직 `RECEIVED` 인 행만 바꾼다(끝난 반응은 다시 바뀌지 않는다). 인정할 때는 판정 단위의 사람도 함께 확정한다.

    판정 근거(`basis`)도 **같은 UPDATE 로 한 번** 쓴다 — 그래서 판정과 근거가 따로 놀지 않고, 이미 판정된 행은 조건(`RECEIVED`)에 걸려 근거도 바뀌지 않는다.
    """
    if status == ReactionStatus.ACCEPTED and person is None:
        raise RuntimeError(f"판정 단위의 사람이 없는 반응을 인정하려 했다: {row.pk}")
    if not basis:
        raise RuntimeError(f"판정 근거 없이 반응을 끝내려 했다: {row.pk}")
    accepted_key = f"{row.decision_id}:{person}:{row.type}" if status == ReactionStatus.ACCEPTED else None  # (결정, 사람, 유형)당 인정 1건을 DB 가 지킨다
    changed = Reaction.objects.filter(pk=row.pk, status=ReactionStatus.RECEIVED).update(
        status=status, reason_code=reason, applied_rule=rule, processed_at=now, person_id=person, accepted_key=accepted_key, basis=basis,
    )
    if changed != 1:
        raise RuntimeError(f"이미 처리된 반응의 상태를 바꾸려 했다: {row.pk}")


def _hold(row, now):
    """앞 단계 반응을 기다린다. 상태는 `RECEIVED` 그대로이고 실패가 아니므로 `attempts` 도 올리지 않는다. 마지막 확인 시각만 남겨 돌려가며 다시 판정한다."""
    Reaction.objects.filter(pk=row.pk, status=ReactionStatus.RECEIVED).update(checked_at=now)


def _process(inbox_id, now):
    row = Reaction.objects.select_for_update().filter(pk=inbox_id, status=ReactionStatus.RECEIVED).first()
    if row is None:
        return None  # 이미 처리됐거나 없다
    decision = Decision.objects.filter(decision_id=row.decision_id).first()
    facts = fact_gathering.gather(row, decision, now)
    verdict = run_rules(settings.REACTION_RULES, facts)
    if verdict is None or isinstance(verdict[1], Hold):
        # **필수 조건은 규칙 설정과 무관하게** 거친다(결정·매체·광고, 클릭 출처, 사람, 종료 전 수신). 설정에서 규칙을 빼도 이것들은 빠지지 않는다.
        mandatory = run_rules(MANDATORY_RULES, facts)
        if mandatory is not None:
            verdict = ("guard", mandatory[1])
    if verdict is not None and isinstance(verdict[1], Hold):
        _hold(row, now)
        return PENDING
    person = fact_gathering.person_of(decision, row.subject_id) if decision is not None else None  # 없는 결정에는 판정 단위의 사람이 없다(보고된 값은 basis.reaction 에만 남는다)
    if verdict is not None:
        basis = judgment_basis.build(facts, rule=verdict[0], reason=verdict[1], person=person, judged_at=now)
        _finish(row, ReactionStatus.REJECTED, now, basis, reason=verdict[1], rule=verdict[0])
        return ReactionStatus.REJECTED
    billing.charge_for_reaction(  # 반응 유형이 과금 단위와 다르면 정책이 0 을 돌려줘 기록만 남는다(`None`)
        decision.owner_id, decision.campaign_id, row.type, decision.pricing_unit, decision.applied_amount,
        reaction_ref(row.media_id, row.reaction_id), now=row.received_at,
    )
    _finish(row, ReactionStatus.ACCEPTED, now, judgment_basis.build(facts, rule=None, reason=None, person=person, judged_at=now), person=person)
    return ReactionStatus.ACCEPTED


def _note_failure(inbox_id):
    try:
        with transaction.atomic():
            Reaction.objects.filter(pk=inbox_id, status=ReactionStatus.RECEIVED).update(attempts=F("attempts") + 1)
    except Exception:  # noqa: BLE001 — 실패를 기록하다 또 실패해도 원래 오류를 가리지 않는다
        logger.exception("반응 처리 실패 횟수를 기록하지 못했다 inbox=%s", inbox_id)


def process_reaction(inbox_id, now=None):
    """반응 하나를 처리한다. 반환: `ACCEPTED`/`REJECTED`/`PENDING`(앞 단계 반응을 기다리는 보류), 이미 처리됐으면 `None`. 실패하면 되돌리고 실패 횟수를 올린 뒤 예외를 올린다."""
    now = _now(now)
    try:
        with transaction.atomic():
            return _process(inbox_id, now)
    except Exception:
        _note_failure(inbox_id)
        raise


def process_after_receipt(inbox_id):
    """수신 커밋 뒤 한 번 바로 처리해 본다. **어떤 실패도 접수 응답을 바꾸지 않는다**(남은 것은 재처리가 이어받는다)."""
    if not settings.REACTION_PROCESS_ON_RECEIPT:
        return None
    try:
        return process_reaction(inbox_id)
    except Exception:  # noqa: BLE001
        logger.warning("수신 직후 처리에 실패했다(재처리 대기) inbox=%s", inbox_id, exc_info=True)
        return None


def process_pending(limit=100, now=None, should_stop=None):
    """`RECEIVED` 를 최대 `limit` 건 처리한다. 한 건의 실패가 다른 건을 막지 않는다. 반환: 결과별 건수.

    앞 단계를 기다리는 보류분은 `REACTION_HOLD_RECHECK_SECONDS` 가 지나야 다시 대상이 된다 — 방금 확인한 보류분이 대기열 앞을 차지해
    새로 들어온 반응을 굶기지 않고 돌려가며 처리된다(정렬은 접수 순서 그대로다).

    `should_stop()` 이 참이 되면 **현재 반응을 끝낸 뒤 다음 반응을 시작하지 않는다**(남은 것은 `RECEIVED` 로 둔다).
    """
    now_for_due = _now(now)
    due = Q(checked_at__isnull=True) | Q(checked_at__lte=now_for_due - timedelta(seconds=settings.REACTION_HOLD_RECHECK_SECONDS))
    ids = list(
        Reaction.objects.filter(due, status=ReactionStatus.RECEIVED, attempts__lt=settings.REACTION_MAX_ATTEMPTS)
        .order_by("received_at", "inbox_id").values_list("inbox_id", flat=True)[:limit]
    )
    counts = {"accepted": 0, "rejected": 0, "pending": 0, "skipped": 0, "failed": 0}
    for inbox_id in ids:
        if should_stop is not None and should_stop():
            break
        try:
            outcome = process_reaction(inbox_id, now=now)
        except Exception:  # noqa: BLE001
            logger.exception("반응 처리 실패 inbox=%s", inbox_id)
            counts["failed"] += 1
            continue
        counts["skipped" if outcome is None else outcome.lower()] += 1
    return counts


def stuck_count():
    """실패가 반복돼 자동 재처리에서 빠진 반응 수. 0 이어야 정상이다(운영이 원인을 보고 `reset_stuck` 으로 되살린다)."""
    return Reaction.objects.filter(status=ReactionStatus.RECEIVED, attempts__gte=settings.REACTION_MAX_ATTEMPTS).count()


def reset_stuck():
    return Reaction.objects.filter(status=ReactionStatus.RECEIVED, attempts__gte=settings.REACTION_MAX_ATTEMPTS).update(attempts=0)
