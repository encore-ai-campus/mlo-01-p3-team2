import uuid
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from .legacy_fixtures import prepare_event_context


class HistoricalMigrationTests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        self.leaves = executor.loader.graph.leaf_nodes()
        prepare_event_context(get_user_model().objects.create_user(username='migration-catalog-seed'))

    def tearDown(self):
        # Always restore the current schema before the runner flushes the DB or
        # another test uses current models, including when an assertion fails.
        MigrationExecutor(connection).migrate(self.leaves)
        super().tearDown()

    def state(self, name):
        executor = MigrationExecutor(connection)
        targets = [('learning', name), ('accounts', '0006_activelogin'), ('eventing', '0007_learning_catalog')]
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_existing_integer_records_and_attempts_survive(self):
        old = self.state('0001_initial')
        User = old.get_model('auth', 'User')
        Question = old.get_model('learning', 'Question')
        Session = old.get_model('learning', 'LearningSession')
        Item = old.get_model('learning', 'SessionQuestion')
        Answer = old.get_model('learning', 'UserAnswer')
        user = User.objects.create(username='migration-user')
        question = Question.objects.create(question_type='fill_blank', difficulty='beginner', category='python',
            question_text='list append', correct_answer='append', explanation='append')
        session = Session.objects.create(user_id=user.pk, question_type='fill_blank', difficulty='beginner', total_questions=1)
        item = Item.objects.create(session_id=session.pk, question_id=question.pk, question_order=1)
        answers = [Answer.objects.create(session_question_id=item.pk, submitted_answer='old', is_correct=False, attempt_no=n) for n in [1, 4]]
        new = self.state('0002_subject_submission_identity')
        self.assertEqual(new.get_model('learning', 'LearningSession').objects.get(pk=session.pk).subject, 'python')
        self.assertEqual(new.get_model('learning', 'Question').objects.get(pk=question.pk).question_text, 'list append')
        restored = list(new.get_model('learning', 'UserAnswer').objects.filter(pk__in=[a.pk for a in answers]).order_by('attempt_no'))
        self.assertEqual([a.attempt_no for a in restored], [1, 4])
        self.assertEqual(len({a.attempt_uuid for a in restored}), 2)
        identities = [a.attempt_uuid for a in restored]
        latest = self.state('0003_learning_events_points')
        self.assertEqual(list(latest.get_model('learning', 'UserAnswer').objects.filter(pk__in=[a.pk for a in answers])
            .order_by('attempt_no').values_list('attempt_uuid', flat=True)), identities)
        self.assertTrue(all(a.submitted_answer == 'old' for a in restored))

    def test_upgrade_adds_unique_ids_preserves_receipts_and_does_not_backpay(self):
        old = self.state('0002_subject_submission_identity')
        User = old.get_model('auth', 'User')
        Profile = old.get_model('accounts', 'Profile')
        Question = old.get_model('learning', 'Question')
        Choice = old.get_model('learning', 'QuestionChoice')
        Session = old.get_model('learning', 'LearningSession')
        Item = old.get_model('learning', 'SessionQuestion')
        Answer = old.get_model('learning', 'UserAnswer')
        user = User.objects.create(username='upgrade-point-user')
        identity = uuid.uuid4()
        Profile.objects.create(user_id=user.pk, user_uuid=identity, nickname='기존 유저')
        question = Question.objects.create(subject='sql', question_type='multiple_choice', difficulty='advanced',
            category='query', question_text='Old SQL question', correct_answer='SELECT')
        choices = [Choice.objects.create(question_id=question.pk, choice_no=n, choice_text=text)
                   for n, text in enumerate(['SELECT', 'wrong', 'other', 'none'], 1)]
        session = Session.objects.create(user_id=user.pk, subject='sql', question_type='multiple_choice', difficulty='advanced', total_questions=1)
        item = Item.objects.create(session_id=session.pk, question_id=question.pk, question_order=1)
        snapshot = {'is_correct': True, 'points': {'status': 'not_connected', 'quoted_points': 80}}
        answer = Answer.objects.create(session_question_id=item.pk, submitted_answer='SELECT', is_correct=True,
            submission_request_uuid=uuid.uuid4(), response_snapshot=snapshot)
        before_events = old.get_model('eventing', 'EventOutbox').objects.count()
        latest = self.state('0003_learning_events_points')
        restored = latest.get_model('learning', 'UserAnswer').objects.get(pk=answer.pk)
        self.assertEqual(restored.attempt_uuid, answer.attempt_uuid)
        self.assertEqual(restored.submission_request_uuid, answer.submission_request_uuid)
        self.assertEqual(restored.response_snapshot, snapshot)
        self.assertEqual(restored.user_id, user.pk)
        self.assertEqual(restored.selected_choice_id, choices[0].pk)
        self.assertIsNone(restored.platform_session_id)
        self.assertIsNotNone(restored.content_id)
        current_question = latest.get_model('learning', 'Question').objects.get(pk=question.pk)
        current_choices = latest.get_model('learning', 'QuestionChoice').objects.filter(question_id=question.pk)
        self.assertEqual(current_question.question_uuid.version, 4)
        self.assertEqual(set(current_choices.values_list('pk', flat=True)), {c.pk for c in choices})
        self.assertEqual(len(set(current_choices.values_list('choice_uuid', flat=True))), 4)
        self.assertTrue(all(c.choice_uuid.version == 4 for c in current_choices))
        self.assertEqual(latest.get_model('learning', 'PointWallet').objects.get(profile_id=identity).balance, 0)
        self.assertEqual(latest.get_model('learning', 'PointLedger').objects.count(), 0)
        self.assertEqual(latest.get_model('eventing', 'EventOutbox').objects.count(), before_events)
