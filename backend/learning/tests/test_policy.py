import uuid
from .legacy_fixtures import start_legacy_session
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, OperationalError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from learning import services
from learning.models import LearningSession, UserAnswer, SessionQuestion
from .test_learning import make_question


class EvaluationPolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='policy')
        self.q = make_question()
        self.s = start_legacy_session(self.user, 'fill_blank', 'beginner')
        self.item = services.get_current_question(self.user, self.s.pk, 1)
        self.client.force_login(self.user)

    def submit(self, answer):
        return services.submit_answer(self.user, self.s.pk, 1, answer)

    def test_wrong_answers_disclose_only_when_finalized(self):
        url = f'/api/learning/sessions/{self.s.pk}/questions/1/answers/'
        for attempt in range(1, 4):
            response = self.client.post(url, json.dumps({'answer': 'wrong', 'submission_request_uuid': str(uuid.uuid4())}), content_type='application/json')
            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['answer_revealed'], attempt == 3)
            if attempt < 3:
                self.assertEqual(data['explanation'], '')
                self.assertNotIn('correct_answer', data)
            else:
                self.assertEqual(data['explanation'], self.q.explanation)
                self.assertEqual(data['correct_answer'], self.q.correct_answer)
            self.assertEqual(data['attempt_no'], attempt)

    def test_correct_answer_keeps_explanation(self):
        url = f'/api/learning/sessions/{self.s.pk}/questions/1/answers/'
        response = self.client.post(url, json.dumps({'answer': 'append', 'submission_request_uuid': str(uuid.uuid4())}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['explanation'], self.q.explanation)

    def test_first_try_correct(self):
        self.submit('append')
        self.assertEqual(services.question_progress(self.item)['outcome'], 'first_try_correct')

    def test_second_try_correct(self):
        self.submit('wrong')
        self.submit('append')
        self.assertEqual(services.question_progress(self.item)['outcome'], 'retry_correct')

    def test_third_try_correct(self):
        self.submit('wrong')
        self.submit('wrong')
        self.submit('append')
        self.assertEqual(services.question_progress(self.item)['outcome'], 'retry_correct')
        self.assertEqual(self.item.answers.count(), 3)

    def test_three_wrong_finalized(self):
        for _ in range(3):
            self.submit('wrong')
        p = services.question_progress(self.item)
        self.assertEqual(p['outcome'], 'incorrect')
        self.assertTrue(p['is_finalized'])
        self.assertEqual(p['remaining_attempts'], 0)

    def test_fourth_attempt_rejected(self):
        for _ in range(3):
            self.submit('wrong')
        with self.assertRaises(services.LearningError) as error:
            self.submit('append')
        self.assertEqual(error.exception.code, 'attempt_limit_reached')
        self.assertEqual(self.item.answers.count(), 3)

    def test_correct_rejects_further_answers(self):
        self.submit('append')
        with self.assertRaises(services.LearningError) as error:
            self.submit('wrong')
        self.assertEqual(error.exception.code, 'question_finalized')
        self.assertEqual(self.item.answers.count(), 1)

    def test_final_wrong_rejects_further_wrong(self):
        for _ in range(3):
            self.submit('wrong')
        with self.assertRaises(services.LearningError):
            self.submit('wrong')

    def test_answered_but_not_finalized_cannot_complete(self):
        self.submit('wrong')
        with self.assertRaises(services.LearningError) as error:
            services.complete_session(self.user, self.s.pk)
        self.assertEqual(error.exception.code, 'unfinalized_questions')
        self.s.refresh_from_db()
        self.assertIsNone(self.s.completed_at)

    def test_remaining_and_case_sensitivity(self):
        self.assertEqual(services.question_progress(self.item)['remaining_attempts'], 3)
        self.assertFalse(self.submit('APPEND').is_correct)
        self.assertEqual(services.question_progress(self.item)['remaining_attempts'], 2)
        self.submit('wrong')
        self.assertEqual(services.question_progress(self.item)['remaining_attempts'], 1)
        self.assertTrue(self.submit(' append ').is_correct)

    def test_wrong_can_complete_after_three(self):
        for _ in range(3):
            self.submit('wrong')
        completed = services.complete_session(self.user, self.s.pk)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.correct_count, 0)
        stats = services.session_statistics(completed)
        self.assertEqual(stats['final_incorrect_count'], 1)
        self.assertEqual(stats['final_accuracy'], 0)

    def test_api_progress_fields(self):
        url = f'/api/learning/sessions/{self.s.pk}/questions/1/'
        self.assertEqual(self.client.get(url).json()['max_attempts'], 3)
        response = self.client.post(url + 'answers/', data=json.dumps({'answer': 'wrong', 'submission_request_uuid': str(uuid.uuid4())}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['remaining_attempts'], 2)
        self.assertFalse(response.json()['is_finalized'])
        self.assertIsNone(response.json()['outcome'])
        self.assertNotIn('correct_answer', self.client.get(url).json()['question'])

    def test_both_types_three_attempts(self):
        for kind in ['multiple_choice', 'fill_blank']:
            if kind == 'multiple_choice':
                make_question(kind)
                s = start_legacy_session(self.user, kind, 'beginner')
                services.get_current_question(self.user, s.pk, 1)
            else:
                s = self.s
            wrong = 'add()' if kind == 'multiple_choice' else 'wrong'
            for n in range(1, 4):
                answer = services.submit_answer(self.user, s.pk, 1, wrong)
                self.assertEqual(answer.attempt_no, n)
            with self.assertRaises(services.LearningError):
                services.submit_answer(self.user, s.pk, 1, wrong)

    def test_legacy_completed_one_wrong_preserved(self):
        # Fixture represents an already completed session under the old policy.
        UserAnswer.objects.create(session_question=self.item, submitted_answer='wrong', is_correct=False)
        completed_at = timezone.now()
        self.s.completed_at = completed_at
        self.s.save(update_fields=['completed_at'])
        stats = services.session_statistics(self.s)
        self.assertEqual(stats['final_incorrect_count'], 1)
        self.assertEqual(stats['finalized_count'], 1)
        self.assertEqual(services.complete_session(self.user, self.s.pk).completed_at, completed_at)
        self.assertEqual(self.item.answers.count(), 1)

    def test_legacy_more_than_three_attempts_preserved(self):
        for n in range(1, 5):
            UserAnswer.objects.create(session_question=self.item, submitted_answer='wrong', is_correct=False, attempt_no=n)
        self.assertEqual(services.question_progress(self.item)['outcome'], 'incorrect')
        with self.assertRaises(services.LearningError):
            self.submit('append')
        self.assertEqual(self.item.answers.count(), 4)

    def test_mixed_results_sum_and_accuracy(self):
        # Create a separate 10-question session: 6 first, 3 retry, 1 wrong.
        for n in range(1, 10):
            make_question(number=n)
        s = start_legacy_session(self.user, 'fill_blank', 'beginner')
        for order in range(1, 11):
            services.get_current_question(self.user, s.pk, order)
            if 7 <= order <= 9:
                services.submit_answer(self.user, s.pk, order, 'wrong')
            if order == 10:
                for _ in range(3):
                    services.submit_answer(self.user, s.pk, order, 'wrong')
            else:
                services.submit_answer(self.user, s.pk, order, 'append')
        completed = services.complete_session(self.user, s.pk)
        response = self.client.get(f'/api/learning/sessions/{s.pk}/').json()
        self.assertEqual((response['first_try_correct_count'], response['retry_correct_count'], response['final_incorrect_count']), (6, 3, 1))
        self.assertEqual(response['finalized_count'], response['total_questions'])
        self.assertEqual(response['pending_count'], 0)
        self.assertEqual(response['final_accuracy'], 90)
        self.assertEqual(response['accuracy'], 90)
        self.assertEqual(completed.correct_count, 9)
        self.assertEqual({i['outcome'] for i in response['questions']}, {'first_try_correct', 'retry_correct', 'incorrect'})


class ConcurrentSubmissionTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='concurrent')
        make_question()
        self.s = start_legacy_session(self.user, 'fill_blank', 'beginner')
        self.item = services.get_current_question(self.user, self.s.pk, 1)

    def race(self, answers, request_uuid=None):
        barrier = Barrier(len(answers))
        user, sid = self.user, self.s.pk

        def worker(answer):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                for _ in range(100):
                    try:
                        return ('saved', services.submit_answer(user, sid, 1, answer, request_uuid).attempt_no)
                    except OperationalError as error:
                        # Shared-memory SQLite may return busy rather than wait.
                        # A client can retry 503; the transaction must have rolled back.
                        if connection.vendor != 'sqlite' or 'locked' not in str(error).lower():
                            raise
                        time.sleep(.01)
                    except services.LearningError as error:
                        return ('rejected', error.code)
                raise AssertionError('DB lock did not recover')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(answers)) as pool:
            return list(pool.map(worker, answers))

    def test_simultaneous_wrong_submissions_never_exceed_three(self):
        results = self.race(['wrong'] * 6)
        self.assertEqual(sorted(value for kind, value in results if kind == 'saved'), [1, 2, 3])
        self.assertEqual(self.item.answers.count(), 3)
        self.assertEqual(len([r for r in results if r[0] == 'rejected']), 3)

    def test_duplicate_correct_requests_only_save_once(self):
        results = self.race(['append'] * 4)
        self.assertEqual(len([r for r in results if r[0] == 'saved']), 1)
        self.assertEqual(self.item.answers.count(), 1)

    def test_same_wrong_request_replayed_concurrently(self):
        import uuid
        key=str(uuid.uuid4())
        results=self.race(['wrong']*4,key)
        self.assertEqual(self.item.answers.count(),1)
        self.assertTrue(all(value==1 for kind,value in results if kind=='saved'))

    def test_race_on_last_remaining_attempt(self):
        for _ in range(2):
            services.submit_answer(self.user, self.s.pk, 1, 'wrong')
        self.race(['append', 'wrong', 'wrong'])
        self.assertEqual(list(self.item.answers.values_list('attempt_no', flat=True)), [1, 2, 3])
        self.assertTrue(services.question_progress(self.item)['is_finalized'])


class AnswerReviewApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='review')
        self.client.force_login(self.user)

    def post(self, url, data):
        if url.endswith('/answers/') and isinstance(data, dict):
            data = {**data, 'submission_request_uuid': str(uuid.uuid4())}
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def test_seven_correct_three_failed_review_and_access(self):
        for number in range(10):
            make_question(number=number)
        session = start_legacy_session(self.user, 'fill_blank', 'beginner')
        base = f'/api/learning/sessions/{session.pk}/'
        self.assertNotIn('wrong_questions', self.client.get(base).json())
        for order in range(1, 11):
            url = base + f'questions/{order}/'
            self.assertNotIn('correct_answer', self.client.get(url).content.decode())
            if order <= 7:
                # Include second/third-try successes; they are not review failures.
                for _ in range(min(order - 1, 2)):
                    response = self.post(url + 'answers/', {'answer': 'wrong'})
                    self.assertNotIn('correct_answer', response.json())
                response = self.post(url + 'answers/', {'answer': 'append'})
                self.assertTrue(response.json()['answer_revealed'])
                self.assertEqual(response.json()['correct_answer'], 'append')
            else:
                for attempt in range(1, 4):
                    response = self.post(url + 'answers/', {'answer': f'wrong-{attempt}'})
                    self.assertEqual(response.json()['question_finished'], attempt == 3)
                self.assertEqual(response.json()['correct_answer'], 'append')
            self.assertEqual(self.post(url + 'answers/', {'answer': 'append'}).status_code, 409)
            self.assertNotIn('correct_answer', self.client.get(url).content.decode())
        self.assertNotIn('wrong_questions', self.client.get(base).json())
        result = self.post(base + 'complete/', {}).json()
        self.assertEqual((result['correct_count'], result['total_questions'], result['accuracy']), (7, 10, 70))
        self.assertEqual([q['question_order'] for q in result['wrong_questions']], [8, 9, 10])
        for question in result['wrong_questions']:
            self.assertEqual(question['submitted_answer'], 'wrong-3')
            self.assertEqual(question['correct_answer'], 'append')
            self.assertTrue(question['explanation'])
        self.assertEqual(self.client.get(base).json()['wrong_questions'], result['wrong_questions'])
        self.assertEqual(UserAnswer.objects.filter(session_question__session=session).count(), 27)
        other = get_user_model().objects.create_user(username='other-review')
        self.client.force_login(other)
        self.assertEqual(self.client.get(base).status_code, 404)

    def test_multiple_choice_reveals_number_only_at_finish(self):
        question = make_question(kind='multiple_choice')
        session = start_legacy_session(self.user, 'multiple_choice', 'beginner')
        url = f'/api/learning/sessions/{session.pk}/questions/1/'
        self.client.get(url)
        wrong = next(c.choice_text for c in question.choices.all() if c.choice_text != question.correct_answer)
        for attempt in range(1, 4):
            data = self.post(url + 'answers/', {'answer': wrong}).json()
            if attempt < 3:
                self.assertNotIn('correct_choice_no', data)
            else:
                correct = question.choices.get(choice_text=question.correct_answer)
                self.assertEqual(data['correct_choice_no'], correct.choice_no)
                self.assertEqual(data['correct_answer'], correct.choice_text)
        review = self.post(f'/api/learning/sessions/{session.pk}/complete/', {}).json()['wrong_questions']
        self.assertEqual(review[0]['correct_choice_no'], correct.choice_no)
