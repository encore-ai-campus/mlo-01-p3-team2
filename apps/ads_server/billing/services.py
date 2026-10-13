"""billing 의 규칙. 잔액은 원장 합계이고, 0 밑으로 내려가지 않으며, 같은 반응은 한 번만 과금한다(설계 §4.4-8~11)."""
from contextlib import contextmanager
from datetime import timedelta
from itertools import batched

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Sum
from django.utils import timezone

from foundation.api import MAX_AMOUNT, Role, clean_request_key, clean_text, create_advertiser, errors, is_int, parse_uuid, record_audit, require_admin

from .budget_day import budget_day_of, day_start, next_reset
from .models import CampaignSpend, EntryType, LedgerEntry, Wallet
from .policies import get_charge_policy
from .types import ChargeEntryView, ChargeResult, LedgerEntryView, WalletView


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


def register_advertiser(username, password, nickname, class_label, request=None):
    """광고주 가입과 가입 지급을 **한 트랜잭션**으로(설계 §4.7: 지급이 실패하면 가입도 취소된다). 감사 로그(`account.signup`)도 같은 트랜잭션.
    가입 검증의 ValidationError(필드별)를 그대로 전달한다. `request` 는 감사 로그의 IP·요청 ID 용이다."""
    with transaction.atomic():
        user = create_advertiser(username, password, nickname, class_label)
        grant_signup(user)
        record_audit(request, "account.signup", target=user, actor=user, detail={"class_label": user.class_label})
    return user


def grant_signup(user, now=None):
    """가입 지급. **한 사용자에 한 번만**이고(재호출은 변화 없음), 호출한 쪽의 가입 트랜잭션 안에서 실행한다."""
    now = _now(now)
    if user.role != Role.ADVERTISER:
        raise errors.Forbidden("광고주만 지갑을 가진다.")
    points = settings.SIGNUP_GRANT_POINTS
    if not is_int(points) or not 0 <= points <= MAX_AMOUNT:
        raise ImproperlyConfigured(f"SIGNUP_GRANT_POINTS 는 0 이상 {MAX_AMOUNT} 이하의 정수여야 한다: {points!r}")
    with transaction.atomic():
        wallet, _created = Wallet.objects.get_or_create(owner=user, defaults={"created_at": now})
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        existing = LedgerEntry.objects.filter(wallet=wallet, entry_type=EntryType.SIGNUP_GRANT).first()
        if existing is None and points > 0:
            existing = _append(wallet, EntryType.SIGNUP_GRANT, points, now, note="가입 지급")
            _audit(user, "billing.signup_grant", ("billing.wallet", wallet.pk), {"amount": points})
    return _entry_view(existing) if existing else None


_ADJUST_KEY_REUSED = "이 조정 폼은 이미 다른 내용으로 처리됐습니다. 새로 불러와 다시 조정하세요."


def adjust(actor, user_id, amount, note, now=None, request_key=None):
    """관리자 조정(부호 있는 정수). 잔액을 0 밑으로 내리는 음수 조정은 거부한다. 사유는 필수.

    `request_key`(화면 폼 하나마다 새 값)를 주면 **같은 키는 한 번만 반영**한다: 키는 원장 줄에 금액 변경과 같은 트랜잭션으로 저장되고(유일 제약),
    같은 키·같은 내용의 다시 보냄(두 번 누름·동시 제출·응답이 실패한 뒤 재시도)은 처음 줄을 그대로 돌려준다. 같은 키에 다른 내용이면 409.
    지갑을 잠근 뒤 키를 보므로 동시에 들어온 같은 키는 뒤쪽이 앞쪽의 커밋을 기다렸다가 처음 줄을 받는다.
    """
    now = _now(now)
    require_admin(actor)
    note = clean_text(note, "사유", "/note", 200)
    if not is_int(amount) or amount == 0 or abs(amount) > MAX_AMOUNT:
        raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"0이 아닌 정수(절댓값 {MAX_AMOUNT} 이하)여야 합니다."}])
    request_key = clean_request_key(request_key)
    try:
        with transaction.atomic():
            return _adjust(actor, parse_uuid(user_id, "지갑"), amount, note, now, request_key)
    except IntegrityError:  # 다른 지갑에 같은 키(위조한 폼)만 여기에 온다 — 같은 지갑은 지갑 잠금이 줄 세운다
        if request_key is not None and LedgerEntry.objects.filter(adjust_key=request_key).exists():
            raise errors.Conflict(_ADJUST_KEY_REUSED)
        raise


