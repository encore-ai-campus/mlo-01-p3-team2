"""반응 처리(설계 §4.4, 계획 2-5). 수신함의 `RECEIVED` 를 규칙 체인과 과금 정책으로 `ACCEPTED`/`REJECTED` 로 바꾼다.

- **반응 하나 = 트랜잭션 하나**: 규칙 판정 → 과금(원장·잔액·일 소진액) → 상태 변경이 함께 커밋되거나 함께 되돌려진다.
  중간에 실패하면 반응은 `RECEIVED` 로 남고 과금도 없다. 다시 처리해도 과금은 한 번이다(`reaction_ref` 유일).
- **시각은 반응의 `received_at`**: 예산 일과 원장 시각이 처리 시각(자정 뒤 재처리 등)이 아니라 접수 시각 기준으로 일관된다.
- **과금액은 결정에 기록된 `applied_amount`**: 결정 이후 입찰·정책이 바뀌어도 다시 계산하지 않는다.
- 여러 프로세스가 동시에 돌려도 안전하다(행을 `RECEIVED` 일 때만 집고, 상태는 조건부 UPDATE 로 바꾼다). 단일 관리 프로세스가 기본 운영 방식이다.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from billing import api as billing

from .models import Decision, Reaction, ReactionStatus
from .rules import RuleInput, run_rules

logger = logging.getLogger(__name__)


def _now(now=None):
    return now if now is not None else timezone.now()


def reaction_ref(media_id, reaction_id):
    """과금 멱등 키. 같은 반응은 항상 같은 키다(처리를 몇 번·어느 시각에 해도 바뀌지 않는다)."""
    return f"{media_id}:{reaction_id}"


def _finish(row, status, now, reason=None, rule=None):
    """상태를 바꾸는 **유일한 곳**. 아직 `RECEIVED` 인 행만 바꾼다(끝난 반응은 다시 바뀌지 않는다)."""
    changed = Reaction.objects.filter(pk=row.pk, status=ReactionStatus.RECEIVED).update(
        status=status, reason_code=reason, applied_rule=rule, processed_at=now,
    )
    if changed != 1:
        raise RuntimeError(f"이미 처리된 반응의 상태를 바꾸려 했다: {row.pk}")


def _guard(row, decision):
    """**규칙 설정과 무관한 필수 조건**: 결정이 있고, 보고한 매체가 그 결정을 만든 매체이고, 광고가 있었다.

    규칙 체인은 정책(무엇을 인정할지)을 바꿀 수 있게 열어 둔 곳이고, 이 세 가지는 과금의 권한·근거라서 설정으로 빠질 수 없다.
    규칙이 이미 걸러 냈다면 여기 오지 않는다. 걸리면 규칙 이름 `guard` 로 거부한다.
    """
    if decision is None:
        return "guard", "unknown_decision"
    if decision.media_id != row.media_id:
        return "guard", "media_mismatch"
    if decision.creative_id is None:
        return "guard", "no_ad_shown"
    return None


def _process(inbox_id, now):
    row = Reaction.objects.select_for_update().filter(pk=inbox_id, status=ReactionStatus.RECEIVED).first()
    if row is None:
        return None  # 이미 처리됐거나 없다
    decision = Decision.objects.filter(decision_id=row.decision_id).first()
    accepted = frozenset(
        Reaction.objects.filter(decision_id=row.decision_id, status=ReactionStatus.ACCEPTED).values_list("type", flat=True)
    )
    facts = RuleInput(
        media_id=row.media_id, reaction_type=row.type, decision_exists=decision is not None,
        decision_media_id=decision.media_id if decision else None, ad_was_shown=bool(decision and decision.creative_id is not None),
        accepted_types=accepted,
    )
    rejection = run_rules(settings.REACTION_RULES, facts)
    if rejection is None:
        rejection = _guard(row, decision)
    if rejection is not None:
        _finish(row, ReactionStatus.REJECTED, now, reason=rejection[1], rule=rejection[0])
        return ReactionStatus.REJECTED
    billing.charge_for_reaction(  # 반응 유형이 과금 단위와 다르면 정책이 0 을 돌려줘 기록만 남는다(`None`)
        decision.owner_id, decision.campaign_id, row.type, decision.pricing_unit, decision.applied_amount,
        reaction_ref(row.media_id, row.reaction_id), now=row.received_at,
    )
    _finish(row, ReactionStatus.ACCEPTED, now)
    return ReactionStatus.ACCEPTED


def _note_failure(inbox_id):
    try:
        with transaction.atomic():
            Reaction.objects.filter(pk=inbox_id, status=ReactionStatus.RECEIVED).update(attempts=F("attempts") + 1)
    except Exception:  # noqa: BLE001 — 실패를 기록하다 또 실패해도 원래 오류를 가리지 않는다
        logger.exception("반응 처리 실패 횟수를 기록하지 못했다 inbox=%s", inbox_id)


def process_reaction(inbox_id, now=None):
    """반응 하나를 처리한다. 반환: `ACCEPTED`/`REJECTED`, 이미 처리됐으면 `None`. 실패하면 되돌리고 실패 횟수를 올린 뒤 예외를 올린다."""
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
    """오래된 순으로 `RECEIVED` 를 최대 `limit` 건 처리한다. 한 건의 실패가 다른 건을 막지 않는다. 반환: 결과별 건수.

    `should_stop()` 이 참이 되면 **현재 반응을 끝낸 뒤 다음 반응을 시작하지 않는다**(남은 것은 `RECEIVED` 로 둔다).
    """
    ids = list(
        Reaction.objects.filter(status=ReactionStatus.RECEIVED, attempts__lt=settings.REACTION_MAX_ATTEMPTS)
        .order_by("received_at", "inbox_id").values_list("inbox_id", flat=True)[:limit]
    )
    counts = {"accepted": 0, "rejected": 0, "skipped": 0, "failed": 0}
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
