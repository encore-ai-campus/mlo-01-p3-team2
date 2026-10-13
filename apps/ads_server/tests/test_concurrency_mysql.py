"""DB-1c: MySQL 의 행 잠금·유일 제약 아래에서 **정상 경쟁이 오류 없이** 끝난다 — 스레드마다 실제 연결 하나, 재시도 없음.

정상 경쟁에서 오류(특히 교착 1213·잠금 초과 1205)가 나면 안 되므로 재시도하지 않고 오류를 그대로 드러낸다. 이 파일의 시험은 `scripts/` 의 반복 실행(수십 회)에서도 무실패여야 한다.
"""
import uuid
from random import Random

from django.test import TransactionTestCase, override_settings, tag

from billing import api as billing
from billing.models import LedgerEntry
from campaigns import api as campaigns
from campaigns.models import ReviewRequest
from records import api as records
from records.models import Reaction
from tests.concurrency import run_together
from tests.factories import NOW, SUBJECT, World, make_admin, make_advertiser


@tag("security")
class WalletConcurrencyTests(TransactionTestCase):
    def test_simultaneous_signup_grants_make_exactly_one_grant(self):
        adv = make_advertiser()
        with override_settings(SIGNUP_GRANT_POINTS=500):
            results, errors = run_together([lambda: billing.grant_signup(adv, now=NOW)] * 6)
        self.assertEqual(errors, [])
        self.assertEqual(LedgerEntry.objects.filter(entry_type="SIGNUP_GRANT").count(), 1)
        self.assertEqual(billing.get_wallet(adv, now=NOW).balance, 500)
        self.assertEqual(billing.check_ledger(), [])

    def test_charges_adjustments_and_reads_on_one_wallet_keep_seq_balance_and_spend_consistent(self):
        adv, admin, camp = make_advertiser(), make_admin(), uuid.uuid4()
        with override_settings(SIGNUP_GRANT_POINTS=10_000):
            billing.grant_signup(adv, now=NOW)

        def charges(n):
            return lambda: [billing.charge_for_reaction(adv.pk, camp, "IMPRESSION", "IMPRESSION", 10, f"w{n}-{i}", now=NOW) for i in range(4)]

        def adjustments():
            return [billing.adjust(admin, adv.pk, 7, "보정", now=NOW) for _ in range(4)]

        results, errors = run_together([charges(0), charges(1), charges(2), adjustments, adjustments, lambda: [billing.get_wallet(adv, now=NOW) for _ in range(8)]])
        self.assertEqual(errors, [])
        seqs = list(LedgerEntry.objects.filter(wallet__owner=adv).order_by("seq").values_list("seq", flat=True))
        self.assertEqual(seqs, list(range(1, 1 + 1 + 12 + 8)))  # 지급 1 + 과금 12 + 조정 8, 빈틈·중복 없음
        self.assertEqual(billing.get_wallet(adv, now=NOW).balance, 10_000 - 120 + 56)
        self.assertEqual(billing.check_ledger(), [])  # 지갑·원장·일 소진액이 모두 맞다

    def test_charges_on_different_wallets_and_a_recompute_all_finish_without_errors(self):
        advertisers = [make_advertiser() for _ in range(3)]
        campaigns_ = [uuid.uuid4() for _ in advertisers]
        for adv in advertisers:
            with override_settings(SIGNUP_GRANT_POINTS=1_000):
                billing.grant_signup(adv, now=NOW)

        def charges(adv, camp, n):
            return lambda: [billing.charge_for_reaction(adv.pk, camp, "IMPRESSION", "IMPRESSION", 5, f"a{n}-{i}", now=NOW) for i in range(6)]

        jobs = [charges(adv, camp, n) for n, (adv, camp) in enumerate(zip(advertisers, campaigns_))] + [billing.recompute_spend, billing.recompute_spend]
        _, errors = run_together(jobs)
        self.assertEqual(errors, [])
        self.assertEqual(billing.check_ledger(), [])  # 재계산이 과금과 겹쳐도 소진액이 원장 합계와 같다


@tag("security")
class CampaignConcurrencyTests(TransactionTestCase):
    def test_simultaneous_review_requests_leave_one_open_and_the_rest_get_a_clear_answer(self):
        w = World()

        campaigns.suspend_campaign(w.admin, w.campaign.campaign_id, "점검", now=NOW)
        results, errors = run_together([lambda: campaigns.create_review_request(w.adv, w.campaign.campaign_id, "풀어 주세요", now=NOW)] * 5)
        outcomes = sorted(type(e).__name__ for e in errors) + ["ok"] * sum(r is not None for r in results)
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(set(outcomes) - {"ok"}, {"ReviewPending"}, outcomes)  # 진 쪽은 '이미 요청 중' 안내다
        self.assertEqual(ReviewRequest.objects.filter(campaign_id=w.campaign.campaign_id, status="OPEN").count(), 1)


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
@tag("security")
class ReceiptAndJudgmentConcurrencyTests(TransactionTestCase):
    """접수(결정 행 잠금)·판정(잠금 지나가기·반응 행·지갑)이 섞여도 교착·잠금 초과 없이 끝나고 불변식이 맞다."""

    def test_receipts_clicks_and_two_processors_on_a_few_decisions_finish_cleanly(self):
        w = World(unit="CLICK")
        media = w.slot.media_id
        people = [SUBJECT, "0197a5c0-0000-7000-8000-0000000000a1", "0197a5c0-0000-7000-8000-0000000000b2"]
        decisions = [records.decide(media, w.slot.slot_id, subject_id=p, now=NOW, rng=Random(1)) for p in people]

        def reporter(decision):
            def work():
                for kind in ("IMPRESSION", "IMPRESSION", "CONVERSION"):  # 같은 유형이 겹치게
                    records.receive_reaction(media, decision.decision_id, uuid.uuid4(), kind, NOW, {}, now=NOW)
                records.observe_click(decision.decision_id, None, now=NOW)

            return work

        def processor():
            for _ in range(30):
                counts = records.process_pending(limit=50, now=NOW)
                if counts["failed"] or counts["transient"]:
                    raise AssertionError(f"처리 중 실패/일시 오류: {counts}")
            return None

        _, errors = run_together([reporter(d) for d in decisions] + [processor, processor])
        self.assertEqual(errors, [])
        # 남은 보류(먼저 접수된 같은 유형을 기다린 것)가 풀릴 때까지 돌린다
        for _ in range(10):
            records.process_pending(limit=100, now=NOW)
            if not Reaction.objects.filter(status="RECEIVED", type__in=["IMPRESSION", "CLICK"]).exists():
                break
        for decision in decisions:
            rows = Reaction.objects.filter(decision_id=decision.decision_id, type="IMPRESSION")
            self.assertEqual(sorted(rows.values_list("status", flat=True)), ["ACCEPTED", "REJECTED"])
        self.assertEqual(billing.check_ledger(), [])
        self.assertFalse(Reaction.objects.filter(status="RECEIVED", attempts__gt=0).exists())