def _adjust(actor, owner_id, amount, note, now, request_key):
    wallet = _lock_wallet(owner_id)
    if request_key is not None:
        done = LedgerEntry.objects.filter(adjust_key=request_key).first()
        if done is not None:
            if (done.wallet_id, done.amount, done.note) != (wallet.pk, amount, note):
                raise errors.Conflict(_ADJUST_KEY_REUSED)
            return _entry_view(done)
    if wallet.balance + amount < 0:
        raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"잔액({wallet.balance})보다 많이 차감할 수 없습니다."}])
    if wallet.balance + amount > MAX_AMOUNT:  # 개별 금액이 범위 안이어도 합산 결과가 잔액 상한을 넘을 수 있다
        raise errors.InvalidRequest(errors=[{"pointer": "/amount", "message": f"조정 후 잔액이 {MAX_AMOUNT} 을 넘을 수 없습니다."}])
    entry = _append(wallet, EntryType.ADMIN_ADJUST, amount, now, note=note, adjust_key=request_key)
    _audit(actor, "billing.adjusted", ("billing.wallet", wallet.pk), {"amount": amount, "note": note, "balance_after": entry.balance_after})
    return _entry_view(entry)


def _duplicate(entry):
    """이미 과금된 반응: 처음 결과를 그대로 돌려준다."""
    return ChargeResult(_entry_view(entry), charged=-entry.amount, shortfall=entry.shortfall, duplicate=True)


def _charge(owner_id, campaign_id, amount, reaction_ref, policy_name, now):
    existing = LedgerEntry.objects.filter(reaction_ref=reaction_ref).first()
    if existing is not None:
        return _duplicate(existing)
    wallet = _lock_wallet(owner_id)
    charged = min(amount, wallet.balance)  # 남은 잔액까지만. 0 밑으로 내리지 않는다
    entry = _append(
        wallet, EntryType.CHARGE, -charged, now, campaign_id=campaign_id, reaction_ref=reaction_ref,
        charge_policy=policy_name, shortfall=amount - charged,
    )
    if charged:
        _add_spend(campaign_id, budget_day_of(now), charged)
    return ChargeResult(_entry_view(entry), charged=charged, shortfall=amount - charged, duplicate=False)


def _add_spend(campaign_id, day, charged):
    """그날 소진액에 `charged` 를 더한다. **행의 키로 갱신하고 없을 때만 만든다** — 재계산이 행을 지우거나 새로 만드는 중이어도 이 증가분이 사라지지 않는다.

    (행의 PK 로 갱신하면, 그 사이에 재계산이 행을 지웠을 때 갱신이 0 행에 닿아 증가분이 조용히 없어진다.)
    """
    if CampaignSpend.objects.filter(campaign_id=campaign_id, budget_day=day).update(spent=F("spent") + charged):
        return
    try:
        with transaction.atomic():
            CampaignSpend.objects.create(campaign_id=campaign_id, budget_day=day, spent=charged)
    except IntegrityError:  # 동시에 다른 과금이 먼저 만들었다 → 그 행에 더한다
        CampaignSpend.objects.filter(campaign_id=campaign_id, budget_day=day).update(spent=F("spent") + charged)


