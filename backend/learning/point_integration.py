"""Same-database wallet and immutable ledger; caller owns the answer transaction."""
from django.db import connection
from django.utils import timezone

from eventing.events import get_profile
from .models import PointWallet, PointLedger
from .point_policy import points_for


def ensure_wallet(user):
    profile = get_profile(user)
    return PointWallet.objects.get_or_create(profile=profile, defaults={'balance': 0})[0]


def wallet_balance(user):
    # Read-only: history/result reads do not award or initialize anything.
    return PointWallet.objects.filter(profile__user=user).values_list('balance', flat=True).first() or 0


def grant_answer_points(answer):
    if not connection.in_atomic_block:
        raise RuntimeError('Answer, wallet, ledger and outbox must share one transaction')
    wallet = ensure_wallet(answer.user)
    wallet = PointWallet.objects.select_for_update().get(pk=wallet.pk)
    delta = points_for(answer.session_question.session.difficulty) if answer.is_correct else 0
    points = {'eligible': answer.is_correct, 'quoted_points': delta, 'granted_points': 0,
              'attempt_uuid': str(answer.attempt_uuid), 'ledger_uuid': None,
              'balance_after': wallet.balance, 'status': 'not_eligible' if not answer.is_correct else 'no_reward'}
    if delta == 0:
        return points, None
    # One ledger per attempt is a DB invariant, independently of HTTP request IDs.
    ledger = PointLedger.objects.filter(answer=answer).first()
    if ledger is None:
        balance_after = wallet.balance + delta
        if balance_after >= 2**63:
            raise OverflowError('Point balance exceeds signed 64-bit range')
        wallet.balance = balance_after
        wallet.updated_at = timezone.now()
        wallet.save(update_fields=['balance', 'updated_at'])
        ledger = PointLedger.objects.create(profile=wallet.profile, answer=answer,
                                            delta=delta, balance_after=balance_after)
    points.update(status='granted', granted_points=ledger.delta, quoted_points=ledger.delta,
                  ledger_uuid=str(ledger.ledger_uuid), balance_after=ledger.balance_after)
    return points, ledger
