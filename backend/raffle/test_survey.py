from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.db import close_old_connections
from django.test import Client, TransactionTestCase
from django.utils import timezone

from accounts.models import Profile
from . import service, survey
from .models import Control, Entry, Event, SurveyAttempt, SurveyConnection
from .tests import buzzer_position, setup_users

ENDPOINT = 'https://script.google.com/macros/s/qa-reader/exec'
KEY = 'qa_only_' + 'x' * 40


def configure_bridge():
    return SurveyConnection.objects.create(pk=1, endpoint=ENDPOINT, access_key=KEY,
        form_id=settings.CAMPUS_RAFFLE_SURVEY_FORM_ID, form_url=settings.CAMPUS_RAFFLE_SURVEY_URL,
        token_parameter='entry.123456789', connected_at=timezone.now())


def google_result(responses=None, **changes):
    return {'ok': True, 'version': 1, 'formId': settings.CAMPUS_RAFFLE_SURVEY_FORM_ID,
            'formUrl': settings.CAMPUS_RAFFLE_SURVEY_URL, 'tokenParameter': 'entry.123456789',
            'checkedAt': (timezone.now() + timedelta(milliseconds=10)).isoformat(),
            'acceptingResponses': True, 'responses': responses or [], **changes}


class SurveyRegistrationTests(TransactionTestCase):
    def setUp(self):
        setup_users(self)
        service.control_event('open', None)
        self.event = Control.objects.get(pk=1).current_event
        self.bridge = configure_bridge()

    def begin(self, user=None):
        user = user or self.member
        url = survey.begin(user, buzzer_position(), str(self.event.pk))
        return SurveyAttempt.objects.get(event=self.event, user=user), url

    def response(self, attempt, response_id='qa-response-1', submitted_at=None):
        return {'token': attempt.token, 'responseId': response_id,
                'submittedAt': (submitted_at or timezone.now()).isoformat()}

    def test_opening_form_only_creates_pending_attempt_with_prefilled_account_token(self):
        attempt, url = self.begin()
        self.assertEqual(Entry.objects.count(), 0)
        self.assertEqual(attempt.status, 'pending')
        self.assertEqual(parse_qs(urlsplit(url).query)['entry.123456789'], [attempt.token])
        self.assertEqual(len(attempt.token), 43)
        self.assertNotIn(self.member.username, url)
        with patch('raffle.survey.google_request', return_value=google_result()) as remote:
            self.assertEqual(survey.synchronize(), 0)
            self.assertEqual(remote.call_args.kwargs['tokens'], [attempt.token])
        self.assertEqual(Entry.objects.count(), 0)

    def test_unconfigured_wrong_floor_closed_and_stale_requests_are_rejected(self):
        for position in ({'floor': 'campus', 'x': 1540, 'y': 384}, {'floor': 'rooftop', 'x': 10, 'y': 10}):
            with self.assertRaises(service.RaffleError):
                survey.begin(self.member, position, str(self.event.pk))
        with self.assertRaises(service.RaffleError):
            survey.begin(self.member, buzzer_position(), 'old-event')
        self.event.draw_at = timezone.now() - timedelta(seconds=1)
        self.event.save()
        with self.assertRaises(service.RaffleError):
            self.begin()
        SurveyConnection.objects.all().delete()
        with self.assertRaises(survey.SurveyError):
            self.begin()
        self.assertEqual(SurveyAttempt.objects.count(), 0)

    def test_retry_and_concurrent_tabs_share_one_attempt_and_reopen_away_from_buzzer(self):
        def start(_):
            close_old_connections()
            try:
                return survey.begin(self.member, buzzer_position(), str(self.event.pk))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=3) as pool:
            urls = list(pool.map(start, range(3)))
        self.assertEqual(len(set(urls)), 1)
        self.assertEqual(SurveyAttempt.objects.count(), 1)
        self.assertEqual(survey.begin(self.member, {'floor': 'campus'}, str(self.event.pk)), urls[0])
        another, other_url = self.begin(self.admin)
        self.assertNotEqual(urls[0], other_url)
        self.assertEqual(Entry.objects.count(), 0)

    def test_confirmed_submission_registers_once_with_nickname_snapshot(self):
        attempt, _ = self.begin()
        Profile.objects.filter(user=self.member).update(nickname='새 이름')
        result = google_result([self.response(attempt)])
        with patch('raffle.survey.google_request', return_value=result):
            self.assertEqual(survey.synchronize(), 1)
            self.assertEqual(survey.synchronize(), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'registered')
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(attempt.entry.nickname, '참가 조원')
        self.assertEqual(service.snapshot(self.member)['myEntryId'], str(attempt.entry_id))
        self.assertIsNone(service.snapshot(self.admin)['myEntryId'])
        self.assertNotIn(attempt.token, json.dumps(service.snapshot(self.admin)))
        self.assertNotIn(KEY, json.dumps(service.snapshot(self.admin)))

    def test_malformed_unrequested_and_wrong_form_responses_never_register(self):
        attempt, _ = self.begin()
        for changes in ({'formId': 'wrong-form'}, {'responses': [self.response(attempt, submitted_at=timezone.now().replace(tzinfo=None))]},
                        {'responses': [{'token': 'other', 'responseId': '1', 'submittedAt': timezone.now().isoformat()}]},
                        {'checkedAt': None}, {'responses': [self.response(attempt), self.response(attempt)]}):
            with patch('raffle.survey.google_request', return_value=google_result(**changes)):
                with self.assertRaises(survey.SurveyError):
                    survey.synchronize()
        self.assertEqual(Entry.objects.count(), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'pending')

    def test_network_failure_preserves_attempt_and_retry_completes_registration(self):
        attempt, _ = self.begin()
        with patch('raffle.survey.google_request', side_effect=survey.SurveyError()):
            with self.assertRaises(survey.SurveyError):
                survey.synchronize()
        self.assertEqual(SurveyAttempt.objects.get(pk=attempt.pk).status, 'pending')
        self.assertTrue(SurveyConnection.objects.get(pk=1).last_error)
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt)])):
            self.assertEqual(survey.synchronize(), 1)
        self.assertEqual(SurveyConnection.objects.get(pk=1).last_error, '')

    def test_submission_before_deadline_is_included_even_when_polling_is_late(self):
        attempt, _ = self.begin()
        now = timezone.now()
        SurveyAttempt.objects.filter(pk=attempt.pk).update(requested_at=now - timedelta(seconds=20))
        Event.objects.filter(pk=self.event.pk).update(draw_at=now - timedelta(seconds=2))
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt, submitted_at=now-timedelta(seconds=3))])):
            self.assertTrue(service.advance_due())
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'drawn')
        self.assertEqual(self.event.winner_nickname, '참가 조원')

    def test_late_submission_and_submission_before_token_issuance_are_rejected(self):
        attempt, _ = self.begin()
        Event.objects.filter(pk=self.event.pk).update(draw_at=timezone.now() - timedelta(seconds=1))
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt)])):
            survey.synchronize()
        attempt.refresh_from_db()
        self.assertEqual(attempt.closed_reason, 'after_deadline')
        Event.objects.filter(pk=self.event.pk).update(draw_at=None)
        other, _ = self.begin(self.admin)
        with patch('raffle.survey.google_request', return_value=google_result([self.response(other, 'qa-old', other.requested_at-timedelta(seconds=1))])):
            survey.synchronize()
        other.refresh_from_db()
        self.assertEqual(other.closed_reason, 'before_request')
        self.assertEqual(Entry.objects.count(), 0)

    def test_draw_waits_for_google_confirmation_and_no_new_attempt_can_start(self):
        attempt, _ = self.begin()
        with patch('raffle.survey.google_request', side_effect=survey.SurveyError()):
            with self.assertRaises(survey.SurveyError):
                service.control_event('draw', str(self.event.pk))
            self.assertFalse(service.advance_due())
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'open')
        self.assertIsNotNone(self.event.draw_at)
        with self.assertRaises(service.RaffleError):
            self.begin(self.admin)
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt, submitted_at=self.event.draw_at-timedelta(microseconds=1))])):
            service.control_event('draw', str(self.event.pk))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'drawn')
        self.assertIsNotNone(self.event.winner_entry_id)

    def test_stale_google_read_boundary_defers_draw_without_accepting_partial_data(self):
        attempt, _ = self.begin()
        Event.objects.filter(pk=self.event.pk).update(draw_at=timezone.now())
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt, submitted_at=attempt.requested_at)], checkedAt=attempt.requested_at.isoformat())):
            self.assertFalse(service.advance_due())
        self.assertEqual(Entry.objects.count(), 0)
        self.assertEqual(Event.objects.get(pk=self.event.pk).status, 'open')

    def test_inactive_or_deleted_accounts_do_not_register(self):
        attempt, _ = self.begin()
        self.member.is_active = False
        self.member.save()
        with patch('raffle.survey.google_request', return_value=google_result([self.response(attempt)])):
            survey.synchronize()
        self.assertEqual(SurveyAttempt.objects.get(pk=attempt.pk).closed_reason, 'account_unavailable')
        other, _ = self.begin(self.admin)
        self.admin.delete()
        with patch('raffle.survey.google_request', return_value=google_result([self.response(other, 'qa-deleted')])):
            survey.synchronize()
        self.assertEqual(SurveyAttempt.objects.get(pk=other.pk).closed_reason, 'account_unavailable')
        self.assertEqual(Entry.objects.count(), 0)

    def test_same_google_response_id_cannot_register_different_accounts(self):
        first, _ = self.begin()
        second, _ = self.begin(self.admin)
        with patch('raffle.survey.google_request', return_value=google_result([self.response(first)])):
            survey.synchronize()
        with patch('raffle.survey.google_request', return_value=google_result([self.response(second)])):
            with self.assertRaises(survey.SurveyError):
                survey.synchronize()
        self.assertEqual(Entry.objects.count(), 1)

    def test_admin_connection_requires_auth_csrf_and_validated_google_metadata(self):
        data = {'endpoint': ENDPOINT, 'accessKey': KEY}
        self.assertEqual(Client().post('/api/raffle/survey/connect/', data=json.dumps(data), content_type='application/json').status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post('/api/raffle/survey/connect/', data=json.dumps(data), content_type='application/json').status_code, 403)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        self.assertEqual(secure.post('/api/raffle/survey/connect/', data=json.dumps(data), content_type='application/json').status_code, 403)
        self.client.cookies = secure.cookies.copy()
        with patch('raffle.survey.google_request', return_value=google_result()) as remote:
            response = self.client.post('/api/raffle/survey/connect/', data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['survey']['configured'])
            self.assertNotIn(KEY, response.content.decode())
            self.assertEqual(remote.call_args.args[1], 'info')
        with patch('raffle.survey.google_request', return_value=google_result(formId='foreign-form')):
            response = self.client.post('/api/raffle/survey/connect/', data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 503)
        self.assertEqual(SurveyConnection.objects.get(pk=1).form_id, settings.CAMPUS_RAFFLE_SURVEY_FORM_ID)
        self.assertEqual(self.client.get('/api/raffle/survey/connect/').status_code, 405)
        self.assertEqual(self.client.post('/api/raffle/survey/complete/', {}).status_code, 404)

    def test_reader_endpoint_rejects_private_hosts_query_keys_and_foreign_redirects(self):
        for url in ('http://127.0.0.1:8003/', 'https://example.com/exec', ENDPOINT+'?key=secret', ENDPOINT.replace('/exec','/dev')):
            with patch('raffle.survey.google_request') as remote:
                with self.assertRaises(survey.SurveyError):
                    survey.connect(url, KEY)
                remote.assert_not_called()
        with self.assertRaises(survey.SurveyError):
            survey.GoogleRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/')

    def test_reader_post_has_private_key_only_in_body_and_sanitizes_errors(self):
        with patch('raffle.survey.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value = b'<html>access denied</html>'
            with self.assertRaises(survey.SurveyError) as failure:
                survey.google_request(self.bridge, 'info')
            request = factory.return_value.open.call_args.args[0]
            self.assertNotIn(KEY, request.full_url)
            self.assertEqual(json.loads(request.data)['accessKey'], KEY)
            self.assertNotIn(KEY, str(failure.exception))

    def test_setup_code_is_staff_only_and_contains_no_deployed_access_key(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get('/api/raffle/survey/script/').status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get('/api/raffle/survey/script/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('setupRaffleSurvey', response.content.decode())
        self.assertNotIn(KEY, response.content.decode())
