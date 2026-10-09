"""2-5 반응 처리: 규칙 체인 → 과금 → ACCEPTED/REJECTED. 재시작·중복 처리·자정 뒤 재처리에서도 과금은 한 번이고 예산 일은 접수 시각 기준이다."""
import io
import json
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from random import Random
from unittest import mock

from django.core.exceptions import ImproperlyConfigured  # noqa: F401
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings, tag

from billing import api as billing
from billing.models import CampaignSpend, LedgerEntry
from masters import api as masters
from records import api as records
from records.models import Decision, Reaction
from records.rules import UnknownRule
from serving_api.throttle import buckets
from tests.factories import DAY, NOW, SUBJECT, World


class ProcessingBase(TestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = records.decide(self.media, self.w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))  # 입찰 30, 노출 과금 단위
        self.assertIsNotNone(self.decision.chosen)

    def receive(self, rtype="IMPRESSION", decision_id=None, media_id=None, at=NOW, reaction_id=None):
        view, created = records.receive_reaction(
            media_id or self.media, decision_id or self.decision.decision_id, reaction_id or uuid.uuid4(), rtype, NOW, {"type": rtype}, now=at,
        )
        self.assertTrue(created)
        return view

    def process(self, view, now=NOW):
        return records.process_reaction(view.inbox_id, now=now)

    def new_decision(self, subject):
        return records.decide(self.media, self.w.slot.slot_id, subject_id=subject, now=NOW, rng=Random(1))

    def click(self, decision_id=None, at=NOW, viewer=None):
        """서버가 관측한 클릭(`GET /c/{token}`)을 수신함에 넣는다. 처리는 호출하는 쪽이 한다."""
        with override_settings(REACTION_PROCESS_ON_RECEIPT=False):
            records.observe_click(decision_id or self.decision.decision_id, viewer, now=at)
        return Reaction.objects.filter(decision_id=decision_id or self.decision.decision_id, source="server").order_by("-received_at").first()

    def row(self, view):
        return Reaction.objects.get(pk=view.inbox_id)

    def balance(self):
        return billing.get_wallet(self.w.adv, now=NOW).balance

    def charges(self):
        return LedgerEntry.objects.filter(entry_type="CHARGE").count()


