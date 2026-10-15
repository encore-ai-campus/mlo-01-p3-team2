import math
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from django.test import SimpleTestCase,TransactionTestCase,override_settings

from . import consumers
from .doors import DOORS,footprint
from .motion import geometry
from .test_poke import PokeSocketTests


class DoorOccupancyTests(SimpleTestCase):
    async def check_door(self, hidden):
        door_id='door-class4';door=DOORS[door_id];target=footprint(door,False)
        room=consumers.CampusRoom();room.doors[door_id]=True
        user=consumers.CampusConsumer();user.player_id='visitor';user.last_door=-math.inf
        user.state={'floor':'campus','x':target['x']+target['w']/2,'y':target['y']-12}
        user.current_identity=AsyncMock(return_value={});user.send_packet=AsyncMock()
        user.broadcast=AsyncMock();user.touch_activity=AsyncMock()
        room.players={'visitor':user.state,'student':{'floor':'campus','x':target['x']+target['w']/2,'y':target['y']+target['h']/2}}
        if hidden:room.interiors.add('student')
        with patch.object(consumers,'room',room):
            await user.receive_door({'doorId':door_id,'open':False})
        return room,user

    async def test_private_student_does_not_block_the_public_door(self):
        room,user=await self.check_door(True)
        self.assertFalse(room.doors['door-class4'])
        user.broadcast.assert_awaited_once()
        user.send_packet.assert_not_awaited()

    async def test_visible_student_still_blocks_door_swing(self):
        room,user=await self.check_door(False)
        self.assertTrue(room.doors['door-class4'])
        self.assertEqual(user.send_packet.await_args.args[0]['type'],'door_error')
        user.broadcast.assert_not_awaited()


@override_settings(ALLOWED_HOSTS=['127.0.0.1','testserver'],KAFKA_BOOTSTRAP_SERVERS='',CAMPUS_RAFFLE_SCHEDULER_ENABLED=False,CAMPUS_TEST_LEGACY_MOVEMENT=False)
class ClassroomVisibilitySocketTests(TransactionTestCase):
    setUp=PokeSocketTests.setUp
    socket=PokeSocketTests.socket
    packets=PokeSocketTests.packets

    async def matching_move(self,socket,player_id,hidden):
        for _ in range(100):
            packet=await socket.receive_json_from(timeout=2)
            if packet['type']=='move' and packet['player']['id']==player_id and packet['player'].get('inClassroom') is hidden:
                return packet
        self.fail('Expected visibility update was not received')

    async def test_enter_and_exit_broadcast_visibility_even_between_movement_frames(self):
        student=self.socket(self.clients[0]);observer=self.socket(self.clients[1])
        try:
            await student.connect();student_id=(await self.packets(student,{'welcome'}))['welcome']['selfId']
            await observer.connect();await self.packets(observer,{'welcome'})
            gate=geometry()['gates'][0];controller=consumers.room.controllers[student_id]
            consumers.room.doors[gate['doorId']]=True
            controller.pose.update(x=(gate['left']+gate['right'])/2,y=gate['y']-.5,dir='down')
            await student.send_json_to({'type':'input','keys':['arrowdown']})
            entered=await self.matching_move(observer,student_id,True)
            self.assertIn(student_id,consumers.room.interiors)
            self.assertTrue(entered['player']['inClassroom'])
            controller.last_classroom_transition=time.monotonic()-3
            await student.send_json_to({'type':'input','keys':[]})
            await student.send_json_to({'type':'control','requestId':'exit','action':'interact'})
            exited=await self.matching_move(observer,student_id,False)
            self.assertNotIn(student_id,consumers.room.interiors)
            self.assertFalse(exited['player']['inClassroom'])
        finally:
            for socket in (student,observer):
                if not socket.future.done():await socket.disconnect()

    async def test_new_observer_and_reconnect_receive_hidden_state(self):
        student=self.socket(self.clients[0]);observer=self.socket(self.clients[1]);replacement=self.socket(self.clients[0])
        try:
            await student.connect();student_id=(await self.packets(student,{'welcome'}))['welcome']['selfId']
            controller=consumers.room.controllers[student_id];gate=geometry()['gates'][0]
            controller.interior={'subject':gate['subject'],'gate':gate,'actor':{'x':154,'y':239,'dir':'left','moving':False}}
            await student.send_json_to({'type':'input','keys':[]})
            for _ in range(20):
                state=(await self.packets(student,{'control_state'}))['control_state']['state']
                if state['main'].get('inClassroom'):break
            self.assertTrue(state['main']['inClassroom'])
            await observer.connect();welcome=(await self.packets(observer,{'welcome'}))['welcome']
            self.assertTrue(next(p for p in welcome['players'] if p['id']==student_id)['inClassroom'])
            await replacement.connect();welcome=(await self.packets(replacement,{'welcome'}))['welcome']
            self.assertTrue(next(p for p in welcome['players'] if p['id']==welcome['selfId'])['inClassroom'])
        finally:
            for socket in (student,observer,replacement):
                if not socket.future.done():await socket.disconnect()
