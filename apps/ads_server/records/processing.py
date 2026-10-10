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
from events import api as events
from foundation.api import is_transient_lock_error

from . import basis as judgment_basis
from . import ordering
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
    judged_event(row, status, reason, rule, basis, now)  # 판정 이벤트(`ad.reaction`): 상태를 바꾼 같은 트랜잭션에서. 판정은 됐는데 이벤트가 없는 상태가 생기지 않는다


def judged_event(row, status, reason, rule, basis, now):
    """판정 이벤트를 outbox 에 쓴다. 라이브 판정(`_finish`)과 이벤트 백필(`backfill`)이 **같은 코드**를 쓴다 — 백필한 이벤트가 라이브로 만들었을 이벤트와 같게."""
    events.record_reaction(
        now=now, inbox_id=row.inbox_id, reaction_id=row.reaction_id, media_id=row.media_id, decision_id=row.decision_id, type=row.type,
        occurred_at=row.occurred_at, received_at=row.received_at, subject_id=row.subject_id, source=row.source, status=status,
        reason_code=reason, applied_rule=rule, basis=basis,
    )


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
    charge = billing.charge_for_reaction(  # 반응 유형이 과금 단위와 다르면 정책이 0 을 돌려줘 기록만 남는다(`None`)
        decision.owner_id, decision.campaign_id, row.type, decision.pricing_unit, decision.applied_amount,
        reaction_ref(row.media_id, row.reaction_id), now=row.received_at,
    )
    if charge is not None:
        _record_charge_event(charge, row, now)
    _finish(row, ReactionStatus.ACCEPTED, now, judgment_basis.build(facts, rule=None, reason=None, person=person, judged_at=now), person=person)
    return ReactionStatus.ACCEPTED


def _record_charge_event(charge, row, now):
    """과금 이벤트(`ad.charge`): 원장 `CHARGE` 한 줄마다 한 건, 과금과 **같은 트랜잭션**에서. 과금은 이 파일에서만 일어나므로(경계 검사) 원장에 이벤트 없는 `CHARGE` 가 생기지 않는다.
    결정 ID 는 원장에 열을 더하지 않고 이 반응의 결정에서 가져온다(원장은 추가 전용이고 결정은 반응이 알고 있다). 이미 과금된 반응을 다시 처리한 경우(`duplicate`)에도
    같은 이벤트 ID 라 한 줄만 남는다."""
    entry = charge.entry
    charge_event(
        entry_id=entry.entry_id, campaign_id=entry.campaign_id, charge_policy=entry.charge_policy, created_at=entry.created_at,
        reaction_ref=reaction_ref(row.media_id, row.reaction_id), decision_id=row.decision_id, charged=charge.charged, shortfall=charge.shortfall, now=now,
    )


def charge_event(*, entry_id, campaign_id, charge_policy, created_at, reaction_ref, decision_id, charged, shortfall, now):
    """과금 이벤트를 outbox 에 쓴다. 라이브 과금과 이벤트 백필이 **같은 코드**를 쓴다."""
    events.record_charge(
        now=now, entry_id=entry_id, campaign_id=campaign_id, charge_policy=charge_policy, created_at=created_at, reaction_ref=reaction_ref,
        decision_id=decision_id, requested_amount=charged + shortfall, charged_amount=charged, shortfall=shortfall, budget_day=billing.budget_day_of(created_at),
    )


def _note_failure(inbox_id):
    try:
        with transaction.atomic():
            Reaction.objects.filter(pk=inbox_id, status=ReactionStatus.RECEIVED).update(attempts=F("attempts") + 1)
    except Exception:  # noqa: BLE001 — 실패를 기록하다 또 실패해도 원래 오류를 가리지 않는다
        logger.exception("반응 처리 실패 횟수를 기록하지 못했다 inbox=%s", inbox_id)


