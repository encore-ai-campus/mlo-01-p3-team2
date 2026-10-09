import random
import uuid
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DataError, IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from billing import api
from billing.models import LedgerEntry, Wallet
from foundation.errors import Forbidden, InvalidRequest, NotFound
from foundation.models import AppendOnlyError, AuditLog, User
from tests.factories import NOW, PW, make_admin, make_advertiser


def funded(points=None):
    adv = make_advertiser()
    if points is not None:
        with override_settings(SIGNUP_GRANT_POINTS=points):
            api.grant_signup(adv, now=NOW)
    else:
        api.grant_signup(adv, now=NOW)
    return adv


def charge(adv, amount, ref, campaign=None, now=NOW, rtype="IMPRESSION", unit="IMPRESSION"):
    return api.charge_for_reaction(adv.pk, campaign or uuid.uuid4(), rtype, unit, amount, ref, now=now)


class SignupGrantTests(TestCase):
    def test_signup_grants_configured_points_once(self):
        adv = make_advertiser()
        entry = api.grant_signup(adv, now=NOW)
        self.assertEqual((entry.entry_type, entry.amount, entry.balance_after), ("SIGNUP_GRANT", 50_000, 50_000))  # 기본값 50,000
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 50_000)
        again = api.grant_signup(adv, now=NOW)  # 재호출은 변화 없음
        self.assertEqual(again.entry_id, entry.entry_id)
        self.assertEqual(LedgerEntry.objects.filter(wallet__owner=adv).count(), 1)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 50_000)

    def test_grant_amount_is_a_setting_and_zero_means_no_grant(self):
        with override_settings(SIGNUP_GRANT_POINTS=1234):
            self.assertEqual(api.grant_signup(make_advertiser(), now=NOW).amount, 1234)
        zero = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=0):
            self.assertIsNone(api.grant_signup(zero, now=NOW))
        self.assertEqual(api.get_wallet(zero, now=NOW).balance, 0)  # 지갑은 만들어지고 지급은 없다

    def test_only_advertisers_have_wallets(self):
        with self.assertRaises(Forbidden):
            api.grant_signup(make_admin(), now=NOW)

    def post_signup(self, client=None, username="ad_wallet1"):
        client = client or Client()
        return client.post(reverse("signup"), {"username": username, "password": PW, "password_confirm": PW, "nickname": "홍길동", "class_label": "1반"}, REMOTE_ADDR="10.9.0.1")

    def test_signup_flow_creates_wallet_with_points_and_audit(self):
        self.assertEqual(self.post_signup().status_code, 302)
        user = User.objects.get(username="ad_wallet1")
        self.assertEqual(api.get_wallet(user, now=NOW).balance, 50_000)
        actions = list(AuditLog.objects.values_list("action", flat=True))
        self.assertIn("account.signup", actions)
        self.assertIn("billing.signup_grant", actions)

    def test_signup_and_grant_same_transaction(self):
        """지급이 실패하면 사용자도, 가입 감사 기록도 남지 않는다."""
        client = Client(raise_request_exception=False)
        with mock.patch("console.views.auth.grant_signup", side_effect=RuntimeError("boom")):
            response = self.post_signup(client)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(User.objects.filter(username="ad_wallet1").exists())
        self.assertFalse(AuditLog.objects.filter(action="account.signup").exists())
        self.assertEqual(self.post_signup(username="ad_wallet1").status_code, 302)  # 같은 아이디로 다시 가입할 수 있다


