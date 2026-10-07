"""billing 의 규칙. 잔액은 원장 합계이고, 0 밑으로 내려가지 않으며, 같은 반응은 한 번만 과금한다(설계 §4.4-8~11)."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from foundation.api import MAX_AMOUNT, Role, clean_text, errors, parse_uuid, record_audit

from .budget_day import budget_day_of, day_start, next_reset
from .models import CampaignSpend, EntryType, LedgerEntry, Wallet
from .policies import get_charge_policy
from .types import ChargeResult, LedgerEntryView, WalletView


def _now(now=None):
    return now if now is not None else timezone.now()


def _entry_view(e):
    return LedgerEntryView(
        entry_id=e.entry_id, entry_type=e.entry_type, amount=e.amount, balance_after=e.balance_after, campaign_id=e.campaign_id,
        charge_policy=e.charge_policy, shortfall=e.shortfall, note=e.note, created_at=e.created_at,
    )


def _audit(actor, action, target, detail=None):
    record_audit(None, action, target=target, actor=actor, detail=detail)


def _lock_wallet(owner_id):
    try:
        return Wallet.objects.select_for_update().get(owner_id=owner_id)
    except Wallet.DoesNotExist:
        raise errors.NotFound("지갑을 찾을 수 없습니다.")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _append(wallet, entry_type, amount, now, **extra):
    """원장 한 줄을 더하고 잔액을 같은 트랜잭션에서 갱신한다. 호출한 쪽이 바깥 트랜잭션을 연다."""
    balance_after = wallet.balance + amount
    if not 0 <= balance_after <= MAX_AMOUNT:  # 마지막 방어선(호출한 쪽이 이미 검사했어야 한다). DB 제약도 같은 범위를 지킨다
        raise ValueError(f"잔액이 허용 범위를 벗어난다: {balance_after}")
    last_seq = LedgerEntry.objects.filter(wallet=wallet).order_by("-seq").values_list("seq", flat=True).first() or 0  # 지갑 잠금 안이라 다른 줄이 끼어들지 않는다
    entry = LedgerEntry.objects.create(
        wallet=wallet, seq=last_seq + 1, entry_type=entry_type, amount=amount, balance_after=balance_after, created_at=now, **extra
    )
    Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + amount)
    wallet.balance = balance_after
    return entry


def grant_signup(user, now=None):
    """가입 지급. **한 사용자에 한 번만**이고(재호출은 변화 없음), 호출한 쪽의 가입 트랜잭션 안에서 실행한다."""
    now = _now(now)
    if user.role != Role.ADVERTISER:
        raise errors.Forbidden("광고주만 지갑을 가진다.")
    points = settings.SIGNUP_GRANT_POINTS
    if not _is_int(points) or not 0 <= points <= MAX_AMOUNT:
        raise ImproperlyConfigured(f"SIGNUP_GRANT_POINTS 는 0 이상 {MAX_AMOUNT} 이하의 정수여야 한다: {points!r}")
    with transaction.atomic():
        wallet, _created = Wallet.objects.get_or_create(owner=user, defaults={"created_at": now})
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        existing = LedgerEntry.objects.filter(wallet=wallet, entry_type=EntryType.SIGNUP_GRANT).first()
        if existing is None and points > 0:
            existing = _append(wallet, EntryType.SIGNUP_GRANT, points, now, note="가입 지급")
            _audit(user, "billing.signup_grant", ("billing.wallet", wallet.pk), {"amount": points})
    return _entry_view(existing) if existing else None


def adjust(actor, user_id, amount, note, now=None):
    """관리자 조정(부호 있는 정수). 잔액을 0 밑으로 내리는 음수 조정은 거부한다. 사유는 필수."""
    now = _now(now)
    if not (getattr(actor, "is_authenticated", False) and actor.is_active and actor.role == Role.ADMIN):
        raise errors.Forbidden("관리자만 할 수 있습니다.")
    note = clean_text(note, "사유", "/note", 200)
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0 or abs(amount) > MAX_AMOUNT:
        raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"0이 아닌 정수(절댓값 {MAX_AMOUNT} 이하)여야 합니다."}])
    with transaction.atomic():
        wallet = _lock_wallet(parse_uuid(user_id, "지갑"))
        if wallet.balance + amount < 0:
            raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"잔액({wallet.balance})보다 많이 차감할 수 없습니다."}])
        if wallet.balance + amount > MAX_AMOUNT:  # 개별 금액이 범위 안이어도 합산 결과가 잔액 상한을 넘을 수 있다
            raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"조정 후 잔액이 {MAX_AMOUNT} 을 넘을 수 없습니다."}])
        entry = _append(wallet, EntryType.ADMIN_ADJUST, amount, now, note=note)
        _audit(actor, "billing.adjusted", ("billing.wallet", wallet.pk), {"amount": amount, "note": note, "balance_after": entry.balance_after})
    return _entry_view(entry)


def _charge(owner_id, campaign_id, amount, reaction_ref, policy_name, now):
    existing = LedgerEntry.objects.filter(reaction_ref=reaction_ref).first()
    if existing is not None:
        return ChargeResult(_entry_view(existing), charged=-existing.amount, shortfall=existing.shortfall, duplicate=True)
    wallet = _lock_wallet(owner_id)
    charged = min(amount, wallet.balance)  # 남은 잔액까지만. 0 밑으로 내리지 않는다
    entry = _append(
        wallet, EntryType.CHARGE, -charged, now, campaign_id=campaign_id, reaction_ref=reaction_ref,
        charge_policy=policy_name, shortfall=amount - charged,
    )
    if charged:
        spend, _ = CampaignSpend.objects.get_or_create(campaign_id=campaign_id, budget_day=budget_day_of(now))
        CampaignSpend.objects.filter(pk=spend.pk).update(spent=F("spent") + charged)
    return ChargeResult(_entry_view(entry), charged=charged, shortfall=amount - charged, duplicate=False)


def charge_for_reaction(owner_id, campaign_id, reaction_type, pricing_unit, applied_amount, reaction_ref, now=None):
    """반응 하나의 과금(Step 2-5 가 부른다). 정책이 0 이라고 하면 `None`(과금 없음).

    **멱등**: 같은 `reaction_ref` 는 몇 번을 불러도 한 번만 차감하고 처음 결과를 돌려준다(최소 한 번 전달 + 멱등 처리).
    한 트랜잭션에서 ① 원장 `CHARGE` ② 지갑 잔액 ③ 그날 소진액을 함께 바꾼다.
    """
    now = _now(now)
    if not _is_int(applied_amount) or not 1 <= applied_amount <= MAX_AMOUNT:  # 소수·bool·범위 밖은 원장·잔액·소진액 어디에도 닿기 전에 거절
        raise errors.InvalidRequest(errors=[{"pointer": "/applied_amount", "message": f"1 이상 {MAX_AMOUNT} 이하의 정수여야 합니다."}])
    policy = get_charge_policy(settings.BILLING_CHARGE_POLICY)
    amount = policy.amount_for(reaction_type, pricing_unit, applied_amount)
    if not _is_int(amount) or not 0 <= amount <= MAX_AMOUNT:  # 정책이 잘못된 값을 돌려주는 것은 서버 쪽 결함이다
        raise ValueError(f"과금 정책 {policy.name!r} 이(가) 올바르지 않은 과금액을 돌려줬다: {amount!r}")
    if amount == 0:
        return None
    if not isinstance(reaction_ref, str) or not (1 <= len(reaction_ref) <= 100):
        raise errors.InvalidRequest(errors=[{"pointer": "/reaction_ref", "message": "1~100자 문자열이어야 합니다."}])
    owner_id, campaign_id = parse_uuid(owner_id, "지갑"), parse_uuid(campaign_id, "캠페인")
    try:
        with transaction.atomic():
            return _charge(owner_id, campaign_id, amount, reaction_ref, policy.name, now)
    except IntegrityError:  # 동시에 같은 키가 들어온 경우의 안전망(유니크 제약): 먼저 들어간 결과를 돌려준다
        existing = LedgerEntry.objects.get(reaction_ref=reaction_ref)
        return ChargeResult(_entry_view(existing), charged=-existing.amount, shortfall=existing.shortfall, duplicate=True)


def get_wallet(user, now=None):
    now = _now(now)
    try:
        wallet = Wallet.objects.get(owner=user)
    except Wallet.DoesNotExist:
        raise errors.NotFound("지갑을 찾을 수 없습니다.")
    day = budget_day_of(now)
    start = day_start(day)
    spent = (
        LedgerEntry.objects.filter(wallet=wallet, entry_type=EntryType.CHARGE, created_at__gte=start, created_at__lt=start + timedelta(days=1))
        .aggregate(s=Sum("amount"))["s"] or 0
    )
    return WalletView(owner_id=user.pk, balance=wallet.balance, spent_today=-spent, budget_day=day, resets_at=next_reset(now))


def list_ledger(user, before=None, limit=50):
    """원장 내역(최신순). `before` 는 앞 쪽의 `next_cursor`(지갑 안의 순번 `seq`). 반환: (항목 목록, 다음 커서 또는 None)."""
    limit = max(1, min(int(limit), 200))
    qs = LedgerEntry.objects.filter(wallet__owner=user).order_by("-seq")
    if before is not None:
        qs = qs.filter(seq__lt=int(before))
    rows = list(qs[: limit + 1])
    next_cursor = rows[limit - 1].seq if len(rows) > limit else None
    return [_entry_view(e) for e in rows[:limit]], next_cursor


def balances(owner_ids):
    """여러 광고주의 잔액을 **질의 한 번**으로(결정 조립용). 지갑이 없으면 결과에 없다."""
    return dict(Wallet.objects.filter(owner_id__in=list(owner_ids)).values_list("owner_id", "balance"))


def spend_today(campaign_ids, now=None):
    """여러 캠페인의 오늘 소진액을 **질의 한 번**으로. 소진이 없으면 결과에 없다(0 으로 읽는다)."""
    day = budget_day_of(_now(now))
    return dict(CampaignSpend.objects.filter(campaign_id__in=list(campaign_ids), budget_day=day).values_list("campaign_id", "spent"))


def recompute_spend():
    """원장의 CHARGE 줄로 `CampaignSpend` 를 처음부터 다시 만든다(예산 일 경계 설정을 바꾼 뒤 실행). 만든 행 수를 돌려준다."""
    # 원장 읽기부터 교체까지 **한 쓰기 트랜잭션**이다. SQLite 는 시작할 때(IMMEDIATE) 쓰기 잠금을 잡으므로, 읽은 뒤 다른 연결의 과금이 끼어들어
    # 새 과금이 파생값에서 빠지는 일이 없다(과금은 이 트랜잭션이 끝날 때까지 기다린다).
    with transaction.atomic():
        totals = {}
        for campaign_id, created_at, amount in LedgerEntry.objects.filter(entry_type=EntryType.CHARGE, campaign_id__isnull=False).values_list("campaign_id", "created_at", "amount"):
            key = (campaign_id, budget_day_of(created_at))
            totals[key] = totals.get(key, 0) - amount
        CampaignSpend.objects.all().delete()
        CampaignSpend.objects.bulk_create([CampaignSpend(campaign_id=c, budget_day=d, spent=s) for (c, d), s in totals.items() if s > 0])
    return len([1 for s in totals.values() if s > 0])


def check_ledger():
    """정합성 점검: 지갑마다 `잔액 == 원장 합계`, `seq` 가 1부터 빈틈없이 이어지고 `balance_after` 가 줄마다 이어지는지. 어긋난 곳의 설명 목록(깨끗하면 빈 목록)."""
    problems = []
    for wallet in Wallet.objects.all():
        running = 0
        for expected_seq, entry in enumerate(LedgerEntry.objects.filter(wallet=wallet).order_by("seq"), start=1):
            if entry.seq != expected_seq:
                problems.append(f"지갑 {wallet.pk}: 원장 {entry.entry_id} 의 seq={entry.seq}, 기대={expected_seq}")
            running += entry.amount
            if entry.balance_after != running:
                problems.append(f"지갑 {wallet.pk}: 원장 {entry.entry_id} 의 balance_after={entry.balance_after}, 누적={running}")
        if wallet.balance != running:
            problems.append(f"지갑 {wallet.pk}: 잔액 {wallet.balance} != 원장 합계 {running}")
    return problems