def _wake_dependents(inbox_id):
    """같은 결정에서 보류 중이던 반응을 바로 다시 판정할 수 있게 한다(마지막 확인 시각을 비운다).

    보류는 앞 단계 반응(노출·클릭)이나 먼저 접수된 같은 유형이 **끝나길** 기다리는 것이다. 끝났다는 사건이 생기면 그때 다시 보면 되므로, 주기적 재확인은
    기한 경과를 잡는 안전망(느린 간격)이면 충분하다 — 보류 N 건을 짧은 주기로 계속 다시 판정하면 처리 프로세스가 보류분을 도는 데 다 쓰인다.

    - **커밋 뒤에, 트랜잭션 밖에서** 한다: 판정 트랜잭션 안에서 다른 반응 행을 건드리면 그 행을 판정 중인 다른 처리 프로세스와 (지갑·반응 행) 교착할 수 있다.
    - **끝난 반응과 같은 매체의 보류분만** 깨운다(다른 매체의 보고는 이 결정의 판정에 쓰이지 않는다 — `scoped_reactions`). 잠금 없는 조회로 후보를 고른 뒤
      그 행들만 PK 로 갱신한다: 조건만으로 갱신하면 훑는 도중 접수가 끝나지 않은 행에서 기다리게 된다.
    - 깨우기가 실패해도 안전망이 있으므로 판정 결과를 바꾸지 않는다.
    """
    try:
        decision_id, media_id = Reaction.objects.filter(pk=inbox_id).values_list("decision_id", "media_id").first()
        held = list(Reaction.objects.filter(decision_id=decision_id, media_id=media_id, status=ReactionStatus.RECEIVED, checked_at__isnull=False).values_list("pk", flat=True))
        if held:
            Reaction.objects.filter(pk__in=held, status=ReactionStatus.RECEIVED).update(checked_at=None)
    except Exception:  # noqa: BLE001
        logger.warning("보류 중인 반응을 깨우지 못했다(주기 재확인이 처리한다) inbox=%s", inbox_id, exc_info=True)


def process_reaction(inbox_id, now=None):
    """반응 하나를 처리한다. 반환: `ACCEPTED`/`REJECTED`/`PENDING`(앞 단계 반응을 기다리는 보류), 이미 처리됐으면 `None`. 실패하면 되돌리고 실패 횟수를 올린 뒤 예외를 올린다."""
    now = _now(now)
    try:
        ordering.wait_for_inflight_receipts(inbox_id)  # 판정 전에 진행 중인 접수(더 이른 시각의 반응)가 커밋되길 기다린다 — 잠금은 쥐지 않는다
        with transaction.atomic():
            outcome = _process(inbox_id, now)
    except Exception as error:
        if not is_transient_lock_error(error):  # 교착·잠금 초과는 실패가 아니다: 서버가 되돌렸을 뿐이라 횟수를 올리면 정상 반응이 자동 재처리에서 빠진다(상한 5)
            _note_failure(inbox_id)
        raise
    if outcome in (ReactionStatus.ACCEPTED, ReactionStatus.REJECTED):
        _wake_dependents(inbox_id)
    return outcome


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

    앞을 기다리는 보류분은 앞 단계가 끝나 **깨워지거나**(`_wake_dependents`) `REACTION_HOLD_RECHECK_SECONDS` 가 지나야 다시 대상이 된다.
    정렬은 **한 번도 확인하지 않은(또는 깨워진) 것 먼저**(접수 순서), 그 다음은 마지막 확인이 오래된 순이다 — 보류분이 아무리 쌓여도 새 반응이 그 뒤로 밀리지 않는다.

    `should_stop()` 이 참이 되면 **현재 반응을 끝낸 뒤 다음 반응을 시작하지 않는다**(남은 것은 `RECEIVED` 로 둔다).
    """
    now_for_due = _now(now)
    due = Q(checked_at__isnull=True) | Q(checked_at__lte=now_for_due - timedelta(seconds=settings.REACTION_HOLD_RECHECK_SECONDS))
    ids = list(
        Reaction.objects.filter(due, status=ReactionStatus.RECEIVED, attempts__lt=settings.REACTION_MAX_ATTEMPTS)
        .order_by(F("checked_at").asc(nulls_first=True), "received_at", "inbox_id").values_list("inbox_id", flat=True)[:limit]
    )
    counts = {"accepted": 0, "rejected": 0, "pending": 0, "skipped": 0, "failed": 0, "transient": 0}
    for inbox_id in ids:
        if should_stop is not None and should_stop():
            break
        try:
            outcome = process_reaction(inbox_id, now=now)
        except Exception as error:  # noqa: BLE001
            if is_transient_lock_error(error):  # 다음 주기에 다시 한다(실패 횟수는 그대로)
                logger.warning("반응 처리가 교착·잠금 초과로 되돌려졌다(다음 주기에 다시) inbox=%s", inbox_id)
                counts["transient"] += 1
            else:
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
