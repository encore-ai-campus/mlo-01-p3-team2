from io import BytesIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from accounts.session_policy import start_login
from PIL import Image, PngImagePlugin

from accounts.models import Profile
from eventing.models import EventOutbox
from . import service
from .models import Control, Entry, Event, WinnerContact
from .winner_contact import MAX_IMAGE_BYTES


def upload_image(size=(120,120), fmt='PNG', metadata=False):
    image = Image.new('RGB', size, 'white')
    buffer = BytesIO()
    if metadata:
        info = PngImagePlugin.PngInfo()
        info.add_text('email', 'private-contact@example.test')
        image.save(buffer, format=fmt, pnginfo=info)
    else:
        image.save(buffer, format=fmt)
    return SimpleUploadedFile('contact.'+fmt.lower(), buffer.getvalue(), content_type='image/'+fmt.lower())


@override_settings(KAFKA_BOOTSTRAP_SERVERS='', CAMPUS_SESSION_CLEANUP_ENABLED=False,
                   CAMPUS_RAFFLE_SCHEDULER_ENABLED=False)
class WinnerContactTests(TestCase):
    def setUp(self):
        self.owner = self.account('winner')
        self.other = self.account('other')
        self.manager = self.account('manager', staff=True)
        self.event = Event.objects.create(title='테스트 이벤트', status=Event.Status.DRAWN, drawn_at=timezone.now())
        self.entry = Entry.objects.create(event=self.event, user=self.owner, nickname='같은 닉네임')
        self.event.winner_entry = self.entry
        self.event.winner_nickname = self.entry.nickname
        self.event.save()
        Control.objects.filter(pk=1).update(current_event=self.event)
        self.owner_client = self.client_for(self.owner)
        self.other_client = self.client_for(self.other)
        self.manager_client = self.client_for(self.manager)
        self.url = f'/api/raffle/winner-contact/qr/{self.event.pk}/'

    def account(self, username, staff=False):
        user = get_user_model().objects.create_user(username=username, is_staff=staff)
        Profile.objects.create(user=user, nickname='같은 닉네임', cohort='mlo-1')
        return user

    def client_for(self, user, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(user)
        session = client.session
        start_login(session, user)
        session.save()
        client.get('/api/learning/csrf/')
        return client

    def save(self, file=None, client=None):
        return (client or self.manager_client).post('/api/raffle/winner-contact/', {'qrImage':file or upload_image()})

    def test_unconfigured_winner_has_pending_guidance_only(self):
        state = service.snapshot(self.owner)
        self.assertEqual(state['winnerContact']['status'], 'pending')
        self.assertIsNone(state['winnerContact']['qrUrl'])
        self.assertEqual(self.owner_client.get(self.url).status_code, 404)

    def test_nonwinner_and_public_snapshots_never_contain_contact_urls(self):
        self.assertEqual(self.save().status_code,200)
        for user in (self.other, None):
            state = service.snapshot(user)
            self.assertIsNone(state['winnerContact'])
            self.assertIsNone(state['winnerContactConfig'])
            self.assertNotIn('/winner-contact/qr/',str(state))

    def test_only_winner_can_fetch_private_image_even_with_same_nickname(self):
        self.assertEqual(self.save().status_code,200)
        response = self.owner_client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/png')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn('private',response['Cache-Control'])
        self.assertIn('Cookie',response['Vary'])
        self.assertEqual(self.other_client.get(self.url).status_code,404)
        self.assertEqual(self.manager_client.get(self.url).status_code,404)
        self.assertEqual(self.other_client.get(f'/api/raffle/winner-contact/qr/{uuid4()}/').status_code,404)

    def test_anonymous_requests_are_rejected(self):
        anonymous = Client()
        for url in (self.url,'/api/raffle/winner-contact/qr/'):
            self.assertEqual(anonymous.get(url).status_code,401)
        self.assertEqual(anonymous.post('/api/raffle/winner-contact/',{'qrImage':upload_image()}).status_code,401)

    def test_upload_and_preview_are_manager_only(self):
        self.assertEqual(self.save(client=self.other_client).status_code,403)
        self.assertFalse(WinnerContact.objects.exists())
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.manager_client.get('/api/raffle/winner-contact/qr/').status_code,200)
        self.assertEqual(self.owner_client.get('/api/raffle/winner-contact/qr/').status_code,403)

    def test_participating_before_draw_does_not_unlock_contact(self):
        self.save()
        self.event.status=Event.Status.OPEN
        self.event.save(update_fields=['status'])
        self.assertIsNone(service.snapshot(self.owner)['winnerContact'])
        self.assertEqual(self.owner_client.get(self.url).status_code,404)

    def test_winner_can_return_after_a_new_event_is_prepared(self):
        next_event=Event.objects.create(title='다음 이벤트')
        Control.objects.filter(pk=1).update(current_event=next_event)
        self.save()
        state=service.snapshot(self.owner)
        self.assertEqual(state['event']['id'],str(next_event.pk))
        self.assertEqual(state['winnerContact']['eventId'],str(self.event.pk))
        self.assertEqual(self.owner_client.get(self.url).status_code,200)

    def test_no_current_event_still_preserves_a_winners_guidance(self):
        Control.objects.filter(pk=1).update(current_event=None)
        self.assertEqual(service.snapshot(self.owner)['winnerContact']['eventId'],str(self.event.pk))

    def test_later_image_registration_updates_existing_winners(self):
        before=service.snapshot(self.owner)['winnerContact']
        self.save()
        after=service.snapshot(self.owner)['winnerContact']
        self.assertEqual(before['status'],'pending')
        self.assertEqual(after['status'],'ready')
        self.assertTrue(after['qrUrl'].startswith(self.url))

    def test_replace_image_changes_version_and_reuses_single_configuration(self):
        self.save()
        before=service.snapshot(self.owner)['winnerContact']['qrUrl']
        self.save(upload_image((150,150)))
        self.assertNotEqual(service.snapshot(self.owner)['winnerContact']['qrUrl'],before)
        self.assertEqual(WinnerContact.objects.count(),1)

    def test_uploaded_metadata_is_removed(self):
        self.assertEqual(self.save(upload_image(metadata=True)).status_code,200)
        response=self.owner_client.get(self.url)
        self.assertNotIn(b'private-contact@example.test',response.content)
        with Image.open(BytesIO(response.content)) as image:
            self.assertNotIn('email',image.info)

    def test_jpeg_and_webp_are_normalized_to_png(self):
        for fmt in ('JPEG','WEBP'):
            with self.subTest(fmt=fmt):
                self.assertEqual(self.save(upload_image(fmt=fmt)).status_code,200)
                with Image.open(BytesIO(self.owner_client.get(self.url).content)) as image:
                    self.assertEqual(image.format,'PNG')

    def test_invalid_or_oversized_images_are_rejected(self):
        files=[(SimpleUploadedFile('qr.png',b'<svg><script>alert(1)</script></svg>',content_type='image/png'),400),
               (upload_image((2049,100)),400),
               (SimpleUploadedFile('qr.png',b'x'*(MAX_IMAGE_BYTES+1),content_type='image/png'),413)]
        for file,status in files:
            with self.subTest(status=status):
                self.assertEqual(self.save(file).status_code,status)
        self.assertFalse(WinnerContact.objects.exists())

    def test_missing_image_and_wrong_method_are_rejected(self):
        self.assertEqual(self.manager_client.post('/api/raffle/winner-contact/',{}).status_code,400)
        response=self.manager_client.get('/api/raffle/winner-contact/')
        self.assertEqual(response.status_code,405)
        self.assertEqual(response['Allow'],'POST')

    def test_contact_registration_does_not_create_kafka_events(self):
        before=EventOutbox.objects.count()
        self.save()
        self.assertEqual(EventOutbox.objects.count(),before)

    def test_csrf_is_required_for_image_registration(self):
        client=self.client_for(self.manager,csrf=True)
        self.assertEqual(self.save(client=client).status_code,403)
        client.get('/api/learning/csrf/')
        token=client.cookies['campus_csrftoken'].value
        response=client.post('/api/raffle/winner-contact/',{'qrImage':upload_image()},HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)

    def test_revoked_entry_ownership_does_not_unlock_image(self):
        self.save()
        Entry.objects.filter(pk=self.entry.pk).update(user=None)
        self.assertIsNone(service.snapshot(self.owner)['winnerContact'])
        self.assertEqual(self.owner_client.get(self.url).status_code,404)
