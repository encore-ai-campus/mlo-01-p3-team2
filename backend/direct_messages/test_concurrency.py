"""Exercise opposite first sends using real, independent MySQL transactions."""
import json
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase, override_settings

from accounts.models import Profile
from .models import Conversation, Message


@unittest.skipUnless(connection.vendor == 'mysql', 'Requires MySQL row locking')
@override_settings(CAMPUS_DM_ENABLED=True, KAFKA_BOOTSTRAP_SERVERS='')
class SimultaneousFirstSendTests(TransactionTestCase):
    def test_opposite_first_sends_keep_both_messages_in_one_conversation(self):
        users = [get_user_model().objects.create_user(username='dm-concurrent-'+str(i)) for i in range(2)]
        profiles = [Profile.objects.create(user=user,nickname='동시전송'+str(i),cohort='mlo-1',setup_complete=True) for i,user in enumerate(users)]
        clients = [Client() for _ in users]
        for client,user in zip(clients,users):
            client.force_login(user)
        barrier = threading.Barrier(2)

        def send(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = clients[index].post('/api/messages/send/',json.dumps({
                    'recipient':str(profiles[1-index].user_uuid),
                    'body':'서로 먼저 보내는 메시지 '+str(index),
                    'requestId':str(uuid.uuid4()),
                }),content_type='application/json')
                return response.status_code,response.json()
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send,range(2)))
        self.assertEqual([result[0] for result in results],[201,201])
        self.assertEqual(results[0][1]['conversationId'],results[1][1]['conversationId'])
        self.assertEqual(Conversation.objects.count(),1)
        self.assertEqual(Message.objects.count(),2)
        self.assertEqual(set(Message.objects.values_list('sender_id',flat=True)),{user.pk for user in users})