def charge_for_reaction(owner_id, campaign_id, reaction_type, shares, applied_amount, reaction_ref, now=None):
    """반응 하나의 과금(Step 2-5 가 부른다). 정책이 0 이라고 하면 `None`(과금 없음).
    `shares` = {반응 유형: 비율(%)} — 그 반응의 결정에 남긴 값이다(6-10c, 지금 정책을 다시 읽지 않는다).

    **멱등**: 같은 `reaction_ref` 는 몇 번을 불러도 한 번만 차감하고 처음 결과를 돌려준다(최소 한 번 전달 + 멱등 처리).
    한 트랜잭션에서 ① 원장 `CHARGE` ② 지갑 잔액 ③ 그날 소진액을 함께 바꾼다.
    """
    now = _now(now)
    if not is_int(applied_amount) or not 1 <= applied_amount <= MAX_AMOUNT:  # 소수·bool·범위 밖은 원장·잔액·소진액 어디에도 닿기 전에 거절
        raise errors.InvalidRequest(errors=[{"pointer": "/applied_amount", "message": f"1 이상 {MAX_AMOUNT} 이하의 정수여야 합니다."}])
    policy = get_charge_policy(settings.BILLING_CHARGE_POLICY)
    amount = policy.amount_for(reaction_type, shares, applied_amount)
    if not is_int(amount) or not 0 <= amount <= applied_amount:  # 정책이 잘못된 값(음수·적용 금액 초과)을 돌려주는 것은 서버 쪽 결함이다
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
        return _duplicate(LedgerEntry.objects.get(reaction_ref=reaction_ref))


def _charged_on(day, **scope):
    """원장의 CHARGE 줄로 센 그 예산 일의 받은 포인트. `scope` 는 지갑(`wallet=`)이나 캠페인(`campaign_id=`)."""
    start = day_start(day)
    total = LedgerEntry.objects.filter(
        entry_type=EntryType.CHARGE, created_at__gte=start, created_at__lt=start + timedelta(days=1), **scope,
    ).aggregate(s=Sum("amount"))["s"] or 0
    return -total


def _wallet_view(owner_id, now):
    try:
        wallet = Wallet.objects.get(owner_id=owner_id)
    except Wallet.DoesNotExist:
        raise errors.NotFound("지갑을 찾을 수 없습니다.")
    day = budget_day_of(now)
    return WalletView(owner_id=owner_id, balance=wallet.balance, spent_today=_charged_on(day, wallet=wallet), budget_day=day, resets_at=next_reset(now))


def _cursor(before):
    """목록 커서(지갑 안의 순번 `seq`). 주소에서 온 값은 ASCII 숫자 10자리까지만 읽고, 형식이 틀린 값은 첫 쪽으로 본다(`²`·`①`도 `isdigit()` 은 참이다)."""
    if is_int(before):
        return before
    if isinstance(before, str) and before.isascii() and before.isdigit() and len(before) <= 10:
        return int(before)
    return None


def _ledger(owner_id, before, limit):
    limit = max(1, min(int(limit), 200))
    qs = LedgerEntry.objects.filter(wallet__owner_id=owner_id).order_by("-seq")
    before = _cursor(before)
    if before is not None:
        qs = qs.filter(seq__lt=before)
    rows = list(qs[: limit + 1])
    next_cursor = rows[limit - 1].seq if len(rows) > limit else None
    return [_entry_view(e) for e in rows[:limit]], next_cursor


def get_wallet(user, now=None):
    return _wallet_view(user.pk, _now(now))


def list_ledger(user, before=None, limit=50):
    """원장 내역(최신순). `before` 는 앞 쪽의 `next_cursor`(지갑 안의 순번 `seq`). 반환: (항목 목록, 다음 커서 또는 None)."""
    return _ledger(user.pk, before, limit)


def wallet_of(actor, owner_id, now=None):
    """관리자가 보는 광고주의 지갑(Step 3-1d). 광고주 화면의 `get_wallet` 과 같은 값. **지갑이 없으면 `None`**(가입 묶음을 거치지 않은 옛 계정 —
    화면은 "지갑 없음"으로 보이고 비활성화는 그대로 할 수 있다. 조회가 지급을 몰래 만들지 않는다)."""
    require_admin(actor)
    try:
        return _wallet_view(parse_uuid(owner_id, "지갑"), _now(now))
    except errors.NotFound:
        return None


