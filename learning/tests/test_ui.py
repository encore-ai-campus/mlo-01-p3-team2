import json
from io import StringIO
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import TestCase, Client
from learning.models import Question, LearningSession


class LearningUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='ui-test', password='test-password')
        call_command('seed_learning_questions', stdout=StringIO())

    def test_learning_page_public(self):
        self.client.force_login(self.user)
        response = self.client.get('/learning/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'learning/standalone.html')
        self.assertContains(response, 'Python Learning Room')
        self.assertContains(response, 'learningDialog')
        self.assertContains(response, 'data-difficulty="beginner"')
        self.assertContains(response, 'data-difficulty="intermediate"')
        self.assertContains(response, 'data-difficulty="advanced"')
        self.assertContains(response, 'role="progressbar"')

    def test_root_redirect(self):
        self.assertEqual(self.client.get('/learning/').status_code, 302)

    def test_static_files_exist_and_no_question_bank(self):
        for name in ['learning/learning.css', 'learning/learning.js']:
            self.assertIsNotNone(finders.find(name))
        from pathlib import Path
        source = Path(finders.find('learning/learning.js')).read_text(encoding='utf-8')
        self.assertIn('correct_answer', source)  # API response rendering, not an embedded answer bank
        self.assertIn('Python 객관식', source)
        self.assertNotIn('sample_questions', source)
        self.assertNotIn('innerHTML', source)

    def test_page_does_not_expose_answers(self):
        self.client.force_login(self.user)
        response = self.client.get('/learning/')
        self.assertNotContains(response, 'correct_answer')
        self.assertNotContains(response, 'append()')

    def test_page_get_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/learning/').status_code, 405)

    def test_both_types_ten_questions_retry_and_result_with_csrf(self):
        # Reuse one authenticated browser, matching the campus single-login policy.
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for kind in ['multiple_choice', 'fill_blank']:
            with self.subTest(kind=kind):
                client.get('/api/learning/csrf/')
                token = client.cookies['campus_csrftoken'].value

                def post(url, data):
                    return client.post(url, data=json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN=token)

                response = post('/api/learning/sessions/', {'question_type': kind, 'difficulty': 'beginner'})
                self.assertEqual(response.status_code, 201)
                sid = response.json()['session_id']
                base = f'/api/learning/sessions/{sid}/'
                for order in range(1, 11):
                    url = base + f'questions/{order}/'
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('correct_answer', response.content.decode())
                    data = response.json()['question']
                    self.assertEqual(data['question_type'], kind)
                    q = Question.objects.get(pk=data['question_id'])
                    if order == 1:
                        wrong = next(c.choice_text for c in q.choices.all() if c.choice_text != q.correct_answer) if kind == 'multiple_choice' else 'wrong'
                        result = post(url + 'answers/', {'answer': wrong})
                        self.assertFalse(result.json()['is_correct'])
                        self.assertEqual(result.json()['attempt_no'], 1)
                    result = post(url + 'answers/', {'answer': q.correct_answer})
                    self.assertTrue(result.json()['is_correct'])
                    self.assertEqual(result.json()['attempt_no'], 2 if order == 1 else 1)
                completed = post(base + 'complete/', {})
                self.assertEqual(completed.status_code, 200)
                self.assertEqual(completed.json()['correct_count'], 10)
                self.assertEqual(client.get(base).json()['accuracy'], 100)
                next_session = post('/api/learning/sessions/', {'question_type': kind, 'difficulty': 'beginner'})
                self.assertNotEqual(sid, next_session.json()['session_id'])

    def test_missing_difficulty_for_both_contents(self):
        self.client.force_login(self.user)
        for kind in ['multiple_choice', 'fill_blank']:
            for level in ['intermediate', 'advanced']:
                response = self.client.post('/api/learning/sessions/', data=json.dumps({'question_type': kind, 'difficulty': level}), content_type='application/json')
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['error'], 'empty_question_pool')
        self.assertEqual(LearningSession.objects.count(), 0)

    def test_ui_does_not_relax_authentication(self):
        self.assertEqual(self.client.get('/api/learning/csrf/').status_code, 401)
        self.assertEqual(self.client.get('/api/learning/sessions/1/').status_code, 401)


class FrozenLearningDesignTests(TestCase):
    def test_panel_reuses_existing_layout_without_extra_controls(self):
        from pathlib import Path
        panel=(Path(__file__).parents[1]/'templates/learning/panel.html').read_text(encoding='utf-8')
        self.assertNotIn('subject-select',panel)
        self.assertNotIn('result-pass',panel)
        self.assertNotIn('result-completed',panel)
        for value in ['Python 기본 문법','자료구조와 함수','심화 Python','id="result-title"','class="result-note"']:
            self.assertIn(value,panel)
