"""Jumps are authenticated, transient, scoped effects with no position writes."""
import asyncio
import math
from unittest.mock import AsyncMock, patch

from channels.db import database_sync_to_async
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from eventing.models import EventOutbox
from . import consumers, test_poke as fixtures
from .motion import MotionController


class JumpControlTests(SimpleTestCase):
    def setUp(self):
        self.room = consumers.CampusRoom()
        self.consumer = consumers.CampusConsumer()
        self.consumer.player_id = 'self'
        self.consumer.controller = MotionController({'floor':'campus','x':130,'y':100,'dir':'right'})
        self.consumer.state = {'id':'self', **self.consumer.controller.pose}
        self.consumer.control_lock = asyncio.Lock()
        self.consumer.last_jump = -math.inf
        self.consumer.position_dirty = False
        self.consumer.policy_status = {}
        for name in ['send_packet','broadcast','touch_activity','receive_movement','session_expired']:
            setattr(self.consumer,name,AsyncMock())
        self.consumer.current_identity = AsyncMock(return_value={})
        self.room.players = {'self': self.consumer.state.copy()}
        replacement = patch.object(consumers,'room',self.room)
        replacement.start();self.addCleanup(replacement.stop)
        share = patch.object(consumers,'share_effect',new=AsyncMock())
        self.share = share.start();self.addCleanup(share.stop)
        self.arguments = {'context':'world','floor':'campus'}

    async def request(self, arguments=None):
        await self.consumer.receive_control({'requestId':'jump-1','action':'jump','data':self.arguments if arguments is None else arguments})

    async def test_jump_does_not_move_or_mark_position_dirty(self):
        before = self.consumer.controller.pose.copy()
        await self.request()
        packet = self.share.await_args.args[1]
        self.assertEqual((packet['type'],packet['actorId'],packet['floor'],packet['durationMs'],packet['height']),('jump','self','campus',720,52))
        self.assertEqual(self.consumer.controller.pose,before)
        self.assertFalse(self.consumer.position_dirty)
        self.consumer.receive_movement.assert_not_awaited()

    async def test_second_jump_is_rejected_until_landing(self):
        await self.request();await self.request()
        self.share.assert_awaited_once()
        self.assertIn('착지',self.consumer.send_packet.await_args.args[0]['error'])

    async def test_forged_context_and_coordinates_cannot_jump(self):
        for arguments in [{'context':'world','floor':'rooftop'},{**self.arguments,'x':9999}, {'context':'classroom','subject':'sql'}]:
            await self.request(arguments)
        self.share.assert_not_awaited()

    async def test_pending_floor_transfer_blocks_jump(self):
        self.consumer.controller.pending_transfer = {'id':'campus-roof-stairs'}
        await self.request()
        self.share.assert_not_awaited()

    async def test_private_classroom_jump_only_goes_to_owner(self):
        self.consumer.controller.interior = {'subject':'python','actor':{'x':154,'y':239,'dir':'left','moving':False}}
        await self.request({'context':'classroom','subject':'python'})
        self.share.assert_not_awaited()
        self.assertTrue(any(call.args[0].get('type')=='jump' and call.args[0].get('context')=='classroom' for call in self.consumer.send_packet.await_args_list))

    async def test_jump_does_not_read_the_session_from_the_database(self):
        # 꾸밈 동작은 조작마다 DB 를 보지 않는다(계획 M8). 만료 시각·10초 세션 확인·로그아웃 알림이 지킨다
        self.consumer.current_identity.return_value = None
        await self.request()
        self.consumer.current_identity.assert_not_awaited()
        self.share.assert_awaited_once()

    async def test_state_changing_controls_still_check_the_session(self):
        self.consumer.current_identity.return_value = None
        await self.consumer.receive_control({'requestId':'stairs-1','action':'prepare_transfer','data':{'objectId':'campus-roof-stairs'}})
        self.consumer.session_expired.assert_awaited_once()

    async def test_jump_reaches_the_same_floor_nearby_and_never_private_classrooms(self):
        await self.request()
        _, packet = self.share.await_args.args
        floor, x, y, reach = self.share.await_args.kwargs['near']
        self.assertEqual((floor, x, y, reach), ('campus', 130, 100, consumers.VIEW_RANGE))
        room = consumers.CampusRoom()
        room.players = {'self':{'floor':'campus','x':130,'y':100},'near':{'floor':'campus','x':900,'y':500},
                        'far':{'floor':'campus','x':130+consumers.VIEW_RANGE+1,'y':100},'roof':{'floor':'rooftop','x':130,'y':100},
                        'class':{'floor':'campus','x':140,'y':100,'inClassroom':True}}
        room.sockets = {key:AsyncMock() for key in room.players}
        await consumers.deliver_effect(room, packet, near=(floor, x, y, reach))
        self.assertEqual({key for key, socket in room.sockets.items() if socket.send.await_count}, {'self','near'})


@override_settings(ALLOWED_HOSTS=['127.0.0.1','testserver'],KAFKA_BOOTSTRAP_SERVERS='')
class JumpSocketTests(TransactionTestCase):
    setUp = fixtures.PokeSocketTests.setUp
    socket = fixtures.PokeSocketTests.socket
    packets = fixtures.PokeSocketTests.packets

    @database_sync_to_async
    def outbox_count(self):
        return EventOutbox.objects.count()

    async def test_two_authenticated_clients_share_jump_without_collecting_event(self):
        left,right = [self.socket(client) for client in self.clients]
        try:
            await left.connect();own=(await self.packets(left,{'welcome'}))['welcome']['selfId']
            await right.connect();await self.packets(right,{'welcome'})
            before=await self.outbox_count()
            await left.send_json_to({'type':'control','requestId':'jump-1','action':'jump','data':{'context':'world','floor':'campus'}})
            accepted=await self.packets(left,{'jump','control_result'})
            observed=(await self.packets(right,{'jump'}))['jump']
            self.assertEqual(accepted['jump'],observed)
            self.assertEqual(observed['actorId'],own)
            self.assertEqual(before,await self.outbox_count())
            await left.send_json_to({'type':'control','requestId':'jump-2','action':'jump','data':{'context':'world','floor':'campus'}})
            self.assertIn('error',(await self.packets(left,{'control_result'}))['control_result'])
        finally:
            await left.disconnect();await right.disconnect()
