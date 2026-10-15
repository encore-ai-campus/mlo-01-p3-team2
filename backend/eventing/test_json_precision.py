import uuid

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from .events import build_envelope, canonical_json
from .models import EventOutbox


class ExactJSONStorageTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='precision-check')
        self.profile = Profile.objects.create(user=user, nickname='precision')
        self.position = {'floor': 'campus', 'x': 1909.0846645249294,
                         'y': 920.9031138666909, 'dir': 'left'}

    def test_last_position_preserves_coordinates_and_json_lookups(self):
        self.profile.last_position = self.position
        self.profile.save(update_fields=['last_position'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.last_position, self.position)
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk,
                        last_position__floor='campus').exists())
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk,
                        last_position__floor__icontains='camp').exists())

    def test_outbox_reload_keeps_wire_payload_and_fingerprint(self):
        raw = {'user_uuid': str(self.profile.user_uuid), 'session_uuid': str(uuid.uuid4()),
               'class_group_uuid': str(uuid.uuid4()), 'floor_uuid': str(uuid.uuid4()),
               'zone_uuid': None, 'x': self.position['x'], 'y': self.position['y'],
               'input_kind': 'KEYBOARD'}
        event_id, occurred_at = uuid.uuid4(), timezone.now()
        envelope = build_envelope(event_id, 'movement_observed', occurred_at, raw)
        row = EventOutbox.objects.create(event_uuid=event_id, event_type='movement_observed',
              topic='raw.movement', message_key=self.profile.user_uuid, raw_data=raw,
              occurred_at=occurred_at, payload_json=envelope)
        row.refresh_from_db()
        self.assertEqual(canonical_json(row.raw_data), canonical_json(raw))
        self.assertEqual(canonical_json(row.payload_json), canonical_json(envelope))
        regenerated = build_envelope(row.event_uuid, row.event_type, row.occurred_at, row.raw_data)
        self.assertEqual(row.payload_json['raw_manifest']['fingerprint'],
                         regenerated['raw_manifest']['fingerprint'])

    def test_database_still_rejects_invalid_json(self):
        table = connection.ops.quote_name(Profile._meta.db_table)
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE ' + table + ' SET last_position=%s WHERE id=%s',
                               ['{invalid json}', self.profile.pk])
