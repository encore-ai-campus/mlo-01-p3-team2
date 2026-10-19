import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.test import Client,TestCase,TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import Profile
from campus.test_poke import PokeSocketTests
from . import service
from .live import notify,user_group
from .models import Conversation,Message


@override_settings(CAMPUS_DM_ENABLED=True,KAFKA_BOOTSTRAP_SERVERS='')
class DirectMessageTests(TestCase):
    def setUp(self):
        self.owner=get_user_model().objects.create_user(username='pilot@example.test')
        self.recipient=get_user_model().objects.create_user(username='recipient')
        self.outsider=get_user_model().objects.create_user(username='outsider',is_staff=True)
        self.profiles={}
        for user,name in [(self.owner,'시범 사용자'),(self.recipient,'받는사람'),(self.outsider,'제삼자')]:
            self.profiles[user.pk]=Profile.objects.create(user=user,nickname=name,cohort='mlo-1',setup_complete=True)
        self.client.force_login(self.owner)

    def send(self,recipient=None,body='개인 메시지',request_id=None,client=None):
        return (client or self.client).post('/api/messages/send/',json.dumps({
            'recipient':str(self.profiles[(recipient or self.recipient).pk].user_uuid),
            'body':body,'requestId':str(request_id or uuid.uuid4())}),content_type='application/json')

    def test_search_selects_offline_accounts_by_nickname_without_exposing_login_details(self):
        response=self.client.get('/api/messages/recipients/',{'q':'받는'})
        self.assertEqual(response.status_code,200)
        person=response.json()['recipients'][0]
        self.assertEqual(person['id'],str(self.profiles[self.recipient.pk].user_uuid))
        self.assertNotIn('email',person);self.assertNotIn('username',person)

    def test_offline_message_persists_and_recipient_can_receive_and_reply(self):
        sent=self.send();self.assertEqual(sent.status_code,201)
        conversation=sent.json()['conversationId'];self.client.force_login(self.recipient)
        status=self.client.get('/api/messages/status/').json()
        self.assertTrue(status['hasInbox']);self.assertTrue(status['canStart']);self.assertEqual(status['unread'],1)
        thread=self.client.get(f'/api/messages/conversations/{conversation}/').json()
        self.assertEqual(thread['messages'][0]['body'],'개인 메시지')
        self.assertFalse(thread['messages'][0]['sentByMe'])
        reply=self.send(recipient=self.owner,body='답장입니다')
        self.assertEqual(reply.status_code,201);self.assertEqual(reply.json()['conversationId'],conversation)

    def test_any_registered_account_can_search_and_start_without_a_pilot_allowlist(self):
        self.client.force_login(self.recipient)
        self.assertEqual(self.client.get('/api/messages/recipients/',{'q':'시범'}).status_code,200)
        self.assertTrue(self.client.get('/api/messages/status/').json()['hasInbox'])
        self.assertEqual(self.send(recipient=self.outsider).status_code,201)

    def test_unrelated_account_including_staff_cannot_read_or_mark_another_conversation(self):
        sent=self.send().json();self.client.force_login(self.outsider)
        url='/api/messages/conversations/'+sent['conversationId']+'/'
        self.assertEqual(self.client.get(url).status_code,404)
        response=self.client.post(url+'read/',json.dumps({'through':sent['message']['id']}),content_type='application/json')
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.get('/api/messages/conversations/').json()['conversations'],[])

    def test_retry_is_idempotent_and_changed_retry_is_rejected(self):
        request_id=uuid.uuid4();first=self.send(request_id=request_id);second=self.send(request_id=request_id)
        self.assertEqual(first.status_code,201);self.assertEqual(second.status_code,200)
        self.assertEqual(first.json()['message']['id'],second.json()['message']['id']);self.assertEqual(Message.objects.count(),1)
        self.assertEqual(self.send(body='다른 내용',request_id=request_id).status_code,409)

    def test_sender_is_always_authenticated_user_and_duplicates_are_rate_limited(self):
        self.assertEqual(self.send().status_code,201)
        message=Message.objects.get();self.assertEqual(message.sender,self.owner)
        self.assertEqual(self.send(body='연속 전송').status_code,429)

    def test_message_content_is_plain_text_and_invalid_content_is_rejected(self):
        self.assertEqual(self.send(body=' ').status_code,400)
        self.assertEqual(self.send(body='x'*2001).status_code,400)
        self.assertEqual(self.send(body='a\x00b').status_code,400)
        self.assertEqual(self.send(body='<script>alert(1)</script>').status_code,201)
        self.assertEqual(Message.objects.get().body,'<script>alert(1)</script>')

    def test_read_only_marks_messages_actually_displayed_and_does_not_repeat_notifications(self):
        first=self.send().json();conversation=Conversation.objects.get()
        later=Message.objects.create(conversation=conversation,sender=self.owner,recipient=self.recipient,body='나중 메시지',request_id=uuid.uuid4())
        self.client.force_login(self.recipient);url=f'/api/messages/conversations/{conversation.pk}/read/'
        with patch('direct_messages.views.notify') as notified,self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,json.dumps({'through':first['message']['id']}),content_type='application/json')
        self.assertEqual(response.json()['unread'],1);later.refresh_from_db();self.assertIsNone(later.read_at)
        self.assertEqual(notified.call_count,2)
        with patch('direct_messages.views.notify') as notified,self.captureOnCommitCallbacks(execute=True):
            self.client.post(url,json.dumps({'through':first['message']['id']}),content_type='application/json')
        notified.assert_not_called()

    def test_mailbox_is_available_without_a_map_socket_or_room_position(self):
        self.assertEqual(self.client.get('/api/messages/status/').status_code,200)
        self.assertEqual(self.client.get('/api/messages/conversations/').status_code,200)
        self.assertEqual(self.client.get('/api/messages/recipients/',{'q':'받는'}).status_code,200)
        self.assertEqual(self.send().status_code,201)

    def test_disabled_feature_is_unavailable_and_requires_authentication(self):
        with override_settings(CAMPUS_DM_ENABLED=False):self.assertEqual(self.client.get('/api/messages/status/').status_code,404)
        self.client.logout();self.assertEqual(self.client.get('/api/messages/status/').status_code,401)

    def test_csrf_is_required_and_status_bootstraps_the_token(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(self.send(client=client).status_code,403)
        self.assertEqual(client.get('/api/messages/status/').status_code,200)
        token=client.cookies['campus_csrftoken'].value
        response=client.post('/api/messages/send/',json.dumps({'recipient':str(self.profiles[self.recipient.pk].user_uuid),
            'body':'CSRF 검사','requestId':str(uuid.uuid4())}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,201)

    def test_disabled_and_unconfigured_profiles_cannot_be_selected_or_receive(self):
        self.recipient.is_active=False;self.recipient.save(update_fields=['is_active'])
        self.assertEqual(self.client.get('/api/messages/recipients/',{'q':'받는'}).json()['recipients'],[])
        self.assertEqual(self.send().status_code,404)
        self.recipient.is_active=True;self.recipient.save(update_fields=['is_active'])
        profile=self.profiles[self.recipient.pk];profile.setup_complete=False;profile.save(update_fields=['setup_complete'])
        self.assertEqual(self.send().status_code,404)

    def test_own_account_and_invalid_recipient_are_rejected(self):
        self.assertEqual(self.send(recipient=self.owner).status_code,400)
        response=self.client.post('/api/messages/send/',json.dumps({'recipient':str(uuid.uuid4()),'body':'없는 상대','requestId':str(uuid.uuid4())}),content_type='application/json')
        self.assertEqual(response.status_code,404)

    def test_private_notification_contains_no_message_body(self):
        layer=SimpleNamespace(group_send=AsyncMock())
        with patch('direct_messages.live.get_channel_layer',return_value=layer):notify(self.recipient.pk,uuid.uuid4())
        group,event=layer.group_send.await_args.args
        self.assertEqual(group,user_group(self.recipient.pk));self.assertEqual(set(event),{'type','conversationId'})


@override_settings(CAMPUS_DM_ENABLED=True,ALLOWED_HOSTS=['127.0.0.1','testserver'],KAFKA_BOOTSTRAP_SERVERS='')
class PrivateSocketTests(TransactionTestCase):
    setUp=PokeSocketTests.setUp
    socket=PokeSocketTests.socket
    packets=PokeSocketTests.packets

    async def test_notification_is_sent_only_to_the_recipient_group(self):
        left,right=[self.socket(client) for client in self.clients]
        try:
            await left.connect();await self.packets(left,{'welcome'})
            await right.connect();await self.packets(right,{'welcome'})
            user_id=await database_sync_to_async(lambda:self.clients[1].session['_auth_user_id'])()
            conversation_id=str(uuid.uuid4())
            await get_channel_layer().group_send(user_group(user_id),{'type':'direct.message','conversationId':conversation_id})
            received=(await self.packets(right,{'private_message'}))['private_message']
            self.assertEqual(received,{'type':'private_message','conversationId':conversation_id})
            # 가만히 있는 소켓에는 메시지가 오지 않는다(계획 1a·1b): 그동안 쌓인 것만 본다
            await asyncio.sleep(.5)
            while not await left.receive_nothing(timeout=0):
                self.assertNotEqual((await left.receive_json_from())['type'],'private_message')
        finally:
            for socket in (left,right):
                if not socket.future.done():await socket.disconnect()
