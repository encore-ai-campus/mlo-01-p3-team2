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
from learning.models import Question, LearningSession, UserAnswer


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

    def test_four_concurrent_wrong_answers_stop_at_three(self):
        def submit(user):
            try:
                return services.submit_answer(user, self.session.pk, 1, 'wrong', uuid.uuid4()).attempt_no
            except services.LearningError as error:
                return error.status
        self.assertEqual(sorted(self.parallel([submit]*4)), [1, 2, 3, 409])
        self.assertEqual(UserAnswer.objects.count(), 3)

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
