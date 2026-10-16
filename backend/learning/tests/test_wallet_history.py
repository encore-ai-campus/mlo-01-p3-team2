import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import resolve
from django.utils import timezone

from eventing.events import get_profile
from eventing.models import EventOutbox
from learning import views
from learning.models import LearningSession, PointLedger, PointWallet, Question, SessionQuestion, UserAnswer


class WalletHistoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='history-owner')
        self.other = get_user_model().objects.create_user(username='history-other')
        get_profile(self.user)
        get_profile(self.other)
        self.factory = RequestFactory()

    def grant(self, user, number=1, subject='python', difficulty='beginner', amount=20):
        question = Question.objects.create(subject=subject, question_type='fill_blank', difficulty=difficulty,
            category='history', question_text='Complete the keyword', correct_answer='append')
        session = LearningSession.objects.create(user=user, subject=subject, question_type='fill_blank',
            difficulty=difficulty, total_questions=1)
        item = SessionQuestion.objects.create(session=session, question=question, question_order=1)
        answer = UserAnswer.objects.create(user=user, session_question=item, submitted_answer='append', is_correct=True)
        return PointLedger.objects.create(profile=get_profile(user), answer=answer, delta=amount, balance_after=number * amount)

    def request(self, cursor=None, user=None):
        request = self.factory.get('/api/learning/wallet/history/', {'cursor': cursor} if cursor is not None else {})
        request.user = user if user is not None else self.user
        response = views.wallet_history(request)
        return response, json.loads(response.content)

    def test_only_owner_records_are_returned_latest_first(self):
        old = self.grant(self.user)
        new = self.grant(self.user, subject='sql', difficulty='advanced', amount=80)
        self.grant(self.other)
        PointLedger.objects.filter(pk=old.pk).update(granted_at=timezone.now() - timedelta(days=1))
        with self.assertNumQueries(1):
            response, data = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual([row['ledger_uuid'] for row in data['items']], [str(new.pk), str(old.pk)])
        self.assertEqual(data['items'][0]['amount'], 80)
        self.assertEqual(data['items'][0]['subject'], 'sql')
        self.assertEqual(data['items'][0]['difficulty'], 'advanced')
        self.assertEqual(data['items'][0]['question_type'], 'fill_blank')
        self.assertEqual(set(data['items'][0]), {'ledger_uuid', 'amount', 'balance_after', 'granted_at',
            'subject', 'difficulty', 'question_type', 'question_order'})
        self.assertIsNone(data['next_cursor'])

    def test_empty_history_is_read_only_and_does_not_create_wallet_or_events(self):
        counts = [model.objects.count() for model in (PointWallet, PointLedger, UserAnswer, EventOutbox)]
        response, data = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {'items': [], 'next_cursor': None})
        self.assertEqual([model.objects.count() for model in (PointWallet, PointLedger, UserAnswer, EventOutbox)], counts)

    def test_existing_history_reads_do_not_award_more_points(self):
        ledger = self.grant(self.user)
        wallet = PointWallet.objects.create(profile=ledger.profile, balance=ledger.delta)
        counts = [model.objects.count() for model in (PointLedger, UserAnswer, EventOutbox)]
        self.request()
        self.request()
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, ledger.delta)
        self.assertEqual([model.objects.count() for model in (PointLedger, UserAnswer, EventOutbox)], counts)

    def test_cursor_paging_handles_equal_timestamps_without_duplicates(self):
        timestamp = timezone.now() - timedelta(hours=1)
        ledgers = [self.grant(self.user, number=index + 1) for index in range(13)]
        PointLedger.objects.filter(pk__in=[ledger.pk for ledger in ledgers]).update(granted_at=timestamp)
        expected = list(PointLedger.objects.filter(profile__user=self.user)
            .order_by('-granted_at', '-ledger_uuid').values_list('ledger_uuid', flat=True))
        response, first = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(first['items']), 10)
        newer = self.grant(self.user, number=14)
        with self.assertNumQueries(2):
            response, second = self.request(first['next_cursor'])
        self.assertEqual(response.status_code, 200)
        ids = [row['ledger_uuid'] for row in first['items'] + second['items']]
        self.assertEqual(ids, [str(identifier) for identifier in expected])
        self.assertNotIn(str(newer.pk), ids)
        self.assertIsNone(second['next_cursor'])

    def test_malformed_missing_and_other_users_cursors_are_rejected(self):
        other = self.grant(self.other)
        for cursor in ['not-a-uuid', str(uuid.uuid4()), str(other.pk)]:
            with self.subTest(cursor=cursor):
                response, data = self.request(cursor)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('items', data)

    def test_login_and_get_only_route(self):
        response, data = self.request(user=AnonymousUser())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(data['error'], 'authentication_required')
        request = self.factory.post('/api/learning/wallet/history/')
        request.user = self.user
        response = views.wallet_history(request)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET')
        self.assertIs(resolve('/api/learning/wallet/history/').func, views.wallet_history)
