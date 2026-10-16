"""반응 처리 현황(Step 6-3c·관리자 첫 화면 카드 6-3i, 설계 §10 "반응 처리 현황 노출", §7-9 "처리 대기 건수를 로그로 노출").

리팩터링 세션 검토 O2: 처리하지 못한 반응(stuck — 과금이 안 된다)이 보이지 않았다. 처리기는 처리한 것이 있을 때만 찍어서 멈춘 상태와 한가한 상태가 똑같이 조용했고,
stuck 으로 넘어가는 순간도 남지 않았다.
"""
import io
import re
import uuid
from datetime import timedelta
from random import Random
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings, tag
from django.urls import reverse

from records import api as records
from records.models import Reaction
from tests.support.factories import NOW, SUBJECT, World, make_admin
from tests.support.cases import Cases

OTHER = "0197a5c0-0000-7000-8000-000000000002"


@override_settings(REACTION_PROCESS_ON_RECEIPT=False)
class InboxBase(TestCase):
    def setUp(self):
        self.w = World()
        self.media = self.w.slot.media_id
        self.decision = self.decide(SUBJECT)

    def decide(self, subject):
        return records.decide(self.media, self.w.slot.slot_id, subject_id=subject, now=NOW, rng=Random(1))

    def receive(self, seconds, decision=None):
        view, _ = records.receive_reaction(self.media, (decision or self.decision).decision_id, uuid.uuid4(), "IMPRESSION", NOW, {}, now=NOW + timedelta(seconds=seconds))
        return view.inbox_id

    def set(self, inbox_id, **fields):
        Reaction.objects.filter(pk=inbox_id).update(**fields)


@tag("security")
class InboxStatusTests(Cases, InboxBase):
    def case_counts_are_disjoint_and_the_oldest_wait_leaves_out_stuck_reactions(self):
        stuck = self.receive(0)
        self.set(stuck, attempts=settings.REACTION_MAX_ATTEMPTS, checked_at=NOW + timedelta(seconds=5))  # 보류된 적이 있어도 stuck 이다(보류로 세지 않는다)
        held = self.receive(20)
        self.set(held, checked_at=NOW + timedelta(seconds=25))
        self.receive(30)  # 아직 확인하지 않은 것
        other = self.decide(OTHER)
        self.assertEqual(records.process_reaction(self.receive(40, other), now=NOW), "ACCEPTED")  # 끝난 반응은 세지 않는다
        self.assertEqual(records.inbox_status(now=NOW + timedelta(seconds=100)), {"received": 3, "held": 1, "stuck": 1, "oldest_age_seconds": 80.0})

    def case_an_empty_inbox(self):
        self.assertEqual(records.inbox_status(now=NOW), {"received": 0, "held": 0, "stuck": 0, "oldest_age_seconds": None})

    def case_the_moment_a_reaction_becomes_stuck_is_logged_once(self):
        inbox_id = self.receive(0)
        self.set(inbox_id, attempts=settings.REACTION_MAX_ATTEMPTS - 1)
        with mock.patch("records.processing.billing.charge_for_reaction", side_effect=RuntimeError("billing down")):
            with self.assertLogs("records.processing", "ERROR") as logs:
                records.process_pending(now=NOW)
            self.assertEqual(len([line for line in logs.output if "stuck" in line and str(inbox_id) in line]), 1)
            with self.assertNoLogs("records.processing", "ERROR"), self.assertRaises(RuntimeError):  # 이미 stuck 인 반응이 또 실패해도 다시 남기지 않는다
                records.process_reaction(inbox_id, now=NOW)
        self.assertEqual(records.inbox_status(now=NOW)["stuck"], 1)

    def case_a_hold_is_logged_at_debug_with_its_rule_and_reason(self):
        self.receive(0)
        later = self.receive(1)  # 먼저 접수된 같은 유형이 끝나길 기다린다
        with self.assertLogs("records.processing", "DEBUG") as logs:
            self.assertEqual(records.process_reaction(later, now=NOW), "PENDING")
        self.assertTrue(any(f"inbox={later} rule=once-per-type reason=duplicate_type" in line for line in logs.output), logs.output)

    def test_inbox_status(self):
        self.run_cases()


@tag("security")
class ProcessReactionsStatusOutputTests(Cases, InboxBase):
    def case_status_prints_the_inbox_status_and_processes_nothing(self):
        inbox_id = self.receive(0)
        out = io.StringIO()
        call_command("process_reactions", "--status", stdout=out)
        self.assertEqual(out.getvalue().strip(), str(records.inbox_status()))  # 시각 없이 그대로(감시가 읽는다)
        self.assertEqual(Reaction.objects.get(pk=inbox_id).status, "RECEIVED")

    def case_an_idle_processor_reports_at_start_when_stuck_changes_and_every_heartbeat(self):
        """한가해도 조용하지 않다: 시작 직후, stuck 이 바뀌면 바로, 그 밖에는 60초마다. 그 사이에는 찍지 않는다."""
        clock = [0.0]
        steps = iter([(30, False), (31, False), (1, False), (1, True)])  # 0(시작) → 30(조용) → 61(주기) → 62(조용 — 주기 기준이 61 로 옮겨 갔다) → 63(stuck 변화)

        def sleep(_):
            step, make_stuck = next(steps, (None, False))
            if step is None:
                raise KeyboardInterrupt
            if make_stuck:
                self.set(self.receive(0), attempts=settings.REACTION_MAX_ATTEMPTS)  # 다른 처리기가 실패를 겪었다
            clock[0] += step

        out = io.StringIO()
        with mock.patch("records.management.commands.process_reactions.time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)):
            call_command("process_reactions", stdout=out)
        idle = [line for line in out.getvalue().splitlines() if " idle " in line]
        self.assertEqual(len(idle), 3, out.getvalue())
        self.assertEqual([("'stuck': 1" in line) for line in idle], [False, False, True])

    def test_process_reactions_status_output(self):
        self.run_cases()


@tag("security")
class AdminIndexInboxCardTests(Cases, InboxBase):
    """6-3i: 로그를 보지 않는 운영자도 관리자 첫 화면에서 stuck(과금되지 않은 반응)과 처리기 멈춤을 본다."""

    def card(self):
        self.client.force_login(make_admin())
        html = self.client.get(reverse("admin:index")).content.decode()
        return {th.split("(")[0]: td for th, td in re.findall(r'<th scope="row">([^<]*)</th><td>(.*?)</td>', html)}, html

    def case_the_card_shows_each_count_and_flags_stuck_reactions(self):
        for seconds in (0, 1):
            self.set(self.receive(seconds), attempts=settings.REACTION_MAX_ATTEMPTS)
        self.set(self.receive(2), checked_at=NOW)
        self.receive(3)
        rows, _ = self.card()
        self.assertEqual((rows["대기"], rows["보류"]), ("4", "1"))
        self.assertEqual(rows["stuck"], "<strong>2 — 과금되지 않은 반응이 있습니다</strong>")
        self.assertRegex(rows["가장 오래된 대기"], r"^\d+초$")

    def case_an_empty_inbox_shows_no_alarm(self):
        rows, html = self.card()
        self.assertEqual((rows["대기"], rows["보류"], rows["stuck"], rows["가장 오래된 대기"]), ("0", "0", "0", "없음"))
        self.assertNotIn("과금되지 않은 반응이 있습니다", html)

    def test_admin_index_inbox_card(self):
        self.run_cases()
