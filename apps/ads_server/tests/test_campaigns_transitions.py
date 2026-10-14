import re
from pathlib import Path

from django.test import TestCase, tag

from campaigns import transitions as tr
from campaigns.errors import CampaignEnded, CampaignSuspended, InvalidTransition
from campaigns.models import Campaign
from tests.factories import DAY, NOW, make_advertiser

ALL = ("ACTIVE", "PAUSED", "SUSPENDED", "ENDED")
EXPECTED = {
    "pause": ({"ACTIVE"}, "PAUSED", "advertiser"),
    "resume": ({"PAUSED"}, "ACTIVE", "advertiser"),
    "suspend": ({"ACTIVE", "PAUSED"}, "SUSPENDED", "admin"),
    "release": ({"SUSPENDED"}, "ACTIVE", "admin"),
    "end": ({"ACTIVE", "PAUSED"}, "ENDED", "advertiser"),
    "expire": ({"ACTIVE", "PAUSED", "SUSPENDED"}, "ENDED", "system"),
}


def make(status):
    c = Campaign.objects.create(owner=make_advertiser(), name="c", starts_at=NOW - DAY, ends_at=NOW + DAY, daily_budget=100)
    Campaign.objects.filter(pk=c.pk).update(status=status)  # 테스트 준비용(서비스가 아니라 직접 설정)
    return Campaign.objects.get(pk=c.pk)


@tag("security")
class TransitionTableTests(TestCase):
    def test_transition_table_is_exactly_the_documented_one(self):
        self.assertEqual({k: ({str(s) for s in v[0]}, str(v[1]), v[2]) for k, v in tr.TRANSITIONS.items()}, EXPECTED)

    def test_transition_table_allows_only_listed(self):
        for action, (allowed, to, who) in EXPECTED.items():
            for status in ALL:
                c = make(status)
                if status in allowed:
                    tr.apply(c, action, who, NOW)
                    self.assertEqual(Campaign.objects.get(pk=c.pk).status, to, (action, status))
                else:
                    expected = CampaignEnded if status == "ENDED" else CampaignSuspended if status == "SUSPENDED" and who == "advertiser" else InvalidTransition
                    with self.assertRaises(expected, msg=(action, status)):
                        tr.apply(c, action, who, NOW)
                    self.assertEqual(Campaign.objects.get(pk=c.pk).status, status)  # 거부되면 상태는 그대로

    def test_actor_kind_is_checked(self):
        for action, (_allowed, _to, who) in EXPECTED.items():
            wrong = "admin" if who != "admin" else "advertiser"
            with self.assertRaises(ValueError, msg=action):
                tr.apply(make("ACTIVE"), action, wrong, NOW)

    def test_expire_records_previous_state_and_end_pins_ends_at(self):
        c = make("SUSPENDED")
        tr.apply(c, "expire", "system", NOW + 2 * DAY)
        c.refresh_from_db()
        self.assertEqual((c.status, c.ended_from), ("ENDED", "SUSPENDED"))
        started_later = Campaign.objects.create(owner=make_advertiser(), name="c", starts_at=NOW + DAY, ends_at=NOW + 3 * DAY, daily_budget=1)
        tr.apply(started_later, "end", "advertiser", NOW)
        started_later.refresh_from_db()
        self.assertEqual(started_later.ends_at, NOW + DAY)  # 시작 전이면 시작 시각으로(기간 제약 유지)


@tag("security")
class OnlyTransitionsWritesStatusTests(TestCase):
    def test_only_transitions_module_writes_status(self):
        """상태(캠페인·재검토 요청)를 쓰는 코드는 transitions.py 뿐이다(설계 §4.4-5)."""
        root = Path(__file__).resolve().parent.parent / "campaigns"
        pattern = re.compile(r"\.status\s*=(?!=)|\.update\([^)]*\bstatus=|\.create\([^)]*\bstatus=|\bsetattr\([^)]*status")
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "transitions.py" or "migrations" in path.parts:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(offenders, [])
        self.assertTrue((root / "transitions.py").read_text(encoding="utf-8").count(".status =") >= 2)  # 검사가 공회전이 아님
