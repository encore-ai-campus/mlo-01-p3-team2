import os
import sqlite3
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, OperationalError
from django.test import TransactionTestCase, SimpleTestCase, RequestFactory
from learning import services, views
from learning.models import Question, LearningSession, UserAnswer, PointLedger
from learning.point_integration import wallet_balance
from eventing.models import EventOutbox
from .legacy_fixtures import prepare_event_context


class LockDiagnosticsTests(SimpleTestCase):
    def test_safe_log_and_503(self):
        request = RequestFactory().get('/api/learning/sessions/123/?answer=SECRET')
        request.user = type('User', (), {'is_authenticated': True})()
        request.resolver_match = type('Match', (), {'route': 'api/learning/sessions/<int:session_id>/'})()
        @views.endpoint('GET')
        def failing(request):
            raise OperationalError('database is locked SECRET')
        with self.assertLogs('learning.views', level='WARNING') as captured:
            response = failing(request)
        self.assertEqual(response.status_code, 503)
        text = ' '.join(captured.output)
        self.assertIn('pid=', text)
        self.assertIn('OperationalError', text)
        self.assertIn('api/learning/sessions/<int:session_id>/', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('123', text.split('path=')[1].split(' pid=')[0])

    def test_non_lock_errors_are_not_swallowed(self):
        request = RequestFactory().get('/')
        request.user = type('User', (), {'is_authenticated': True})()
        @views.endpoint('GET')
        def failing(request):
            raise OperationalError('disk I/O error')
        with self.assertRaises(OperationalError):
            failing(request)

    def test_old_deferred_read_then_write_lock_reproduction(self):
        # Independent disposable file; never touches a project/server database.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'lock.sqlite3')
            a, b = sqlite3.connect(path, timeout=.1), sqlite3.connect(path, timeout=.1)
            try:
                a.execute('CREATE TABLE records (value INTEGER)')
                a.execute('INSERT INTO records VALUES (0)'); a.commit()
                for conn in [a, b]:
                    conn.execute('BEGIN'); conn.execute('SELECT * FROM records').fetchall()
                a.execute('UPDATE records SET value=1')
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    b.execute('UPDATE records SET value=2')
            finally:
                a.rollback(); b.rollback(); a.close(); b.close()


class LearningConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'sqlite' or 'memory' in str(connection.settings_dict['NAME']):
            self.skipTest('Requires a disposable file-backed SQLite test database')
        self.user = get_user_model().objects.create_user(username='concurrency')
        prepare_event_context(self.user)
        for n in range(10):
            Question.objects.create(subject='sql', question_type='fill_blank', difficulty='beginner',
                                    category='concept', question_text=f'query {n}', correct_answer='SELECT')
        self.session = services.start_learning_session(self.user, 'fill_blank', 'beginner', 'sql')
        services.get_current_question(self.user, self.session.pk, 1)

    def parallel(self, functions):
        barrier = threading.Barrier(len(functions))
        def run(fn):
            connections.close_all()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                return fn(user)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(run, fn) for fn in functions]
            return [f.result(timeout=20) for f in futures]

    def test_duplicate_uuid_creates_one_answer_and_same_snapshot(self):
        key = uuid.uuid4()
        def submit(user):
            return services.answer_payload(services.submit_answer(user, self.session.pk, 1, 'SELECT', key))
        results = self.parallel([submit, submit])
        self.assertEqual(results[0], results[1])
        self.assertEqual(UserAnswer.objects.count(), 1)
        self.session.refresh_from_db(); self.assertEqual(self.session.correct_count, 1)
        self.assertEqual(PointLedger.objects.count(), 1)
        self.assertEqual(wallet_balance(self.user), 20)
        self.assertEqual(EventOutbox.objects.filter(event_type='quiz_answered').count(), 1)
        self.assertEqual(EventOutbox.objects.filter(event_type='point_granted').count(), 1)

    def test_four_concurrent_wrong_answers_stop_at_three(self):
        def submit(user):
            try:
                return services.submit_answer(user, self.session.pk, 1, 'wrong', uuid.uuid4()).attempt_no
            except services.LearningError as error:
                return error.status
        self.assertEqual(sorted(self.parallel([submit]*4)), [1, 2, 3, 409])
        self.assertEqual(UserAnswer.objects.count(), 3)
        self.assertEqual(wallet_balance(self.user), 0)
        self.assertEqual(EventOutbox.objects.filter(event_type='quiz_answered').count(), 3)
        self.assertEqual(PointLedger.objects.count(), 0)

    def test_different_lessons_share_one_locked_wallet_without_lost_update(self):
        other = services.start_learning_session(self.user, 'fill_blank', 'beginner', 'sql')
        services.get_current_question(self.user, other.pk, 1)
        def first(user):
            return services.submit_answer(user, self.session.pk, 1, 'SELECT', uuid.uuid4()).pk
        def second(user):
            return services.submit_answer(user, other.pk, 1, 'SELECT', uuid.uuid4()).pk
        ids = self.parallel([first, second])
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(wallet_balance(self.user), 40)
        self.assertEqual(sorted(PointLedger.objects.values_list('balance_after', flat=True)), [20, 40])
        self.assertEqual(EventOutbox.objects.filter(event_type='point_granted').count(), 2)

    def test_same_owner_request_id_raced_across_lessons_creates_one_grant(self):
        other = services.start_learning_session(self.user, 'fill_blank', 'beginner', 'sql')
        services.get_current_question(self.user, other.pk, 1)
        key = uuid.uuid4()
        def submit(sid):
            def action(user):
                try:
                    services.submit_answer(user, sid, 1, 'SELECT', key)
                    return 'saved'
                except services.LearningError as error:
                    return error.code
            return action
        self.assertEqual(sorted(self.parallel([submit(self.session.pk), submit(other.pk)])), ['saved', 'submission_uuid_conflict'])
        self.assertEqual(UserAnswer.objects.count(), 1)
        self.assertEqual(PointLedger.objects.count(), 1)
        self.assertEqual(wallet_balance(self.user), 20)

    def test_first_question_view_timestamp_and_repeat_read_only(self):
        def view(user):
            return services.get_current_question(user, self.session.pk, 2).started_at
        timestamps = self.parallel([view, view])
        self.assertEqual(timestamps[0], timestamps[1])
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as captured:
            services.get_current_question(self.user, self.session.pk, 2)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('UPDATE', 'INSERT')) for q in captured))

    def test_concurrent_session_creation_keeps_ten_unique_questions(self):
        def start(user):
            return services.start_learning_session(user, 'fill_blank', 'beginner', 'sql').pk
        ids = self.parallel([start, start])
        self.assertNotEqual(ids[0], ids[1])
        for sid in ids:
            items = LearningSession.objects.get(pk=sid).session_questions.all()
            self.assertEqual(items.count(), 10)
            self.assertEqual(len(set(items.values_list('question_id', flat=True))), 10)