@tag("security")
class RuleChainTests(ProcessingBase):
    def test_a_valid_report_in_the_billing_unit_is_accepted_and_charged_the_recorded_amount(self):
        view = self.receive("IMPRESSION")
        self.assertEqual(self.process(view), "ACCEPTED")
        row = self.row(view)
        self.assertEqual((row.status, row.reason_code, row.applied_rule, row.processed_at), ("ACCEPTED", None, None, NOW))
        entry = LedgerEntry.objects.get(entry_type="CHARGE")
        self.assertEqual((entry.amount, entry.reaction_ref, entry.charge_policy), (-30, f"{self.media}:{view.reaction_id}", "by-unit/v1"))
        self.assertEqual(self.balance(), 50_000 - 30)
        self.assertEqual(billing.spend_today([self.w.campaign.campaign_id], now=NOW), {self.w.campaign.campaign_id: 30})
        self.assertEqual(billing.check_ledger(), [])

    def test_the_amount_is_the_decisions_not_a_recomputation(self):
        """결정 뒤에 입찰·정책이 바뀌어도 과금액은 결정 때의 적용 금액이다."""
        self.w.api.add_bid(self.w.adv, self.w.group.ad_group_id, 99, expected_version=1, now=NOW)
        masters.add_policy_version(self.w.admin, self.w.slot.slot_id, 1, 2, 3, "정책 대폭 변경", expected_version=1)
        self.process(self.receive("IMPRESSION"))
        self.assertEqual(LedgerEntry.objects.get(entry_type="CHARGE").amount, -30)

    def test_a_type_other_than_the_billing_unit_is_accepted_but_not_charged(self):
        self.assertEqual(self.process(self.receive("IMPRESSION")), "ACCEPTED")  # 과금 단위(노출)는 과금된다
        self.assertEqual(self.process(self.click()), "ACCEPTED")
        self.assertEqual(self.process(self.receive("CONVERSION")), "ACCEPTED")
        self.assertEqual((self.charges(), self.balance(), CampaignSpend.objects.count()), (1, 50_000 - 30, 1))  # 클릭·전환은 인정만 되고 과금은 노출 한 번뿐

    def test_unknown_decision_is_rejected_and_kept(self):
        view = self.receive(decision_id=uuid.uuid4())
        self.assertEqual(self.process(view), "REJECTED")
        row = self.row(view)
        self.assertEqual((row.status, row.reason_code, row.applied_rule), ("REJECTED", "unknown_decision", "known-decision"))
        self.assertEqual((self.charges(), row.raw), (0, {"type": "IMPRESSION"}))  # 거부돼도 원문이 남는다

    def test_another_medias_decision_is_rejected(self):
        other = World()
        view = self.receive(media_id=other.slot.media_id)  # 다른 매체가 이 결정에 대해 보고
        self.assertEqual(self.process(view), "REJECTED")
        self.assertEqual((self.row(view).reason_code, self.row(view).applied_rule), ("media_mismatch", "same-media"))
        self.assertEqual(self.charges(), 0)

    def test_a_decision_without_an_ad_cannot_have_reactions(self):
        empty = World(with_creative=False)
        decision = records.decide(empty.slot.media_id, empty.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
        self.assertIsNone(decision.chosen)
        view = self.receive(media_id=empty.slot.media_id, decision_id=decision.decision_id)
        self.assertEqual(self.process(view), "REJECTED")
        self.assertEqual((self.row(view).reason_code, self.row(view).applied_rule), ("no_ad_shown", "ad-shown"))

    def test_the_second_report_of_the_same_type_is_a_duplicate_but_other_types_are_fine(self):
        first, second = self.receive("IMPRESSION"), self.receive("IMPRESSION")
        self.process(first)
        click = self.click()
        self.assertEqual([self.process(v) for v in (second, click)], ["REJECTED", "ACCEPTED"])
        self.assertEqual((self.row(second).reason_code, self.row(second).applied_rule), ("duplicate_type", "once-per-type"))
        self.assertEqual((self.charges(), self.balance()), (1, 50_000 - 30))  # 중복은 과금되지 않는다

    def test_a_rejected_duplicate_does_not_block_a_later_valid_type(self):
        self.process(self.receive("IMPRESSION"))
        self.process(self.receive("IMPRESSION"))
        self.assertEqual(self.process(self.click()), "ACCEPTED")

    def test_rules_come_from_settings_and_unknown_names_fail_loudly(self):
        view = self.receive(decision_id=uuid.uuid4())
        with override_settings(REACTION_RULES=("nonexistent",)), self.assertRaises(UnknownRule):
            self.process(view)
        self.assertEqual(self.row(view).status, "RECEIVED")  # 설정 오류로 반응을 거부하거나 인정하지 않는다
        with override_settings(REACTION_RULES=("once-per-type",)):  # 규칙을 빼도 근거 없는 보고는 인정하지 않는다(안전망)
            self.assertEqual(self.process(view), "REJECTED")
            self.assertEqual(self.row(view).applied_rule, "guard")
        self.assertEqual(self.charges(), 0)

    def test_ownership_is_enforced_whatever_the_rule_configuration(self):
        """교체 가능한 것은 정책(유형별 1회 등)이고, 결정의 존재·매체 소유·광고 유무는 규칙 설정과 무관한 필수 조건이다."""
        other = World()
        for rules in ((), ("once-per-type",), ("known-decision", "ad-shown"), ("same-media",)):
            with override_settings(REACTION_RULES=rules):
                view = self.receive("IMPRESSION", media_id=other.slot.media_id)  # 다른 매체가 이 결정으로 보고
                self.assertEqual(self.process(view), "REJECTED", rules)
                self.assertEqual((self.row(view).reason_code, self.charges(), self.balance()), ("media_mismatch", 0, 50_000), rules)
        with override_settings(REACTION_RULES=()):  # 규칙이 없어도 정당한 보고는 인정된다(안전망은 거부만 한다)
            self.assertEqual(self.process(self.receive("IMPRESSION")), "ACCEPTED")
        self.assertEqual(self.charges(), 1)

    def test_dropping_a_rule_by_configuration_really_changes_the_result(self):
        first, second = self.receive("IMPRESSION"), self.receive("IMPRESSION")
        self.assertEqual(self.process(first), "ACCEPTED")
        with override_settings(REACTION_RULES=("known-decision", "same-media", "ad-shown")):
            with self.assertRaises(Exception):  # 규칙은 빠졌지만 DB 안전망이 두 번째 인정을 막는다
                self.process(second)
        self.assertEqual((self.charges(), self.row(second).status), (1, "RECEIVED"))


@tag("security")
class AtomicityAndIdempotencyTests(ProcessingBase):
    def test_processing_twice_charges_once(self):
        view = self.receive()
        self.assertEqual((self.process(view), self.process(view)), ("ACCEPTED", None))
        self.assertEqual((self.charges(), self.balance()), (1, 50_000 - 30))

    def test_a_failure_after_the_charge_rolls_everything_back_and_the_retry_charges_once(self):
        view = self.receive()
        with mock.patch("records.processing._finish", side_effect=OperationalError("disk I/O error")), self.assertRaises(OperationalError):
            self.process(view)
        row = self.row(view)
        self.assertEqual((row.status, row.attempts, self.charges(), self.balance()), ("RECEIVED", 1, 0, 50_000))  # 과금도 되돌려졌다
        self.assertEqual(CampaignSpend.objects.count(), 0)
        self.assertEqual(self.process(view), "ACCEPTED")
        self.assertEqual((self.charges(), self.balance(), billing.check_ledger()), (1, 50_000 - 30, []))

    def test_a_charge_that_already_exists_is_not_repeated(self):
        """과금이 먼저 일어나 있고 상태만 못 바꾼 상황(다른 경로·수동 조치)에서도 같은 키로 한 번만 차감된다."""
        view = self.receive()
        billing.charge_for_reaction(
            self.decision.chosen.owner_id, self.decision.chosen.campaign_id, "IMPRESSION", "IMPRESSION", 30,
            f"{self.media}:{view.reaction_id}", now=NOW,
        )
        self.assertEqual(self.process(view), "ACCEPTED")
        self.assertEqual((self.charges(), self.balance()), (1, 50_000 - 30))

    def test_a_late_reprocess_after_midnight_keeps_the_received_day_and_time(self):
        """자정 뒤에 처리해도 예산 일·원장 시각은 처리 시각이 아니라 접수 시각(`received_at`) 기준이다."""
        received = NOW.replace(hour=23, minute=59, second=59)
        view = self.receive(at=received)
        late = received + timedelta(seconds=10)  # 다음 예산 일(UTC 자정 뒤)
        self.assertEqual(self.process(view, now=late), "ACCEPTED")
        campaign = self.w.campaign.campaign_id
        self.assertEqual(billing.spend_today([campaign], now=received), {campaign: 30})
        self.assertEqual(billing.spend_today([campaign], now=late), {})
        entry = LedgerEntry.objects.get(entry_type="CHARGE")
        self.assertEqual(entry.created_at, received)
        self.assertEqual(self.row(view).processed_at, late)

    def test_the_ref_is_stable_whenever_it_is_processed(self):
        view = self.receive()
        with mock.patch("records.processing._finish", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
            self.process(view, now=NOW)
        self.process(view, now=NOW + 3 * DAY)
        self.assertEqual(LedgerEntry.objects.get(entry_type="CHARGE").reaction_ref, f"{self.media}:{view.reaction_id}")

    def test_the_status_is_never_changed_again_once_processed(self):
        view = self.receive()
        self.process(view)
        with self.assertRaises(RuntimeError):
            from records.processing import _finish

            _finish(self.row(view), "REJECTED", NOW, {"v": 1}, reason="x", rule="x")
        self.assertEqual(self.row(view).status, "ACCEPTED")


@tag("security")
class QueueTests(ProcessingBase):
    def test_pending_is_oldest_first_and_limited(self):
        views = [self.receive(at=NOW + timedelta(seconds=i)) for i in range(5)]
        counts = records.process_pending(limit=2, now=NOW)
        self.assertEqual(sum(counts.values()), 2)
        self.assertEqual([self.row(v).status for v in views], ["ACCEPTED", "REJECTED", "RECEIVED", "RECEIVED", "RECEIVED"])  # 첫 건만 인정, 나머지는 중복

    def test_one_failure_does_not_block_the_others_and_stuck_ones_are_reported(self):
        bad = self.receive("IMPRESSION", at=NOW)
        others = [self.new_decision("0197a5c0-0000-7000-8000-00000000000%d" % i).decision_id for i in (1, 2)]
        good = [self.receive("IMPRESSION", decision_id=d, at=NOW + timedelta(seconds=i + 1)) for i, d in enumerate(others)]
        real = records.process_reaction

        def flaky(inbox_id, now=None):
            if inbox_id == bad.inbox_id:
                raise RuntimeError("poison")
            return real(inbox_id, now=now)

        with override_settings(REACTION_MAX_ATTEMPTS=3), mock.patch("records.processing.process_reaction", flaky):
            first = records.process_pending(now=NOW)
        self.assertEqual((first["failed"], first["accepted"]), (1, 2))
        self.assertEqual([self.row(v).status for v in good], ["ACCEPTED", "ACCEPTED"])
        # 실패한 반응은 횟수가 쌓이다가 한도에서 자동 처리 대상에서 빠진다(거부·삭제하지 않는다)
        with override_settings(REACTION_MAX_ATTEMPTS=3):
            Reaction.objects.filter(pk=bad.inbox_id).update(attempts=3)
            self.assertEqual(records.process_pending(now=NOW), {"accepted": 0, "rejected": 0, "pending": 0, "skipped": 0, "failed": 0})
            self.assertEqual(records.stuck_count(), 1)
            self.assertEqual(self.row(bad).status, "RECEIVED")
            self.assertEqual(records.reset_stuck(), 1)
            self.assertEqual(records.stuck_count(), 0)
            self.assertEqual(records.process_pending(now=NOW)["accepted"], 1)

    def test_failures_are_counted_on_the_row(self):
        view = self.receive()
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=RuntimeError("down")):
            self.assertEqual(records.process_pending(now=NOW)["failed"], 1)
        self.assertEqual(self.row(view).attempts, 1)

    def test_command_once_drains_and_reports(self):
        [self.receive("IMPRESSION"), self.receive("IMPRESSION"), self.receive("CLICK")]  # 중복 노출 하나, 매체가 보고한 클릭 하나는 거부된다
        out = io.StringIO()
        call_command("process_reactions", "--once", "--batch", "2", stdout=out)
        self.assertEqual(Reaction.objects.filter(status="RECEIVED").count(), 0)  # 배치(2)보다 많아도 한 번의 실행이 다 비운다
        self.assertIn("'accepted': 1", out.getvalue())
        self.assertIn("'rejected': 2", out.getvalue())
        self.assertIn("'pending': 0", out.getvalue())
        self.assertIn("stuck=0", out.getvalue())

    def test_command_loop_polls_until_interrupted(self):
        self.receive()
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise KeyboardInterrupt

        with mock.patch("records.management.commands.process_reactions.time.sleep", fake_sleep):
            call_command("process_reactions", "--interval", "0.5", stdout=io.StringIO())
        self.assertEqual(sleeps, [0.5, 0.5])
        self.assertEqual(Reaction.objects.get().status, "ACCEPTED")

    def test_command_can_revive_stuck_reactions(self):
        view = self.receive()
        Reaction.objects.filter(pk=view.inbox_id).update(attempts=99)
        out = io.StringIO()
        call_command("process_reactions", "--once", "--retry-stuck", stdout=out)
        self.assertIn("retried-stuck: 1", out.getvalue())
        self.assertEqual(self.row(view).status, "ACCEPTED")


@tag("security")
class CommandSafetyTests(ProcessingBase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command("process_reactions", *args, stdout=out)
        return out.getvalue()

    def test_invalid_options_are_rejected_before_anything_is_changed(self):
        view = self.receive()
        Reaction.objects.filter(pk=view.inbox_id).update(attempts=99)
        for args in (
            ("--once", "--batch", "0"), ("--once", "--batch", "-1"), ("--once", "--interval", "0"), ("--once", "--interval", "-1"),
            ("--once", "--interval", "nan"), ("--once", "--interval", "inf"),
        ):
            with self.assertRaises(CommandError, msg=args):
                self.run_command("--retry-stuck", *args)
            self.assertEqual(self.row(view).attempts, 99, args)  # --retry-stuck 이 먼저 실행되지 않았다
        self.assertEqual(self.row(view).status, "RECEIVED")

    def test_sigterm_finishes_the_current_reaction_and_stops_without_draining_the_queue(self):
        for i, kind in enumerate(("IMPRESSION", "CLICK", "CONVERSION", "IMPRESSION")):
            self.receive(kind, at=NOW + timedelta(seconds=i))
        handlers, real = {}, records.process_reaction

        def capture(signum, handler):
            handlers[signum] = handler
            return signal.SIG_DFL

        def term_during_first(inbox_id, now=None):
            if not handlers.get("fired"):
                handlers["fired"] = True
                handlers[signal.SIGTERM](signal.SIGTERM, None)  # 첫 반응을 처리하는 중에 SIGTERM
            return real(inbox_id, now=now)

        for batch in ("2", "1", "100"):
            Reaction.objects.update(status="RECEIVED", reason_code=None, applied_rule=None, processed_at=None, person_id=None, accepted_key=None, basis=None)
            handlers.clear()
            with mock.patch("records.management.commands.process_reactions.signal.signal", capture), \
                    mock.patch("records.processing.process_reaction", term_during_first):
                self.run_command("--batch", batch, "--interval", "0.01")
            done = Reaction.objects.exclude(status="RECEIVED").count()
            self.assertEqual(done, 1, f"batch={batch}: 현재 한 건만 끝내고 멈춘다")
            self.assertEqual(Reaction.objects.filter(status="RECEIVED").count(), 3)  # 남은 것은 RECEIVED 로 두고 재기동 뒤 이어서 처리

    def test_a_restart_resumes_what_the_stopped_run_left(self):
        decisions = [self.decision.decision_id] + [self.new_decision("0197a5c0-0000-7000-8000-00000000000%d" % i).decision_id for i in (1, 2)]
        views = [self.receive("IMPRESSION", decision_id=d, at=NOW + timedelta(seconds=i)) for i, d in enumerate(decisions)]
        handlers, real = {}, records.process_reaction

        def capture(signum, handler):
            handlers[signum] = handler
            return signal.SIG_DFL

        def term_after_first(inbox_id, now=None):
            result = real(inbox_id, now=now)
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return result

        with mock.patch("records.management.commands.process_reactions.signal.signal", capture), \
                mock.patch("records.processing.process_reaction", term_after_first):
            self.run_command("--batch", "1")
        self.assertEqual([self.row(v).status for v in views], ["ACCEPTED", "RECEIVED", "RECEIVED"])
        self.run_command("--once")  # 재기동
        self.assertEqual([self.row(v).status for v in views], ["ACCEPTED", "ACCEPTED", "ACCEPTED"])
        self.assertEqual((self.charges(), billing.check_ledger()), (3, []))

    def test_the_previous_signal_handler_is_restored(self):
        before = signal.getsignal(signal.SIGTERM)
        self.run_command("--once")
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)


@tag("security")
class ConcurrentProcessingTests(TransactionTestCase):
    def test_two_processors_at_once_charge_each_reaction_exactly_once(self):
        w = World()
        media = w.slot.media_id
        views = []
        for _ in range(6):  # 서로 다른 결정 6개 × 노출 하나씩
            d = records.decide(media, w.slot.slot_id, subject_id=SUBJECT, now=NOW, rng=Random(1))
            views.append(records.receive_reaction(media, d.decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW)[0])
        barrier, errors = threading.Barrier(2), []

        def worker():
            try:
                barrier.wait(timeout=10)
                for _ in range(300):
                    try:  # 처리뿐 아니라 대기열 조회도 테스트 DB(인메모리 공유 캐시)의 테이블 잠금을 받을 수 있다 → 같은 재시도 범위
                        records.process_pending(limit=100, now=NOW)
                        if not Reaction.objects.filter(status="RECEIVED").exists():
                            return
                    except OperationalError:
                        pass
                    time.sleep(0.003)
            except Exception as error:  # noqa: BLE001
                errors.append(repr(error))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        self.assertEqual(errors, [])
        # 재시도 사이에 일시적인 실패(테스트 DB 의 테이블 잠금)가 났더라도, 끝난 뒤에는 남김없이 처리되고 이중 과금이 없다
        records.process_pending(limit=100, now=NOW)
        self.assertEqual(Reaction.objects.filter(status="RECEIVED").count(), 0)
        self.assertEqual(Reaction.objects.filter(status="ACCEPTED").count(), 6)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 6)
        self.assertEqual(billing.get_wallet(w.adv, now=NOW).balance, 50_000 - 6 * 30)
        self.assertEqual(billing.check_ledger(), [])


