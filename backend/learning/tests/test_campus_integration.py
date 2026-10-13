from config.testing import PresentationTestCase
from io import StringIO
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from accounts.models import Profile
from learning.models import Question


class CampusLearningIntegrationTests(PresentationTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='campus-learning-integration')
        Profile.objects.create(user=cls.user, nickname='학습 확인', avatar='male-1', cohort='mlo-1', setup_complete=True)

    def test_map_includes_versioned_learning_panels_and_keeps_latest_features(self):
        self.client.force_login(self.user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for value in ('id="classroomDialog"', 'id="learningDialog"', 'id="lunchWheel"', 'rooftop-city.js', 'stair-motion.js'):
            self.assertContains(response, value)
        for name in ('learning.css', 'learning.js', 'classroom-assets.js', 'classroom-map.js', 'classroom.js'):
            self.assertContains(response, f'/static/learning/{name}?v=')
        self.assertNotContains(response, '<!-- learning-panels -->')
        self.assertNotContains(response, '<!-- learning-assets -->')
        self.assertNotContains(response, 'sample_questions')

    def test_standalone_map_has_no_server_template_tags(self):
        source = (settings.BASE_DIR.parent / 'frontend/dist/index.html').read_text(encoding='utf-8')
        self.assertNotIn('{%', source)
        self.assertIn('<!-- learning-panels -->', source)
        self.assertIn('lunch-wheel.js', source)

    def test_both_datasets_seed_120_questions_idempotently(self):
        files = [Path(__file__).parents[1] / 'sample_questions.json',
                 Path(__file__).parents[1] / 'data/initial_subject_bank.json']
        for _ in range(2):
            for file in files:
                call_command('seed_learning_questions', file=file, stdout=StringIO())
        self.assertEqual(Question.objects.count(), 120)
        self.assertEqual(Question.objects.filter(subject='python').count(), 60)
        self.assertEqual(Question.objects.filter(subject='sql').count(), 60)
