"""서로 다른 매체의 실제 저장 기록을 사용하고 외부 HTTP만 대체한다."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from ad_bridge.api.config import AdsConfig
from ad_bridge.api.errors import AdsHTTPError
from ad_bridge.decisions.store import remember_decision
from ad_bridge.delivery.worker import dispatch_due_impressions
from ad_bridge.game.placements import placement
from ad_bridge.game.views import report_impression, reaction_result
from ad_bridge.impressions import store
from ad_bridge.impressions.service import report_impression_once
from ad_bridge.models import IssuedDecision
from ad_bridge.placements import transfer_token
from ad_bridge.routing import RoutedAdsClient
from ad_bridge.tests.support import received_reaction, shared_decision


class MediaRoutingTests(TestCase):
    def setUp(self):
        self.roof, self.legacy, self.portal = (str(uuid4()) for _ in range(3))
        self.owner, self.subject = uuid4(), uuid4()
        self.config = AdsConfig('https://ads.test/api/media/v1', 'default-test-key', 1,
                                subject_secret='test-subject-secret')
        self.env = {
            'ADS_PORTAL_MEDIA_KEY': 'portal-test-key',
            'ADS_PORTAL_MEDIA_SLOT_IDS': self.portal,
            'ADS_PORTAL_LEFT_SLOT_ID': self.portal,
            'ADS_PORTAL_RIGHT_SLOT_ID': self.portal,
            'ADS_ROOFTOP_SLOT_ID': self.roof,
        }
        self.clients = {key: Mock() for key in ('default-test-key', 'portal-test-key')}
        self.receipts = {}
        self.now = datetime(2026, 10, 15, 1, 0, 1, tzinfo=timezone.utc)
        self.ad = shared_decision().ad
        for client in self.clients.values():
            client.create_decision.side_effect = lambda **kw: replace(
                shared_decision(), slot_id=str(kw['slot_id']), ad=self.ad,
                audience='individual' if kw.get('subject_id') else 'shared')
            client.report_impression.side_effect = self.receive
            client.get_reaction.side_effect = lambda **kw: self.receipts[kw['reaction_id']]
        factory = patch('ad_bridge.routing.AdsClient', side_effect=lambda config: self.clients[config.media_key])
        self.factory = factory.start()
        self.addCleanup(factory.stop)

    def receive(self, **request):
        result = received_reaction(**request)
        self.receipts[request['reaction_id']] = result
        return result

    def decision(self, slot):
        shared = slot == self.roof
        decision = replace(shared_decision(), slot_id=slot, audience='shared' if shared else 'individual')
        remember_decision(decision, subject_id=None if shared else self.subject,
                          owner_id=None if shared else self.owner)
        return decision

    def report(self, router, decision):
        return report_impression_once(
            client=router, store=store, decision_id=decision.decision_id, owner_id=self.owner,
            subject_id=self.subject, occurred_at=self.now.isoformat().replace('+00:00', 'Z'),
            now=lambda: self.now)

    def request(self, body=None):
        request = RequestFactory().post('/api/ads/', data=json.dumps(body or {}), content_type='application/json')
        request.user = SimpleNamespace(pk=7, is_authenticated=True,
                                       campus_profile=SimpleNamespace(user_uuid=self.owner))
        return request

    def test_roof_new_portal_and_legacy_slot_choose_their_own_media(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        for slot in (self.roof, self.portal, self.legacy):
            router.create_decision(slot_id=slot, subject_id=None if slot == self.roof else self.subject)
        self.assertEqual([c.kwargs['slot_id'] for c in self.clients['default-test-key'].create_decision.call_args_list],
                         [self.roof, self.legacy])
        self.clients['portal-test-key'].create_decision.assert_called_once_with(slot_id=self.portal, subject_id=self.subject)

    def test_http_placement_routes_two_portal_requests_and_preserves_roof(self):
        with patch.dict(os.environ, self.env), patch('ad_bridge.game.placements.AdsConfig.from_env', return_value=self.config), \
             override_settings(ADS_ENABLED=True, ADS_ROOFTOP_SLOT_ID=self.roof,
                               ADS_PORTAL_LEFT_SLOT_ID=self.portal, ADS_PORTAL_RIGHT_SLOT_ID=self.portal):
            roof = placement(self.request(), 'rooftop')
            portal = placement(self.request({'token': transfer_token(7, uuid4())}), 'portal')
        self.assertEqual((roof.status_code, portal.status_code), (200, 200))
        self.assertEqual(self.clients['default-test-key'].create_decision.call_count, 1)
        self.assertEqual(self.clients['portal-test-key'].create_decision.call_count, 2)
        ads = json.loads(portal.content)['ads']
        self.assertEqual(len(ads), 2)
        self.assertEqual(ads[0]['decision_id'], ads[1]['decision_id'])
        self.assertNotIn('portal-test-key', portal.content.decode())

    def test_impressions_use_saved_slots_and_duplicates_never_send_again(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        for slot in (self.roof, self.legacy, self.portal):
            decision = self.decision(slot)
            first, duplicate = self.report(router, decision), self.report(router, decision)
            self.assertEqual(first.record.delivery_state, 'ACKNOWLEDGED')
            self.assertFalse(duplicate.created)
            self.assertEqual(first.record.reaction_id, duplicate.record.reaction_id)
        self.assertEqual(self.clients['default-test-key'].report_impression.call_count, 2)
        self.assertEqual(self.clients['portal-test-key'].report_impression.call_count, 1)

    def test_impression_and_result_views_use_portal_key(self):
        decision = self.decision(self.portal)
        with patch.dict(os.environ, self.env), patch('ad_bridge.game.views.AdsConfig.from_env', return_value=self.config):
            sent = report_impression(self.request(), decision.decision_id)
            result = reaction_result(self.request(), decision.decision_id)
        self.assertEqual((sent.status_code, result.status_code), (201, 200))
        self.clients['portal-test-key'].report_impression.assert_called_once()
        self.clients['portal-test-key'].get_reaction.assert_called_once()
        self.clients['default-test-key'].report_impression.assert_not_called()
        self.clients['default-test-key'].get_reaction.assert_not_called()

    def test_mixed_retry_batch_keeps_keys_reaction_ids_and_subjects(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        for client in self.clients.values():
            client.report_impression.side_effect = AdsHTTPError(503)
        pending = [self.report(router, self.decision(slot)) for slot in (self.legacy, self.portal, self.roof)]
        original = {key: [c.kwargs.copy() for c in client.report_impression.call_args_list]
                    for key, client in self.clients.items()}
        for client in self.clients.values():
            client.report_impression.reset_mock()
            client.report_impression.side_effect = self.receive
        due = max(result.record.next_attempt_at for result in pending) + timedelta(seconds=1)
        counts = dispatch_due_impressions(client=router, store=store, now=lambda: due)
        self.assertEqual(counts['acknowledged'], 3)
        for key, client in self.clients.items():
            self.assertCountEqual([c.kwargs for c in client.report_impression.call_args_list], original[key])

    def test_production_retry_command_uses_routed_client(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        self.clients['portal-test-key'].report_impression.side_effect = AdsHTTPError(503)
        self.report(router, self.decision(self.portal))
        self.clients['portal-test-key'].report_impression.side_effect = self.receive
        with patch.dict(os.environ, self.env), patch('ad_bridge.management.commands.dispatch_ad_reactions.AdsConfig.from_env', return_value=self.config):
            call_command('dispatch_ad_reactions', '--once', stdout=StringIO())
        self.assertEqual(self.clients['portal-test-key'].report_impression.call_count, 2)
        self.clients['default-test-key'].report_impression.assert_not_called()

    def test_manual_401_recovery_uses_saved_portal_slot(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        self.clients['portal-test-key'].report_impression.side_effect = AdsHTTPError(401)
        blocked = self.report(router, self.decision(self.portal))
        self.clients['portal-test-key'].report_impression.side_effect = self.receive
        with patch.dict(os.environ, self.env), patch('ad_bridge.management.commands.dispatch_ad_reactions.AdsConfig.from_env', return_value=self.config):
            call_command('dispatch_ad_reactions', '--recover-401', blocked.record.reaction_id, stdout=StringIO())
        self.assertEqual(self.clients['portal-test-key'].report_impression.call_count, 2)
        self.clients['default-test-key'].report_impression.assert_not_called()

    def test_historical_portal_slot_stays_routable_after_display_slot_change(self):
        decision = self.decision(self.portal)
        other = str(uuid4())
        env = {**self.env, 'ADS_PORTAL_MEDIA_SLOT_IDS': self.portal + ',' + other,
               'ADS_PORTAL_LEFT_SLOT_ID': other, 'ADS_PORTAL_RIGHT_SLOT_ID': other}
        self.report(RoutedAdsClient(self.config, environ=env), decision)
        self.clients['portal-test-key'].report_impression.assert_called_once()
        self.clients['default-test-key'].report_impression.assert_not_called()

    def test_single_media_configuration_keeps_legacy_behavior(self):
        router = RoutedAdsClient(self.config, environ={})
        with self.assertNumQueries(0):
            router.report_impression(decision_id=str(uuid4()), reaction_id=str(uuid4()),
                                     occurred_at='2026-10-15T01:00:01Z', subject_id=str(self.subject))
        self.clients['default-test-key'].report_impression.assert_called_once()
        self.clients['portal-test-key'].report_impression.assert_not_called()

    def test_invalid_route_configuration_never_initializes_transport(self):
        cases = [
            {'ADS_PORTAL_MEDIA_KEY': 'private-value'},
            {'ADS_PORTAL_MEDIA_SLOT_IDS': self.portal},
            {**self.env, 'ADS_PORTAL_MEDIA_SLOT_IDS': 'private-value'},
            {**self.env, 'ADS_PORTAL_MEDIA_SLOT_IDS': self.portal + ',' + self.roof},
            {**self.env, 'ADS_PORTAL_RIGHT_SLOT_ID': self.legacy},
            {**self.env, 'ADS_PORTAL_MEDIA_KEY': 'private value'},
        ]
        for env in cases:
            with self.subTest(env_names=sorted(env)):
                self.factory.reset_mock()
                with self.assertRaises(ValueError) as error:
                    RoutedAdsClient(self.config, environ=env)
                self.assertNotIn('private', str(error.exception))
                self.factory.assert_not_called()

    def test_unknown_decision_does_not_fall_back_to_a_different_media(self):
        router = RoutedAdsClient(self.config, environ=self.env)
        with self.assertRaises(ValueError):
            router.get_reaction(decision_id=str(uuid4()), reaction_id=str(uuid4()))
        for client in self.clients.values():
            client.get_reaction.assert_not_called()
