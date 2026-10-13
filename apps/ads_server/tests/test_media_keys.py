import hmac
import re
import uuid
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase, tag

from foundation.errors import Conflict, Forbidden, InvalidRequest, NotFound
from foundation.models import AuditLog
from masters import api
from masters.models import MediaKey
from tests.concurrency import overlap
from tests.factories import DAY, NOW, make_admin, make_advertiser

KEY_SHAPE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9_-]{43}$")


def media(admin, name="메타버스"):
    return api.create_media(admin, name)


@tag("security")
class MediaKeyTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.media = media(self.admin)

    def test_issued_key_is_shown_once_and_only_its_hash_is_stored(self):
        issued = api.issue_media_key(self.admin, self.media.media_id, "운영", now=NOW)
        self.assertRegex(issued.key, KEY_SHAPE)
        self.assertTrue(issued.key.startswith(issued.key_id.hex + "."))
        secret = issued.key.split(".", 1)[1]
        with connection.cursor() as cur:  # 저장소 전체(키 테이블과 감사 로그)에 평문이 없다
            cur.execute("SELECT * FROM masters_media_key")
            rows = " ".join(str(v) for row in cur.fetchall() for v in row)
        self.assertNotIn(secret, rows)
        self.assertNotIn(issued.key, rows)
        self.assertEqual(len(MediaKey.objects.get(key_id=issued.key_id).secret_hash), 64)  # SHA-256 16진수
        self.assertNotIn(secret, str(list(AuditLog.objects.values())))
        keys = api.list_media_keys(self.admin, self.media.media_id, now=NOW)
        self.assertNotIn(secret, str(keys))  # 목록·값 객체에도 비밀이 없다
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].active)

    def test_keys_are_unique_and_unpredictable(self):
        issued = [api.issue_media_key(self.admin, self.media.media_id, now=NOW) for _ in range(20)]
        self.assertEqual(len({k.key for k in issued}), 20)
        self.assertEqual(len({k.key_id for k in issued}), 20)

    def test_authenticate_success_and_all_failures_look_the_same(self):
        issued = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        identity = api.authenticate_media_key(issued.key, now=NOW)
        self.assertEqual((identity.media_id, identity.key_id, identity.media_is_active), (self.media.media_id, issued.key_id, True))
        key_hex, secret = issued.key.split(".")
        wrong_secret = key_hex + "." + ("A" if secret[0] != "A" else "B") + secret[1:]
        bad = [
            "", " ", None, 5, "garbage", "x" * 500, key_hex, key_hex + ".", "." + secret, secret + "." + key_hex,
            uuid.uuid4().hex + "." + secret,  # 모르는 key_id
            wrong_secret,  # 맞는 key_id, 틀린 비밀
            issued.key + "x", issued.key[:-1], issued.key.upper(), " " + issued.key, issued.key + "\n",
            key_hex + "." + secret.replace(secret[0], "é", 1),  # 유니코드
        ]
        for value in bad:
            self.assertIsNone(api.authenticate_media_key(value, now=NOW), repr(value))

    def test_comparison_is_constant_time_even_for_unknown_keys(self):
        """없는 키도 같은 해시 비교를 한다(응답 시간으로 key_id 의 존재 여부를 알 수 없게)."""
        issued = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        calls = []
        real = hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        with mock.patch("masters.services.hmac.compare_digest", side_effect=spy):
            api.authenticate_media_key(issued.key, now=NOW)
            api.authenticate_media_key(uuid.uuid4().hex + "." + "A" * 43, now=NOW)
        self.assertEqual(len(calls), 2)  # 알려진 키와 모르는 키 모두 한 번씩 비교
        with mock.patch("masters.services.MediaKey.objects") as objects:
            api.authenticate_media_key("not even close", now=NOW)
            objects.select_related.assert_not_called()  # 형식이 틀리면 DB 를 보지 않는다

    def test_revoked_and_expired_keys_are_rejected(self):
        revoked = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        expiring = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        MediaKey.objects.filter(key_id=expiring.key_id).update(expires_at=NOW + timedelta(seconds=10))
        api.revoke_media_key(self.admin, revoked.key_id, now=NOW)
        self.assertIsNone(api.authenticate_media_key(revoked.key, now=NOW))
        self.assertIsNotNone(api.authenticate_media_key(expiring.key, now=NOW + timedelta(seconds=9)))
        self.assertIsNone(api.authenticate_media_key(expiring.key, now=NOW + timedelta(seconds=10)))  # 만료 시각 포함
        api.revoke_media_key(self.admin, revoked.key_id, now=NOW)  # 다시 폐기해도 변화 없음
        self.assertEqual(AuditLog.objects.filter(action="masters.media_key_revoked").count(), 1)

    def test_inactive_media_still_authenticates_but_is_flagged(self):
        issued = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        api.set_media_active(self.admin, self.media.media_id, False)
        identity = api.authenticate_media_key(issued.key, now=NOW)
        self.assertFalse(identity.media_is_active)  # 403 은 호출하는 쪽이 판단한다

    def test_rotation_keeps_both_keys_valid_during_the_grace_period(self):
        old = api.issue_media_key(self.admin, self.media.media_id, "옛", now=NOW)
        new = api.rotate_media_key(self.admin, self.media.media_id, grace_seconds=3600, label="새", now=NOW)
        for t in (NOW, NOW + timedelta(seconds=3599)):
            self.assertIsNotNone(api.authenticate_media_key(old.key, now=t), t)
            self.assertIsNotNone(api.authenticate_media_key(new.key, now=t), t)  # 무중단: 유예 동안 두 키 모두 유효
        self.assertIsNone(api.authenticate_media_key(old.key, now=NOW + timedelta(seconds=3600)))  # 유예가 끝나면 옛 키만 무효
        self.assertIsNotNone(api.authenticate_media_key(new.key, now=NOW + 10 * DAY))
        views = {k.key_id: k for k in api.list_media_keys(self.admin, self.media.media_id, now=NOW)}
        self.assertEqual(views[old.key_id].expires_at, NOW + timedelta(seconds=3600))
        self.assertIsNone(views[new.key_id].expires_at)

    def test_rotation_never_extends_an_earlier_expiry_and_zero_grace_expires_old_now(self):
        old = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        MediaKey.objects.filter(key_id=old.key_id).update(expires_at=NOW + timedelta(seconds=60))
        api.rotate_media_key(self.admin, self.media.media_id, grace_seconds=3600, now=NOW)
        self.assertEqual(MediaKey.objects.get(key_id=old.key_id).expires_at, NOW + timedelta(seconds=60))  # 더 일찍 만료될 키는 그대로
        other = api.issue_media_key(self.admin, self.media.media_id, now=NOW)
        api.rotate_media_key(self.admin, self.media.media_id, grace_seconds=0, now=NOW)
        self.assertIsNone(api.authenticate_media_key(other.key, now=NOW))  # 유예 0: 바로 만료

    def test_rotation_validates_grace_and_other_media_keys_are_untouched(self):
        other_media = media(self.admin, "다른 매체")
        other = api.issue_media_key(self.admin, other_media.media_id, now=NOW)
        for bad in (-1, 1.5, True, "3600", None, 31 * 24 * 3600):
            with self.assertRaises(InvalidRequest, msg=bad):
                api.rotate_media_key(self.admin, self.media.media_id, grace_seconds=bad, now=NOW)
        api.rotate_media_key(self.admin, self.media.media_id, grace_seconds=0, now=NOW)
        self.assertIsNotNone(api.authenticate_media_key(other.key, now=NOW + DAY))  # 다른 매체의 키는 영향 없음
        self.assertEqual(api.authenticate_media_key(other.key, now=NOW).media_id, other_media.media_id)

    def test_only_admins_manage_keys_and_everything_is_audited_without_the_key(self):
        for actor in (make_advertiser(), None):
            for call in (
                lambda a=actor: api.issue_media_key(a, self.media.media_id),
                lambda a=actor: api.rotate_media_key(a, self.media.media_id, 10),
                lambda a=actor: api.revoke_media_key(a, uuid.uuid4()),
                lambda a=actor: api.list_media_keys(a, self.media.media_id),
            ):
                with self.assertRaises(Forbidden):
                    call()
        self.assertEqual(MediaKey.objects.count(), 0)
        issued = api.issue_media_key(self.admin, self.media.media_id, "운영", now=NOW)
        api.rotate_media_key(self.admin, self.media.media_id, 60, now=NOW)
        api.revoke_media_key(self.admin, issued.key_id, now=NOW)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertLessEqual({"masters.media_key_issued", "masters.media_key_rotated", "masters.media_key_revoked"}, actions)
        dump = str(list(AuditLog.objects.values()))
        self.assertNotIn(issued.key.split(".")[1], dump)
        self.assertEqual(AuditLog.objects.get(action="masters.media_key_issued").actor_id, self.admin.pk)

    def test_unknown_media_or_key_is_not_found(self):
        with self.assertRaises(NotFound):
            api.issue_media_key(self.admin, uuid.uuid4())
        with self.assertRaises(NotFound):
            api.rotate_media_key(self.admin, "nope", 10)
        with self.assertRaises(NotFound):
            api.revoke_media_key(self.admin, uuid.uuid4())


