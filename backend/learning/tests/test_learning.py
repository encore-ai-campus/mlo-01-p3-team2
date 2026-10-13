import uuid
from .legacy_fixtures import start_legacy_session
import json
from io import StringIO
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, Client
from learning.models import Question, QuestionChoice, LearningSession, SessionQuestion, UserAnswer
from learning import services


def make_question(kind='fill_blank', difficulty='beginner', number=0, active=True):
    q = Question.objects.create(question_type=kind, difficulty=difficulty, category='list',
                                question_text=f'문제 {number}', correct_answer='append' if kind == 'fill_blank' else 'append()',
                                code_snippet='numbers.____(4)', explanation='리스트 끝에 추가합니다.', is_active=active)
    if kind == 'multiple_choice':
        for n, text in enumerate(['add()', 'append()', 'push()', 'insertLast()'], 1):
            QuestionChoice.objects.create(question=q, choice_no=n, choice_text=text)
    return q


class ModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='model')
        self.q = make_question()
        self.session = LearningSession.objects.create(user=self.user, question_type='fill_blank', difficulty='beginner')
        self.item = SessionQuestion.objects.create(session=self.session, question=self.q, question_order=1)

    def assert_db_rejects(self, model, **fields):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.bulk_create([model(**fields)])

    def test_question_and_choices(self):
        q = make_question('multiple_choice')
        services.validate_question(q)
        self.assertEqual(q.choices.count(), 4)
        self.assert_db_rejects(QuestionChoice, question=q, choice_no=5, choice_text='bad')
        self.assert_db_rejects(QuestionChoice, question=q, choice_no=0, choice_text='bad')
        self.assert_db_rejects(QuestionChoice, question=q, choice_no=1, choice_text='duplicate')

    def test_blank_cannot_have_choices(self):
        with self.assertRaises(ValidationError):
            QuestionChoice.objects.create(question=self.q, choice_no=1, choice_text='append')

    def test_choice_count_validation(self):
        q = Question.objects.create(question_type='multiple_choice', difficulty='beginner', category='list', question_text='x', correct_answer='x')
        with self.assertRaises(ValidationError):
            services.validate_question(q)

    def test_session_uniqueness(self):
        self.assert_db_rejects(SessionQuestion, session=self.session, question=self.q, question_order=2)
        other = make_question(number=1)
        self.assert_db_rejects(SessionQuestion, session=self.session, question=other, question_order=1)

    def test_order_range(self):
        for order in (0, 11):
            self.assert_db_rejects(SessionQuestion, session=self.session, question=make_question(number=order), question_order=order)

    def test_attempt_constraints(self):
        UserAnswer.objects.create(session_question=self.item, submitted_answer='wrong', is_correct=False, attempt_no=1)
        self.assert_db_rejects(UserAnswer, session_question=self.item, submitted_answer='append', is_correct=True, attempt_no=1)
        self.assert_db_rejects(UserAnswer, session_question=self.item, submitted_answer='append', is_correct=True, attempt_no=0)

    def test_mismatched_question(self):
        for q in [make_question('multiple_choice'), make_question(difficulty='advanced')]:
            with self.assertRaises(ValidationError):
                SessionQuestion.objects.create(session=self.session, question=q, question_order=2)

    def test_used_question_immutable(self):
        self.q.correct_answer = 'changed'
        with self.assertRaises(ValidationError):
            self.q.save()
        self.q.refresh_from_db()
        self.q.is_active = False
        self.q.save()
        self.assertFalse(self.q.is_active)

    def test_used_choice_immutable(self):
        q = make_question('multiple_choice')
        s = LearningSession.objects.create(user=self.user, question_type='multiple_choice', difficulty='beginner')
        SessionQuestion.objects.create(session=s, question=q, question_order=1)
        c = q.choices.first()
        c.choice_text = 'changed'
        with self.assertRaises(ValidationError):
            c.save()
        with self.assertRaises(ProtectedError):
            q.delete()

    def test_session_type_immutable(self):
        self.session.difficulty = 'advanced'
        with self.assertRaises(ValidationError):
            self.session.save()

    def test_used_choice_delete_blocked(self):
        q = make_question('multiple_choice')
        s = LearningSession.objects.create(user=self.user, question_type='multiple_choice', difficulty='beginner')
        SessionQuestion.objects.create(session=s, question=q, question_order=1)
        with self.assertRaises(ValidationError):
            q.choices.all().delete()

    def test_answer_is_append_only(self):
        a = UserAnswer.objects.create(session_question=self.item, submitted_answer='append', is_correct=True)
        with self.assertRaises(ValidationError):
            a.save()
        with self.assertRaises(ValidationError):
            a.delete()

    def test_invalid_enums_db(self):
        self.assert_db_rejects(Question, question_type='unknown', difficulty='beginner', category='x', question_text='x', correct_answer='x')


class ServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='service')

    def test_random_ten_and_filters(self):
        for n in range(12):
            make_question(number=n)
        make_question('multiple_choice')
        make_question(difficulty='advanced')
        make_question(active=False)
        s = services.start_learning_session(self.user, 'fill_blank', 'beginner')
        items = list(s.session_questions.all())
        self.assertEqual(s.total_questions, 10)
        self.assertEqual(len(set(i.question_id for i in items)), 10)
        self.assertEqual([i.question_order for i in items], list(range(1, 11)))
        self.assertTrue(all(i.started_at is None for i in items))
        self.assertTrue(all(i.question.question_type == 'fill_blank' and i.question.difficulty == 'beginner' and i.question.is_active for i in items))

    def test_fewer_questions(self):
        for n in range(3):
            make_question(number=n)
        with self.assertRaises(services.LearningError) as error:
            services.start_learning_session(self.user, 'fill_blank', 'beginner')
        self.assertEqual(error.exception.code, 'insufficient_question_pool')
        self.assertFalse(LearningSession.objects.exists())

    def test_zero_and_invalid(self):
        for kind, level in [('fill_blank', 'beginner'), ('bad', 'beginner'), ('fill_blank', 'bad')]:
            with self.assertRaises(services.LearningError):
                services.start_learning_session(self.user, kind, level)
        self.assertEqual(LearningSession.objects.count(), 0)

    def test_invalid_pool_rolls_back(self):
        for n in range(10):
            Question.objects.create(question_type='multiple_choice', difficulty='beginner', category='list', question_text=f'invalid {n}', correct_answer='x')
        with self.assertRaises(ValidationError):
            services.start_learning_session(self.user, 'multiple_choice', 'beginner')
        self.assertFalse(LearningSession.objects.exists())

    def test_view_retry_complete(self):
        make_question()
        s = start_legacy_session(self.user, 'fill_blank', 'beginner')
        with self.assertRaises(services.LearningError):
            services.submit_answer(self.user, s.pk, 1, 'append')
        first = services.get_current_question(self.user, s.pk, 1).started_at
        self.assertEqual(services.get_current_question(self.user, s.pk, 1).started_at, first)
        a = services.submit_answer(self.user, s.pk, 1, 'add')
        b = services.submit_answer(self.user, s.pk, 1, ' append ')
        with self.assertRaises(services.LearningError):
            services.submit_answer(self.user, s.pk, 1, 'APPEND')
        self.assertFalse(a.is_correct)
        self.assertTrue(b.is_correct)
        self.assertEqual([a.attempt_no, b.attempt_no], [1, 2])
        self.assertEqual(UserAnswer.objects.count(), 2)
        s = services.complete_session(self.user, s.pk)
        self.assertEqual(s.correct_count, 1)
        self.assertIsNotNone(s.completed_at)
        self.assertEqual(services.complete_session(self.user, s.pk).completed_at, s.completed_at)
        with self.assertRaises(services.LearningError):
            services.submit_answer(self.user, s.pk, 1, 'append')

    def test_unanswered_blocks_completion(self):
        make_question()
        s = start_legacy_session(self.user, 'fill_blank', 'beginner')
        with self.assertRaises(services.LearningError):
            services.complete_session(self.user, s.pk)
        s.refresh_from_db()
        self.assertIsNone(s.completed_at)

    def test_mcq_judgment(self):
        make_question('multiple_choice')
        s = start_legacy_session(self.user, 'multiple_choice', 'beginner')
        services.get_current_question(self.user, s.pk, 1)
        self.assertFalse(services.submit_answer(self.user, s.pk, 1, 'add()').is_correct)
        self.assertTrue(services.submit_answer(self.user, s.pk, 1, 'append()').is_correct)
        with self.assertRaises(services.LearningError):
            services.submit_answer(self.user, s.pk, 1, 'not a choice')

    def test_seed_idempotent(self):
        call_command('seed_learning_questions', stdout=StringIO())
        call_command('seed_learning_questions', stdout=StringIO())
        self.assertEqual(Question.objects.filter(question_type='multiple_choice').count(), 10)
        self.assertEqual(Question.objects.filter(question_type='fill_blank').count(), 10)
        self.assertEqual(QuestionChoice.objects.count(), 40)


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='api', password='test-password')
        self.other = get_user_model().objects.create_user(username='other')
        make_question('multiple_choice')
        make_question('fill_blank')
        self.client.force_login(self.user)

    def post(self, path, data):
        if path.endswith('/answers/') and isinstance(data, dict):
            data = {**data, 'submission_request_uuid': str(uuid.uuid4())}
        return self.client.post(path, data=json.dumps(data), content_type='application/json')

    def start(self, kind):
        for n in range(10 - Question.objects.filter(question_type=kind, difficulty='beginner').count()):
            make_question(kind, number=100+n)
        response = self.post('/api/learning/sessions/', {'question_type': kind, 'difficulty': 'beginner'})
        self.assertEqual(response.status_code, 201)
        return response.json()['session_id']

    def test_mcq_response_no_secret(self):
        sid = self.start('multiple_choice')
        response = self.client.get(f'/api/learning/sessions/{sid}/questions/1/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('correct_answer', response.content.decode())
        self.assertNotIn('explanation', response.json()['question'])
        self.assertEqual(len(response.json()['question']['choices']), 4)

    def test_blank_flow_and_result(self):
        sid = self.start('fill_blank')
        base = f'/api/learning/sessions/{sid}/'
        response = self.client.get(base + 'questions/1/')
        self.assertNotIn('choices', response.json()['question'])
        self.assertNotIn('correct_answer', response.content.decode())
        for text, correct in [('add', False), (' append ', True)]:
            answer = self.post(base + 'questions/1/answers/', {'answer': text})
            self.assertEqual(answer.status_code, 201)
            self.assertEqual(answer.json()['is_correct'], correct)
        for order in range(2, 11):
            self.client.get(base + f'questions/{order}/')
            self.post(base + f'questions/{order}/answers/', {'answer':'append'})
        result = self.post(base + 'complete/', {})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['correct_count'], 10)
        self.assertEqual(result.json()['accuracy'], 100)
        self.assertEqual(result.json()['unanswered_count'], 0)

    def test_ownership_all_endpoints(self):
        sid = self.start('fill_blank')
        self.client.force_login(self.other)
        base = f'/api/learning/sessions/{sid}/'
        for path in [base, base + 'questions/1/']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(base + 'questions/1/answers/', {'answer': 'append'}).status_code, 404)
        self.assertEqual(self.post(base + 'complete/', {}).status_code, 404)

    def test_anonymous(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/learning/sessions/1/').status_code, 401)
        self.assertEqual(self.post('/api/learning/sessions/', {}).status_code, 401)

    def test_invalid_requests(self):
        url = '/api/learning/sessions/'
        for value in [None, [], {'question_type': [], 'difficulty': 'beginner'}]:
            self.assertEqual(self.post(url, value).status_code, 400)
        self.assertEqual(self.client.post(url, data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, data='x', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_invalid_answer_and_missing_question(self):
        sid = self.start('fill_blank')
        base = f'/api/learning/sessions/{sid}/questions/'
        self.assertEqual(self.client.get(base + '11/').status_code, 404)
        self.client.get(base + '1/')
        for answer in [None, 1, [], '', ' ', 'a' * 10001]:
            self.assertEqual(self.post(base + '1/answers/', {'answer': answer}).status_code, 400)

    def test_csrf_enforced(self):
        for n in range(9):make_question(number=200+n)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = '/api/learning/sessions/'
        self.assertEqual(client.post(url, data='{}', content_type='application/json').status_code, 403)
        self.assertEqual(client.get('/api/learning/csrf/').status_code, 200)
        token = client.cookies['campus_csrftoken'].value
        response = client.post(url, data=json.dumps({'question_type': 'fill_blank', 'difficulty': 'beginner'}),
                               content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)

    def test_ten_question_session_end_to_end(self):
        call_command('seed_learning_questions', stdout=StringIO())
        sid = self.start('fill_blank')
        base = f'/api/learning/sessions/{sid}/'
        self.assertEqual(self.client.get(base).json()['unanswered_count'], 10)
        self.assertEqual(self.post(base + 'complete/', {}).status_code, 409)
        for order in range(1, 11):
            url = base + f'questions/{order}/'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            qid = response.json()['question']['question_id']
            expected = Question.objects.get(pk=qid).correct_answer
            response = self.post(url + 'answers/', {'answer': expected})
            self.assertEqual(response.status_code, 201)
        result = self.post(base + 'complete/', {})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['correct_count'], 10)
        self.assertEqual(result.json()['answered_count'], 10)
        self.assertIsNotNone(result.json()['completed_at'])
        self.assertEqual(UserAnswer.objects.filter(session_question__session_id=sid).count(), 10)

    def test_empty_pool_error(self):
        response = self.post('/api/learning/sessions/', {'question_type': 'fill_blank', 'difficulty': 'advanced'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'empty_question_pool')
