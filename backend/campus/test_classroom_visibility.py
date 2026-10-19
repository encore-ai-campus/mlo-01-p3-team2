import time
from types import SimpleNamespace

from django.test import TransactionTestCase,override_settings

from . import consumers
from .motion import geometry
from .test_poke import PokeSocketTests


class ClassroomVisibilitySocketTests(TransactionTestCase):
    setUp=PokeSocketTests.setUp
    socket=PokeSocketTests.socket
    packets=PokeSocketTests.packets

    async def matching_move(self,socket,player_id,hidden):
        for _ in range(100):
            packet=await socket.receive_json_from(timeout=2)
            for player in packet['players'] if packet['type']=='moves' else [packet.get('player')] if packet['type']=='move' else []:
                if player['id']==player_id and player.get('inClassroom') is hidden:
                    return {'type':'move','player':player}
        self.fail('Expected visibility update was not received')

    async def test_enter_and_exit_broadcast_visibility_even_between_movement_frames(self):
        student=self.socket(self.clients[0]);observer=self.socket(self.clients[1])
        try:
            await student.connect();student_id=(await self.packets(student,{'welcome'}))['welcome']['selfId']
            await observer.connect();await self.packets(observer,{'welcome'})
            gate=geometry()['gates'][0];controller=consumers.room.controllers[student_id]
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