@tag("security")
class InlineProcessingTests(TransactionTestCase):
    """수신 커밋 뒤 한 번 바로 처리해 본다. 접수 응답(스냅샷)은 처리 결과나 실패에 영향받지 않는다."""

    def setUp(self):
        buckets.reset()
        self.addCleanup(buckets.reset)
        self.w = World()
        self.media = self.w.slot.media_id
        self.key = masters.issue_media_key(self.w.admin, self.media).key
        patcher = mock.patch("records.services._now", lambda now=None: now or NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = Client()

    def decide(self):
        response = self.client.post(
            "/api/media/v1/decisions", data=json.dumps({"slot_id": str(self.w.slot.slot_id), "subject_id": str(uuid.uuid4())}),
            content_type="application/json", HTTP_X_MEDIA_KEY=self.key,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["decision_id"]

    def put(self, decision_id, rid, kind="IMPRESSION"):
        return self.client.put(
            f"/api/media/v1/decisions/{decision_id}/reactions/{rid}", data=json.dumps({"type": kind, "occurred_at": "2026-10-07T12:00:00Z"}),
            content_type="application/json", HTTP_X_MEDIA_KEY=self.key,
        )

    def get(self, decision_id, rid):
        return self.client.get(f"/api/media/v1/decisions/{decision_id}/reactions/{rid}", HTTP_X_MEDIA_KEY=self.key)

    def test_the_result_is_available_right_after_the_receipt_but_the_receipt_says_received(self):
        decision, rid = self.decide(), uuid.uuid4()
        response = self.put(decision, rid)
        self.assertEqual((response.status_code, response.json()["status"]), (201, "RECEIVED"))  # 접수 확인
        result = self.get(decision, rid).json()
        self.assertEqual((result["status"], result["reason_code"]), ("ACCEPTED", None))
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 1)
        self.assertEqual(self.put(decision, rid).json()["status"], "ACCEPTED")  # 재전송(200)은 지금 상태를 돌려준다
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 1)

    def test_unknown_decision_is_rejected_and_visible_to_the_reporter(self):
        decision, rid = uuid.uuid4(), uuid.uuid4()
        self.assertEqual(self.put(decision, rid).status_code, 201)
        body = self.get(decision, rid).json()
        self.assertEqual((body["status"], body["reason_code"]), ("REJECTED", "unknown_decision"))

    def test_a_processing_failure_never_changes_the_receipt(self):
        decision, rid = self.decide(), uuid.uuid4()
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=RuntimeError("billing down")):
            response = self.put(decision, rid)
        self.assertEqual((response.status_code, response.json()["status"]), (201, "RECEIVED"))
        self.assertEqual(Reaction.objects.get(reaction_id=rid).status, "RECEIVED")  # 접수는 그대로, 재처리 대기
        self.assertEqual(records.process_pending(now=NOW)["accepted"], 1)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="CHARGE").count(), 1)

    def test_inline_processing_can_be_switched_off(self):
        decision, rid = self.decide(), uuid.uuid4()
        with override_settings(REACTION_PROCESS_ON_RECEIPT=False):
            self.put(decision, rid)
        self.assertEqual(Reaction.objects.get(reaction_id=rid).status, "RECEIVED")