def ledger_of(actor, owner_id, before=None, limit=50):
    """관리자가 보는 광고주의 원장(Step 3-1d). `list_ledger` 와 같은 쪽 나누기."""
    require_admin(actor)
    return _ledger(parse_uuid(owner_id, "지갑"), before, limit)


def balances(owner_ids):
    """여러 광고주의 잔액을 **질의 한 번**으로(결정 조립용). 지갑이 없으면 결과에 없다."""
    return dict(Wallet.objects.filter(owner_id__in=list(owner_ids)).values_list("owner_id", "balance"))


def spend_today(campaign_ids, now=None):
    """여러 캠페인의 오늘 소진액을 **질의 한 번**으로. 소진이 없으면 결과에 없다(0 으로 읽는다)."""
    day = budget_day_of(_now(now))
    return dict(CampaignSpend.objects.filter(campaign_id__in=list(campaign_ids), budget_day=day).values_list("campaign_id", "spent"))


def _spend_totals(campaign_ids, start_day, end_day, key):
    rows = (
        CampaignSpend.objects.filter(campaign_id__in=list(campaign_ids), budget_day__gte=start_day, budget_day__lt=end_day)
        .values(key).annotate(total=Sum("spent")).values_list(key, "total")
    )
    return dict(rows)


def spend_by_day(campaign_ids, start_day, end_day):
    """캠페인들의 예산 일별 소진액 합 `{날짜: 포인트}` 를 **질의 한 번**으로. `start_day` 포함, `end_day` 미포함. 소진이 없는 날은 결과에 없다(0 으로 읽는다)."""
    return _spend_totals(campaign_ids, start_day, end_day, "budget_day")


def spend_by_campaign(campaign_ids, start_day, end_day):
    """캠페인별 소진액 합 `{campaign_id: 포인트}`(`start_day` 포함, `end_day` 미포함) — **질의 한 번**. 소진이 없는 캠페인은 결과에 없다."""
    return _spend_totals(campaign_ids, start_day, end_day, "campaign_id")


def charged_amounts(reaction_refs):
    """반응 멱등 키(`reaction_ref`)별로 **실제로 받은** 포인트 `{키: 포인트}`. 과금되지 않은 키(과금 단위가 아닌 유형 등)는 결과에 없다.

    광고그룹처럼 소진액이 따로 쌓이지 않는 범위의 소진을 원장에서 읽을 때 쓴다. 한 번에 많은 키를 `IN` 에 넣지 않도록 나눠 조회한다.
    """
    found = {}
    for chunk in batched(reaction_refs, 500):
        for ref, amount in LedgerEntry.objects.filter(entry_type=EntryType.CHARGE, reaction_ref__in=chunk).values_list("reaction_ref", "amount"):
            found[ref] = -amount  # 원장의 과금은 음수다
    return found


def charge_entry_ids():
    """원장 `CHARGE` 항목 ID 를 훑는다(이벤트 누락 점검용 읽기). 큰 표를 한꺼번에 메모리에 올리지 않는다."""
    return LedgerEntry.objects.filter(entry_type=EntryType.CHARGE).values_list("entry_id", flat=True).iterator(chunk_size=2000)


def charge_refs_after(after=None, limit=2000):
    """원장 `CHARGE` 항목의 (entry_id, reaction_ref) 를 ID 순으로 한 묶음(`after` 다음부터). 큰 표를 한꺼번에 읽지 않고 이어 읽는다(구간 manifest 의 미해결 과금 찾기)."""
    rows = LedgerEntry.objects.filter(entry_type=EntryType.CHARGE)
    if after is not None:
        rows = rows.filter(entry_id__gt=after)
    return list(rows.order_by("entry_id").values_list("entry_id", "reaction_ref")[:limit])


def charge_entries(entry_ids):
    """원장 `CHARGE` 항목을 ID 로 읽는다(없는 ID 는 결과에 없다). 이벤트 백필이 원본 행에서 과금 이벤트를 다시 만들 때 쓴다."""
    return _charge_entries("entry_id__in", entry_ids)


