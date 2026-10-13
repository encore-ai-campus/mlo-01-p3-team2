import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Profile
from eventing.events import enqueue_event, validate_raw_data, raw_identity
from eventing.models import EventOutbox, PlatformSession
from learning import services
from learning.models import Question, QuestionChoice, LearningSession, SessionQuestion, UserAnswer, PointWallet, PointLedger
from learning.point_integration import ensure_wallet, wallet_balance
from .legacy_fixtures import prepare_event_context


def one_question_lesson(user, subject='python', kind='fill_blank', difficulty='beginner'):
    question = Question.objects.create(subject=subject, question_type=kind, difficulty=difficulty,
        category='integration', question_text='Choose or fill the keyword', correct_answer='SELECT' if subject == 'sql' else 'append')
    if kind == 'multiple_choice':
        for number, text in enumerate(['wrong', question.correct_answer, 'other', 'none'], 1):
            QuestionChoice.objects.create(question=question, choice_no=number, choice_text=text)
    lesson = LearningSession.objects.create(user=user, subject=subject, question_type=kind, difficulty=difficulty, total_questions=1)
    return SessionQuestion.objects.create(session=lesson, question=question, question_order=1, started_at=timezone.now())


class LearningPointEventTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='point-learner')
        prepare_event_context(self.user)
        ensure_wallet(self.user)
        self.login = PlatformSession.objects.get(user=self.user, ended_at__isnull=True)
        self.item = one_question_lesson(self.user)

    def submit(self, item=None, answer=None, request_id=None, **kwargs):
        item = item or self.item
        return services.submit_answer(self.user, item.session_id, 1, answer or item.question.correct_answer,
            request_id or uuid.uuid4(), platform_session_uuid=self.login.pk, **kwargs)

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json')

    def test_both_subjects_types_and_difficulties_award_actual_points(self):
        total = 0
        for subject in ['python', 'sql']:
            for kind in ['multiple_choice', 'fill_blank']:
                for difficulty, amount in [('beginner', 20), ('intermediate', 50), ('advanced', 80)]:
                    with self.subTest(subject=subject, kind=kind, difficulty=difficulty):
                        item = one_question_lesson(self.user, subject, kind, difficulty)
                        choice = item.question.choices.get(choice_text=item.question.correct_answer) if kind == 'multiple_choice' else None
                        result = self.submit(item, choice_uuid=choice.choice_uuid if choice else None)
                        total += amount
                        response = services.answer_payload(result)
                        self.assertEqual(response['points']['status'], 'granted')
                        self.assertEqual(response['points']['granted_points'], amount)
                        self.assertEqual(response['points']['balance_after'], total)
                        ledger = PointLedger.objects.get(answer=result)
                        quiz = EventOutbox.objects.get(event_type='quiz_answered', raw_data__attempt_uuid=str(result.attempt_uuid))
                        point = EventOutbox.objects.get(event_type='point_granted', raw_data__attempt_uuid=str(result.attempt_uuid))
                        self.assertEqual(quiz.payload_json['raw_manifest']['schema_version'], '1.1')
                        self.assertEqual(point.payload_json['raw_manifest']['schema_version'], '1.0')
                        self.assertEqual(quiz.raw_data['question_type'], kind.upper())
                        self.assertEqual(quiz.raw_data['question_uuid'], str(item.question.question_uuid))
                        self.assertEqual(quiz.raw_data['choice_uuid'], str(choice.choice_uuid) if choice else None)
                        self.assertEqual(point.raw_data['ledger_uuid'], str(ledger.pk))
                        self.assertEqual(point.raw_data['balance_after'], total)
                        self.assertEqual(str(quiz.message_key), str(Profile.objects.get(user=self.user).user_uuid))
                        self.assertNotIn('submitted_answer', quiz.raw_data)
                        self.assertNotIn('submission_request_uuid', quiz.raw_data)
        self.assertEqual(wallet_balance(self.user), 600)
        self.assertEqual(PointLedger.objects.count(), 12)
        self.assertEqual(EventOutbox.objects.filter(topic='raw.points').count(), 12)

    def test_wrong_then_retry_has_two_quiz_logs_and_only_one_grant(self):
        wrong = self.submit(answer='wrong')
        self.assertEqual(services.answer_payload(wrong)['points']['status'], 'not_eligible')
        self.assertEqual(wallet_balance(self.user), 0)
        result = self.submit()
        self.assertEqual(result.attempt_no, 2)
        self.assertEqual(wallet_balance(self.user), 20)
        self.assertEqual(EventOutbox.objects.filter(event_type='quiz_answered').count(), 2)
        self.assertEqual(EventOutbox.objects.filter(event_type='point_granted').count(), 1)
        self.assertEqual(PointLedger.objects.count(), 1)

    def test_retry_after_completion_returns_original_receipt_without_repaying(self):
        key = uuid.uuid4()
        result = self.submit(request_id=key)
        frozen = services.answer_payload(result)
        frozen_events = list(EventOutbox.objects.values_list('event_uuid', 'payload_json'))
        services.complete_session(self.user, self.item.session_id)
        self.submit(one_question_lesson(self.user, difficulty='advanced'))
        with override_settings(LEARNING_POINTS_BY_DIFFICULTY={'beginner': 999}):
            replay = self.submit(request_id=key)
        self.assertEqual(services.answer_payload(replay), frozen)
        self.assertEqual(wallet_balance(self.user), 100)
        self.assertEqual(UserAnswer.objects.count(), 2)
        self.assertEqual(PointLedger.objects.count(), 2)
        for identifier, payload in frozen_events:
            self.assertEqual(EventOutbox.objects.get(pk=identifier).payload_json, payload)

    def test_changed_body_with_same_request_id_is_conflict(self):
        key = uuid.uuid4()
        self.submit(request_id=key)
        for item, answer in [(self.item, 'different'), (one_question_lesson(self.user), 'append')]:
            with self.assertRaises(services.LearningError) as raised:
                self.submit(item, answer=answer, request_id=key)
            self.assertEqual(raised.exception.code, 'submission_uuid_conflict')
        self.assertEqual(PointLedger.objects.count(), 1)

    def test_request_id_is_scoped_to_owner(self):
        key = uuid.uuid4()
        first = self.submit(request_id=key)
        other = get_user_model().objects.create_user(username='other-point-learner')
        prepare_event_context(other)
        item = one_question_lesson(other)
        second = services.submit_answer(other, item.session_id, 1, 'append', key)
        self.assertNotEqual(first.attempt_uuid, second.attempt_uuid)
        self.assertEqual(PointLedger.objects.count(), 2)
        self.assertEqual(wallet_balance(other), 20)

    def assert_rolled_back(self):
        self.assertEqual(wallet_balance(self.user), 0)
        self.assertEqual(UserAnswer.objects.count(), 0)
        self.assertEqual(PointLedger.objects.count(), 0)
        self.assertFalse(EventOutbox.objects.filter(event_type__in=['quiz_answered', 'point_granted']).exists())
        self.item.session.refresh_from_db()
        self.assertEqual(self.item.session.correct_count, 0)

    def test_outbox_failure_rolls_back_answer_wallet_ledger_and_score(self):
        def enqueue(event_type, *args, **kwargs):
            if event_type == 'point_granted':
                raise RuntimeError('simulated outbox failure')
            return enqueue_event(event_type, *args, **kwargs)
        with patch('learning.services.enqueue_event', side_effect=enqueue):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_rolled_back()

    def test_ledger_failure_rolls_back_wallet_and_quiz_event(self):
        with patch.object(PointLedger.objects, 'create', side_effect=IntegrityError('simulated grant failure')):
            with self.assertRaises(IntegrityError):
                self.submit()
        self.assert_rolled_back()

    def test_response_snapshot_failure_rolls_back_all_changes(self):
        with patch('learning.services.answer_payload', side_effect=RuntimeError('simulated snapshot failure')):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_rolled_back()

    def test_choice_uuid_must_belong_to_question_and_match_answer(self):
        item = one_question_lesson(self.user, kind='multiple_choice')
        other = one_question_lesson(self.user, kind='multiple_choice')
        foreign = other.question.choices.get(choice_text='append')
        for choice in [foreign, item.question.choices.get(choice_text='wrong')]:
            with self.assertRaises(services.LearningError):
                self.submit(item, choice_uuid=choice.choice_uuid)
        with self.assertRaises(services.LearningError):
            self.submit(choice_uuid=foreign.choice_uuid)
        self.assert_rolled_back()

    def test_missing_or_non_v4_http_request_id_is_rejected(self):
        self.client.force_login(self.user)
        path = f'/api/learning/sessions/{self.item.session_id}/questions/1/answers/'
        for key in [None, str(uuid.uuid1()), 'invalid', str(uuid.uuid4()).upper()]:
            data = {'answer': 'append'}
            if key is not None:
                data['submission_request_uuid'] = key
            response = self.post(path, data)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error'], 'invalid_submission_uuid')
        self.assert_rolled_back()

    def test_actual_login_session_is_used_when_resuming_an_old_lesson(self):
        self.client.force_login(self.user)
        response = self.post(f'/api/learning/sessions/{self.item.session_id}/questions/1/answers/',
            {'answer': 'append', 'submission_request_uuid': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 201)
        active = self.client.session['platform_session_uuid']
        result = UserAnswer.objects.get()
        self.assertEqual(str(result.platform_session_id), active)
        for row in EventOutbox.objects.filter(event_type__in=['quiz_answered', 'point_granted']):
            self.assertEqual(row.raw_data['session_uuid'], active)

    def test_expired_or_foreign_login_cannot_award_points(self):
        self.login.ended_at = timezone.now()
        self.login.save(update_fields=['ended_at'])
        with self.assertRaises(services.LearningError) as error:
            self.submit()
        self.assertEqual(error.exception.status, 401)
        self.assert_rolled_back()

    def test_content_open_records_catalog_classification_before_display(self):
        self.client.force_login(self.user)
        for subject in ['python', 'sql']:
            for kind in ['multiple_choice', 'fill_blank']:
                response = self.post('/api/learning/content-open/', {'subject': subject, 'question_type': kind})
                self.assertEqual(response.status_code, 201)
                content_id = response.json()['content_uuid']
                row = EventOutbox.objects.get(event_type='content_open_requested', raw_data__content_uuid=content_id)
                self.assertEqual(row.raw_data['domain'], 'LEARNING')
                self.assertEqual(row.raw_data['content_kind'], 'QUIZ')
                self.assertEqual(row.raw_data['action'], 'OPEN_REQUESTED')
                self.assertIsNotNone(row.raw_data['zone_uuid'])
        self.assertEqual(self.client.get('/api/learning/wallet/').json(), {'balance': 0})
        self.assertFalse(EventOutbox.objects.filter(event_type='quiz_answered').exists())

    def test_wallet_query_does_not_pay_old_answers_or_emit_events(self):
        UserAnswer.objects.create(session_question=self.item, submitted_answer='append', is_correct=True)
        before = EventOutbox.objects.count()
        self.client.force_login(self.user)
        self.client.get('/api/learning/csrf/')
        before = EventOutbox.objects.count()
        for _ in range(2):
            self.assertEqual(self.client.get('/api/learning/wallet/').json()['balance'], 0)
            result = self.client.get(f'/api/learning/sessions/{self.item.session_id}/').json()
            self.assertEqual(result['points_summary']['granted_total'], 0)
            self.assertEqual(result['points_summary']['unpaid_legacy_count'], 1)
        self.assertEqual(EventOutbox.objects.count(), before)
        self.assertFalse(PointLedger.objects.exists())

    def test_zero_reward_setting_does_not_emit_a_zero_delta_grant(self):
        with override_settings(LEARNING_POINTS_BY_DIFFICULTY={'beginner': 0}):
            result = self.submit()
        self.assertEqual(services.answer_payload(result)['points']['status'], 'no_reward')
        self.assertEqual(EventOutbox.objects.filter(event_type='quiz_answered').count(), 1)
        self.assertFalse(PointLedger.objects.exists())
        self.assertFalse(EventOutbox.objects.filter(event_type='point_granted').exists())

    def test_signup_creates_exactly_one_zero_balance_wallet(self):
        response = self.client.post('/accounts/signup/', {'username': 'new-point-user', 'cohort': 'mlo-1',
            'password1': 'SamplePass!94123', 'password2': 'SamplePass!94123'})
        self.assertEqual(response.status_code, 302)
        profile = Profile.objects.get(user__username='new-point-user')
        self.assertEqual(PointWallet.objects.get(profile=profile).balance, 0)
        ensure_wallet(profile.user)
        self.assertEqual(PointWallet.objects.filter(profile=profile).count(), 1)
        self.assertFalse(PointLedger.objects.exists())

    def test_numeric_and_question_type_contracts_are_strict(self):
        identity = raw_identity(self.user, self.login.pk)
        quiz = {**identity, 'attempt_uuid': str(uuid.uuid4()), 'question_uuid': str(uuid.uuid4()),
                'content_uuid': str(uuid.uuid4()), 'question_type': 'FILL_BLANK', 'choice_uuid': None, 'is_correct': False}
        validate_raw_data('quiz_answered', quiz)
        for changed in [{'is_correct': 1}, {'choice_uuid': str(uuid.uuid4())}, {'question_type': 'MULTIPLE_CHOICE'}]:
            with self.assertRaises(ValueError):
                validate_raw_data('quiz_answered', {**quiz, **changed})
        grant = {**identity, 'ledger_uuid': str(uuid.uuid4()), 'attempt_uuid': str(uuid.uuid4()), 'delta': 20, 'balance_after': 20}
        for changed in [{'delta': 0}, {'delta': True}, {'delta': 1.5}, {'balance_after': -1}, {'balance_after': 2**63}]:
            with self.assertRaises(ValueError):
                validate_raw_data('point_granted', {**grant, **changed})
