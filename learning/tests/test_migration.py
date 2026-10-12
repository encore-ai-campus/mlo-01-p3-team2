from django.test import TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
class HistoricalMigrationTests(TransactionTestCase):
    def test_existing_integer_records_and_attempts_survive(self):
        executor=MigrationExecutor(connection);executor.migrate([('learning','0001_initial')])
        old=executor.loader.project_state([('learning','0001_initial')]).apps
        User=old.get_model('auth','User');Question=old.get_model('learning','Question');Session=old.get_model('learning','LearningSession');Item=old.get_model('learning','SessionQuestion');Answer=old.get_model('learning','UserAnswer')
        user=User.objects.create(username='migration-user')
        q=Question.objects.create(question_type='fill_blank',difficulty='beginner',category='python',question_text='list append',correct_answer='append',explanation='append')
        session=Session.objects.create(user_id=user.pk,question_type='fill_blank',difficulty='beginner',total_questions=1)
        item=Item.objects.create(session_id=session.pk,question_id=q.pk,question_order=1)
        answers=[Answer.objects.create(session_question_id=item.pk,submitted_answer='old',is_correct=False,attempt_no=n) for n in [1,4]]
        executor=MigrationExecutor(connection);executor.migrate([('learning','0002_subject_submission_identity')])
        new=executor.loader.project_state([('learning','0002_subject_submission_identity')]).apps
        self.assertEqual(new.get_model('learning','LearningSession').objects.get(pk=session.pk).subject,'python')
        self.assertEqual(new.get_model('learning','Question').objects.get(pk=q.pk).question_text,'list append')
        restored=list(new.get_model('learning','UserAnswer').objects.filter(pk__in=[a.pk for a in answers]).order_by('attempt_no'))
        self.assertEqual([a.attempt_no for a in restored],[1,4]);self.assertEqual(len({a.attempt_uuid for a in restored}),2)
        self.assertTrue(all(a.submitted_answer=='old' for a in restored))