def charge_entries_for(reaction_refs):
    """원장 `CHARGE` 항목을 반응 멱등 키(`reaction_ref`)로 읽는다(과금되지 않은 키는 결과에 없다). 구간 manifest 가 창 하나의 반응으로 과금 줄을 찾을 때 쓴다."""
    return _charge_entries("reaction_ref__in", reaction_refs)


def _charge_entries(lookup, keys):
    found = []
    for chunk in batched(keys, 500):  # 한 번에 많은 키를 IN 에 넣지 않는다
        for e in LedgerEntry.objects.filter(entry_type=EntryType.CHARGE, **{lookup: chunk}):
            found.append(ChargeEntryView(
                entry_id=e.entry_id, campaign_id=e.campaign_id, charge_policy=e.charge_policy, reaction_ref=e.reaction_ref, charged=-e.amount,
                shortfall=e.shortfall, created_at=e.created_at,
            ))
    return found


def recompute_spend():
    """원장의 CHARGE 줄로 `CampaignSpend` 를 처음부터 다시 만든다(예산 일 경계 설정을 바꾼 뒤 실행). 만든 행 수(받은 포인트가 있는 행)를 돌려준다.

    **과금과 함께 돌려도 안전하다**(MySQL 에서는 `atomic()` 만으로 다른 연결의 과금을 막지 못해, 한 트랜잭션에서 읽고 덮어쓰는 방식은 그 사이에 커밋된 과금을 잃는다).
    (캠페인, 예산 일)마다 따로 한 트랜잭션으로, **소진액 행을 잠근 뒤에** 원장 합계를 읽어 그 값으로 맞춘다:
    - 과금은 원장 줄을 넣은 뒤 같은 트랜잭션에서 소진액 행에 더한다. 이 행 잠금이 둘을 줄 세운다 — 과금이 먼저 커밋됐으면 재계산의 합계에 들어 있고,
      재계산이 먼저 잠갔으면 과금은 기다렸다가 재계산이 맞춘 값 위에 더한다(그 원장 줄은 아직 안 보이므로 이중으로 세지 않는다).
    - 키는 먼저 모은다(원장의 과금이 있는 (캠페인, 날) + 지금 있는 소진액 행 = 경계 설정이 바뀌기 전의 날도 포함). 재계산 도중 새로 생기는 (캠페인, 날)은
      그 과금이 스스로 쌓으므로 건드리지 않는다. 받은 포인트가 없는 행은 지운다(과금은 키로 갱신하고 없을 때만 만들므로 지워도 증가분을 잃지 않는다).
    """
    keys = {(campaign_id, budget_day_of(created_at)) for campaign_id, created_at in LedgerEntry.objects.filter(
        entry_type=EntryType.CHARGE, campaign_id__isnull=False, amount__lt=0,
    ).values_list("campaign_id", "created_at")}
    keys |= set(CampaignSpend.objects.values_list("campaign_id", "budget_day"))
    rows = 0
    for campaign_id, day in sorted(keys, key=lambda key: (str(key[0]), key[1])):
        with transaction.atomic():
            # 행을 얻는 것과 잠그는 것은 **한 문장**이다. 따로 하면 그 사이에 다른 재계산이 합계 0 인 행을 지워 `DoesNotExist` 로 중단된다
            # (예산 일 경계를 바꾸는 정상 절차에서도 이전 날짜 행을 두 재계산이 함께 만난다). 없으면 만들고, 그 행은 우리가 쥔다.
            spend, _ = CampaignSpend.objects.select_for_update().get_or_create(campaign_id=campaign_id, budget_day=day)
            # 잠근 **뒤에** 읽는다
            total = _charged_on(day, campaign_id=campaign_id)
            if total > 0:
                CampaignSpend.objects.filter(pk=spend.pk).update(spent=total)
                rows += 1
            else:
                spend.delete()
    return rows