@tag("security")
class LedgerIntegrityTests(TestCase):
    def test_balance_equals_ledger_sum_after_any_sequence(self):
        rng = random.Random(20261007)
        users = [funded(rng.choice([0, 100, 5_000, 50_000])) for _ in range(3)]
        admin = make_admin()
        for i in range(120):
            adv = rng.choice(users)
            kind = rng.choice(["charge", "charge", "adjust_up", "adjust_down", "dup"])
            wallet_balance = api.get_wallet(adv, now=NOW).balance
            if kind == "charge":
                charge(adv, rng.randint(1, 8_000), f"ref-{i}", now=NOW)
            elif kind == "dup":
                charge(adv, 77, "dup-ref", now=NOW)  # 같은 키 반복
            elif kind == "adjust_up":
                api.adjust(admin, adv.pk, rng.randint(1, 3_000), "보너스", now=NOW)
            elif wallet_balance:
                api.adjust(admin, adv.pk, -rng.randint(1, wallet_balance), "회수", now=NOW)
            self.assertEqual(api.check_ledger(quiescent=True), [], (i, kind))
        self.assertEqual(sum(w.balance for w in Wallet.objects.all()), sum(e.amount for e in LedgerEntry.objects.all()))

    def test_balance_never_below_zero(self):
        adv = funded(100)
        first = charge(adv, 250, "r1")
        self.assertEqual((first.charged, first.shortfall, first.entry.amount, first.entry.balance_after), (100, 150, -100, 0))
        second = charge(adv, 40, "r2")  # 잔액 0: 0 을 받고 부족분을 기록한다
        self.assertEqual((second.charged, second.shortfall, second.entry.amount), (0, 40, 0))
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 0)
        self.assertEqual(api.check_ledger(quiescent=True), [])
        # DB 가 직접 쓰기도 거부한다. 거부 방식은 DB 마다 다르다: MySQL 은 부호 없는 열이라 범위 오류(DataError), 그 밖에는 CHECK(IntegrityError)
        with self.assertRaises((IntegrityError, DataError)), transaction.atomic():
            Wallet.objects.filter(owner=adv).update(balance=-1)
        self.assertEqual(Wallet.objects.get(owner=adv).balance, 0)  # 어느 쪽이든 값은 그대로다

    def test_ledger_is_append_only_and_cannot_be_overwritten(self):
        adv = funded(500)
        row = LedgerEntry.objects.get(wallet__owner=adv)
        row.amount = 999_999
        with self.assertRaises(AppendOnlyError):
            row.save()
        with self.assertRaises(AppendOnlyError):
            row.delete()
        with self.assertRaises(AppendOnlyError):
            LedgerEntry.objects.filter(pk=row.pk).update(amount=1)
        with self.assertRaises(AppendOnlyError):
            LedgerEntry.objects.filter(wallet__owner=adv).delete()
        clone = LedgerEntry(pk=row.pk, wallet=row.wallet, seq=row.seq, entry_type="ADMIN_ADJUST", amount=5, balance_after=5)
        with self.assertRaises((IntegrityError, AppendOnlyError)), transaction.atomic():
            clone.save()
        with self.assertRaises(AppendOnlyError):
            LedgerEntry.objects.bulk_create([clone], update_conflicts=True, update_fields=["amount"], unique_fields=["entry_id"])
        self.assertEqual(LedgerEntry.objects.get(pk=row.pk).amount, 500)

    def test_ledger_db_constraints(self):
        adv = funded(500)
        wallet = Wallet.objects.get(owner=adv)

        seqs = iter(range(100, 200))  # 제약 하나만 시험하도록 seq 는 매번 새 값(NOT NULL·유일 제약에 걸려 우연히 통과하지 않게)

        def attempt(**kw):
            values = dict(wallet=wallet, seq=next(seqs), entry_type="ADMIN_ADJUST", amount=5, balance_after=5)
            values.update(kw)
            with self.assertRaises(IntegrityError, msg=kw), transaction.atomic():
                LedgerEntry.objects.create(**values)

        attempt(entry_type="CHARGE", amount=5, reaction_ref="x")  # 과금은 −(또는 0)
        attempt(entry_type="TOPUP", amount=-5)  # 충전은 +
        attempt(entry_type="SIGNUP_GRANT", amount=-5)
        attempt(entry_type="SIGNUP_GRANT", amount=5)  # 지갑당 가입 지급은 한 번(이미 있음)
        attempt(entry_type="ADMIN_ADJUST", amount=0)
        attempt(entry_type="ADMIN_ADJUST", amount=5, reaction_ref="x")  # 반응 키는 과금에만
        attempt(entry_type="ADMIN_ADJUST", amount=2**53)
        LedgerEntry.objects.create(wallet=wallet, seq=next(seqs), entry_type="CHARGE", amount=0, balance_after=500, reaction_ref="ok-ref")
        attempt(entry_type="CHARGE", amount=-1, reaction_ref="ok-ref")  # 같은 반응 키로 두 번 과금 불가(DB)

    def test_check_ledger_detects_tampering(self):
        adv = funded(500)
        charge(adv, 100, "r1")
        self.assertEqual(api.check_ledger(quiescent=True), [])
        call_command("check_ledger", quiescent=True)  # 깨끗하면 정상 종료
        with connection.cursor() as cur:  # ORM 우회(추가 전용 가드는 ORM 경로만 막는다): 운영자 실수·DB 직접 수정 모사
            cur.execute("UPDATE billing_wallet SET balance = balance + 5")
        problems = api.check_ledger(quiescent=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("잔액", problems[0])
        with self.assertRaises(CommandError):
            call_command("check_ledger", quiescent=True)
        with connection.cursor() as cur:
            cur.execute("UPDATE billing_wallet SET balance = balance - 5")
            cur.execute("UPDATE billing_ledger_entry SET balance_after = balance_after + 1 WHERE entry_type = 'CHARGE'")
        self.assertTrue(any("balance_after" in p for p in api.check_ledger(quiescent=True)))


@tag("security")
class LedgerSequenceTests(TestCase):
    """원장 순서는 **지갑 안의 `seq`**(1부터 빈틈없이)다. 자동 증가 PK 에 기대지 않는다(설계 §4, PK 규칙)."""

    def seqs(self, adv):
        return list(LedgerEntry.objects.filter(wallet__owner=adv).order_by("seq").values_list("seq", flat=True))

    def test_seq_runs_from_one_without_gaps_and_per_wallet(self):
        a, b, admin = funded(1000), funded(1000), make_admin()
        charge(a, 10, "a1")
        api.adjust(admin, a.pk, 5, "보너스", now=NOW)
        charge(b, 10, "b1")
        charge(a, 10, "a2")
        self.assertEqual(self.seqs(a), [1, 2, 3, 4])  # 지급·과금·조정·과금
        self.assertEqual(self.seqs(b), [1, 2])  # 다른 지갑의 줄이 번호를 건드리지 않는다
        self.assertEqual(api.check_ledger(quiescent=True), [])

    def test_a_duplicate_charge_does_not_consume_a_seq(self):
        adv = funded(1000)
        charge(adv, 10, "same")
        charge(adv, 10, "same")  # 멱등: 줄이 늘지 않는다
        self.assertEqual(self.seqs(adv), [1, 2])

    def test_db_rejects_a_duplicate_or_non_positive_seq(self):
        adv = funded(1000)
        wallet = Wallet.objects.get(owner=adv)
        for seq in (1, 0):
            with self.assertRaises(IntegrityError, msg=seq), transaction.atomic():
                LedgerEntry.objects.create(wallet=wallet, seq=seq, entry_type="ADMIN_ADJUST", amount=5, balance_after=5)

    def test_check_ledger_detects_a_gap_in_seq(self):
        adv = funded(1000)
        charge(adv, 10, "r1")
        charge(adv, 10, "r2")
        self.assertEqual(api.check_ledger(quiescent=True), [])
        with connection.cursor() as cur:  # 가운데 줄의 번호를 비운다(ORM 우회)
            cur.execute("UPDATE billing_ledger_entry SET seq = 7 WHERE seq = 2")
        problems = api.check_ledger(quiescent=True)
        self.assertTrue(any("seq" in p for p in problems), problems)

    def test_list_ledger_cursor_is_the_seq(self):
        adv = funded(1000)
        for i in range(4):
            charge(adv, 10, f"c{i}")
        page, cursor = api.list_ledger(adv, limit=2)
        self.assertEqual(cursor, 4)  # 이 쪽의 가장 오래된 줄의 seq
        rest, cursor = api.list_ledger(adv, before=cursor, limit=5)
        self.assertEqual((len(page), len(rest), cursor), (2, 3, None))
        self.assertEqual([e.entry_type for e in rest][-1], "SIGNUP_GRANT")


@tag("security")
class AdjustTests(TestCase):
    def test_adjust_requires_admin_note_and_audited(self):
        adv, admin = funded(1000), make_admin()
        for actor in (adv, None, make_advertiser()):
            with self.assertRaises(Forbidden):
                api.adjust(actor, adv.pk, 10, "사유", now=NOW)
        for amount, note in ((10, ""), (10, " "), (0, "사유"), (True, "사유"), (1.5, "사유"), (2**53 + 1, "사유"), (-1001, "너무 많이 회수")):
            with self.assertRaises(InvalidRequest, msg=(amount, note)):
                api.adjust(admin, adv.pk, amount, note, now=NOW)
        with self.assertRaises(NotFound):
            api.adjust(admin, uuid.uuid4(), 10, "없는 지갑", now=NOW)
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 1000)  # 실패한 시도는 흔적이 없다
        entry = api.adjust(admin, adv.pk, -300, "환불", now=NOW)
        self.assertEqual((entry.entry_type, entry.amount, entry.balance_after, entry.note), ("ADMIN_ADJUST", -300, 700, "환불"))
        log = AuditLog.objects.get(action="billing.adjusted")
        self.assertEqual((log.actor_id, log.detail["amount"], log.detail["note"], log.detail["balance_after"]), (admin.pk, -300, "환불", 700))
        api.adjust(admin, adv.pk, -700, "전액 회수", now=NOW)  # 정확히 0 까지는 가능
        self.assertEqual(api.get_wallet(adv, now=NOW).balance, 0)


class LedgerListingTests(TestCase):
    def test_list_ledger_newest_first_with_cursor_and_isolation(self):
        adv, other = funded(1000), funded(1000)
        for i in range(6):
            charge(adv, 10, f"r{i}")
        charge(other, 10, "other-ref")
        seen, cursor = [], None
        for _ in range(5):
            page, cursor = api.list_ledger(adv, before=cursor, limit=3)
            seen += page
            if cursor is None:
                break
        self.assertEqual(len(seen), 7)  # 지급 1 + 과금 6, 다른 광고주의 것은 없다
        self.assertEqual(seen[-1].entry_type, "SIGNUP_GRANT")  # 최신순
        self.assertEqual([e.balance_after for e in seen], [940, 950, 960, 970, 980, 990, 1000])
        self.assertEqual(len({e.entry_id for e in seen}), 7)
        self.assertEqual(api.list_ledger(make_advertiser())[0], [])  # 지갑 없는 사용자는 빈 목록
