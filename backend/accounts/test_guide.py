from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import Profile
from .session_policy import start_login
from eventing.models import EventOutbox


class FirstVisitGuideTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='guide-owner')
        self.profile = Profile.objects.create(user=self.user, nickname='안내 사용자')
        self.sign_in(self.client, self.user)

    def sign_in(self, client, user):
        client.force_login(user)
        session = client.session
        start_login(session, user)
        session.save()

    def config(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        return response.json()['presentation']['context']['view_config']

    def test_first_visit_waits_until_finished(self):
        self.assertTrue(self.config()['guidePending'])
        self.assertTrue(self.config()['guidePending'])
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.guide_completed)

    def test_finished_or_skipped_does_not_repeat_after_login(self):
        self.assertEqual(self.client.post('/api/accounts/guide/complete/').status_code, 200)
        self.assertFalse(self.config()['guidePending'])
        self.client.logout()
        self.sign_in(self.client, self.user)
        self.assertFalse(self.config()['guidePending'])

    def test_cannot_complete_other_accounts(self):
        other = get_user_model().objects.create_user(username='other-guide-user')
        profile = Profile.objects.create(user=other, nickname='다른 사용자')
        self.client.post('/api/accounts/guide/complete/', {'user_id': other.pk})
        profile.refresh_from_db()
        self.assertFalse(profile.guide_completed)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.guide_completed)

    def test_anonymous_and_wrong_method(self):
        anonymous = Client()
        self.assertEqual(anonymous.post('/api/accounts/guide/complete/').status_code, 401)
        self.assertEqual(self.client.get('/api/accounts/guide/complete/').status_code, 405)

    def test_incomplete_profile_must_finish_setup(self):
        Profile.objects.filter(pk=self.profile.pk).update(setup_complete=False)
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.post('/api/accounts/guide/complete/').status_code, 409)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        self.sign_in(client, self.user)
        self.assertEqual(client.post('/api/accounts/guide/complete/').status_code, 403)
        client.get('/')
        token = client.cookies['csrftoken'].value if 'csrftoken' in client.cookies else client.cookies['campus_csrftoken'].value
        self.assertEqual(client.post('/api/accounts/guide/complete/', HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_repeated_completion_is_safe_and_emits_no_events(self):
        self.client.get('/')
        before = EventOutbox.objects.count()
        for unused in range(2):
            response = self.client.post('/api/accounts/guide/complete/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'guideCompleted': True})
            self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(EventOutbox.objects.count(), before)