class ConsistentReadUnavailable(RuntimeError):
    """정합성 점검을 일관된 읽기 스냅샷으로 할 수 없는 곳에서 불렀다(아래 `consistent_read`)."""


@contextmanager
def consistent_read(quiescent=False):
    """이 안의 모든 읽기가 **하나의 스냅샷**을 본다. 기본 격리 수준(`READ COMMITTED`)은 SELECT 마다 새 스냅샷이라, 점검이 여러 조회를 비교하는 동안
    정상 과금이 커밋되면 서로 다른 시점의 값을 비교해 거짓 불일치를 보고한다. 이 점검에만 `REPEATABLE READ` 를 쓴다(읽기만 하므로 잠금이 없고, 전역 설정은 그대로다).

    - **트랜잭션 밖**에서 부르면(운영 호출: 관리 명령, 부하 검사기) 다음 트랜잭션 하나만 `REPEATABLE READ` 로 열어 그 안에서 읽는다.
    - **이미 시작한 트랜잭션 안**에서는 격리 수준을 바꿀 수 없고(MySQL), 그 트랜잭션이 어떤 격리 수준으로 시작했는지도 **확인할 수 없다**
      (세션 기본값 `@@transaction_isolation` 은 `SET TRANSACTION` 으로 그 트랜잭션만 바꾼 경우를 알려 주지 않는다). `atomic()` 이라고 다른 연결의 커밋이 막히는 것도 아니다.
      그래서 **스냅샷을 보장할 수 없다고 거절한다**(`ConsistentReadUnavailable`) — 조용히 건너뛰지도, 추정해서 허용하지도 않는다.
    - `quiescent=True` 는 호출한 쪽이 **동시에 쓰는 연결이 없음을 보장**할 때(단일 연결 시험)만 쓴다. 보장은 호출한 쪽의 책임이고, 틀리면 거짓 불일치가 날 수 있다.
    """
    if connection.in_atomic_block:
        if quiescent:
            yield
            return
        raise ConsistentReadUnavailable(
            "정합성 점검은 일관된 읽기 스냅샷이 필요한데, 이미 시작한 트랜잭션 안에서는 그 트랜잭션의 격리 수준을 확인할 수 없어 보장할 수 없습니다. "
            "트랜잭션 밖에서 부르거나, 동시에 쓰는 연결이 없다면 quiescent=True 로 부르세요."
        )
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")  # 다음 트랜잭션 하나에만 적용된다
    with transaction.atomic():
        yield


def check_ledger(quiescent=False):
    """정합성 점검(한 읽기 스냅샷 안에서, 보장 조건은 `consistent_read`): 지갑마다 `잔액 == 원장 합계`, `seq` 가 1부터 빈틈없이 이어지고 `balance_after` 가 줄마다 이어지는지. 어긋난 곳의 설명 목록(깨끗하면 빈 목록)."""
    with consistent_read(quiescent):
        return _check_wallets() + _check_spend()


def _check_wallets():
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


def _check_spend():
    """일 소진액(`CampaignSpend`)이 원장의 CHARGE 합계와 같은지. 재계산·과금이 서로의 증가분을 잃으면 여기서 드러난다(지갑·원장은 맞아도 소진액만 어긋날 수 있다)."""
    expected = {}
    for campaign_id, created_at, amount in LedgerEntry.objects.filter(entry_type=EntryType.CHARGE, campaign_id__isnull=False, amount__lt=0).values_list("campaign_id", "created_at", "amount"):
        key = (campaign_id, budget_day_of(created_at))
        expected[key] = expected.get(key, 0) - amount
    stored = {(campaign_id, day): spent for campaign_id, day, spent in CampaignSpend.objects.values_list("campaign_id", "budget_day", "spent")}
    problems = []
    for key in sorted(expected.keys() | stored.keys(), key=lambda k: (str(k[0]), k[1])):
        if expected.get(key, 0) != stored.get(key, 0):
            problems.append(f"캠페인 {key[0]} {key[1]} 의 소진액 {stored.get(key, 0)} != 원장 합계 {expected.get(key, 0)}")
    return problems