@tag("security")
class MediaKeyRequestKeyTests(TestCase):
    """같은 요청 키(화면 폼 하나)로는 키를 한 번만 발급한다. 평문을 다시 보여 줄 수 없으므로 두 번째는 409 이고 키 식별자를 알려 준다."""

    def setUp(self):
        self.admin = make_admin()
        self.media = media(self.admin)

    def test_the_same_request_key_issues_once(self):
        first = api.issue_media_key(self.admin, self.media.media_id, request_key="r1")
        before = MediaKey.objects.get(pk=first.key_id).expires_at
        for call in (
            lambda: api.issue_media_key(self.admin, self.media.media_id, request_key="r1"),
            lambda: api.rotate_media_key(self.admin, self.media.media_id, 0, request_key="r1"),  # 기존 키를 만료시키기 전에 거절한다
            lambda: api.issue_media_key(self.admin, media(self.admin, "다른 매체").media_id, request_key="r1"),
        ):
            with self.assertRaisesRegex(Conflict, str(first.key_id)):
                call()
        self.assertEqual(MediaKey.objects.count(), 1)
        self.assertEqual(MediaKey.objects.get(pk=first.key_id).expires_at, before)
        self.assertIsNotNone(api.issue_media_key(self.admin, self.media.media_id, request_key="r2"))
        self.assertEqual(MediaKey.objects.count(), 2)
        with self.assertRaises(InvalidRequest):
            api.issue_media_key(self.admin, self.media.media_id, request_key="x" * 65)


@tag("security")
class RotationRaceTests(TransactionTestCase):
    """외부 검토(3-1d) P2: 서로 다른 교체가 겹치면, 늦게 끝난 긴 유예 교체가 그 사이 유예 0 교체로 이미 만료된 키를 다시 살렸다
    (만료를 파이썬에서 읽은 값으로 판단하고 PK 로만 갱신). 같은 매체의 교체는 매체 행 잠금으로 줄을 서고, 만료 조건은 UPDATE 가 DB 의 지금 값으로 본다."""

    def test_a_slower_long_grace_rotation_does_not_revive_an_expired_key(self):
        admin = make_admin()
        m = media(admin)
        old = api.issue_media_key(admin, m.media_id)
        # 긴 유예 교체가 옛 키(만료 없음)를 읽은 뒤 만료 UPDATE 직전에 멈춘 사이, 유예 0 교체는 매체 행 잠금에서 기다린다
        slow, fast = overlap(self, lambda: api.rotate_media_key(admin, m.media_id, 3600, request_key="slow"), "UPDATE", "masters_media_key",
                             lambda: api.rotate_media_key(admin, m.media_id, 0, request_key="fast"))
        self.assertEqual((slow.errors, fast.errors), ([], []))
        self.assertIsNone(api.authenticate_media_key(old.key))  # 즉시 만료가 되살아나지 않는다
        self.assertIsNone(api.authenticate_media_key(slow.result.key))  # 뒤의 교체(유예 0)는 앞의 교체가 만든 키도 본다
        self.assertIsNotNone(api.authenticate_media_key(fast.result.key))


class KeyListActiveTests(TestCase):
    def test_revoked_keys_and_keys_at_their_expiry_are_not_active(self):
        admin = make_admin()
        media = api.create_media(admin, "키 목록")
        live, expiring, revoked = (api.issue_media_key(admin, media.media_id, now=NOW) for _ in range(3))
        MediaKey.objects.filter(key_id=expiring.key_id).update(expires_at=NOW)
        api.revoke_media_key(admin, revoked.key_id, now=NOW)

        def active(now):
            return {k.key_id: k.active for k in api.list_media_keys(admin, media.media_id, now=now)}
        self.assertEqual(active(NOW), {live.key_id: True, expiring.key_id: False, revoked.key_id: False})  # 인증과 같은 경계: 만료 시각에 닿으면 무효
        self.assertTrue(active(NOW - timedelta(microseconds=1))[expiring.key_id])
