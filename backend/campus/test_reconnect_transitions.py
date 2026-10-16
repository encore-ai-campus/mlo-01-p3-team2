import asyncio
import time
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from . import consumers
from .motion import CLASSROOM_TRANSITION_DELAY, ControlError, MotionController, geometry, world
from .test_poke import PokeSocketTests


class ClassroomTransitionTests(SimpleTestCase):
    def enter(self):
        gate = geometry()['gates'][0]
        pose = {'floor':'campus','x':(gate['left']+gate['right'])/2,
                'y':gate['y']-.5,'dir':'down'}
        controller = MotionController(pose, {})
        controller.pose.update(pose)
        controller.input(['arrowdown'], now=100)
        controller.tick(.04, {}, now=100)
        self.assertIsNotNone(controller.interior)
        return controller, gate

    def at_exit(self, controller):
        controller.interior['actor'].update(world(controller.interior['subject']).data['spawn'].copy()
                                           if isinstance(world(controller.interior['subject']).data['spawn'],dict)
                                           else dict(zip(('x','y'),world(controller.interior['subject']).data['spawn'])))

    def test_held_entry_direction_never_exits_until_released_and_pressed_again(self):
        controller, gate = self.enter()
        for now in [100.1,100.5,101.9,102.1,103.5]:
            self.at_exit(controller)
            controller.input(['arrowdown'], now=now)
            controller.tick(.01, {}, now=now)
            self.assertIsNotNone(controller.interior)
        controller.input([], now=103.6)
        self.at_exit(controller)
        controller.input(['arrowdown'], now=103.7)
        controller.tick(.01, {}, now=103.7)
        self.assertIsNone(controller.interior)

    def test_exit_button_and_repressed_direction_wait_for_two_seconds(self):
        controller, gate = self.enter()
        controller.input([], now=100.1)
        self.at_exit(controller)
        controller.input(['arrowdown'], now=100.2)
        controller.tick(.01, {}, now=100.2)
        self.assertIsNotNone(controller.interior)
        with self.assertRaisesMessage(ControlError,'2초'):
            controller.leave_classroom({}, now=101.9)
        with patch('campus.motion.time.monotonic',return_value=101):
            self.assertEqual(controller.snapshot({})['interior']['exitCooldownMs'],1000)
        self.at_exit(controller)
        controller.input(['arrowdown'],now=102.01)
        controller.tick(.01,{},now=102.01)
        self.assertIsNone(controller.interior)

    def test_exit_has_a_reentry_cooldown(self):
        controller,gate=self.enter()
        controller.leave_classroom({},now=103)
        pose={'x':(gate['left']+gate['right'])/2,'y':gate['y']-.5,'dir':'down'}
        controller.pose.update(pose)
        controller.input(['arrowdown'],now=103.1)
        controller.tick(.04,{},now=103.1)
        self.assertIsNone(controller.interior)
        controller.pose.update(pose)
        controller.input(['arrowdown'],now=105.1)
        controller.tick(.04,{},now=105.1)
        self.assertIsNotNone(controller.interior)


@override_settings(ALLOWED_HOSTS=['127.0.0.1','testserver'],KAFKA_BOOTSTRAP_SERVERS='',CAMPUS_TEST_LEGACY_MOVEMENT=False)
class ReconnectSocketTests(TransactionTestCase):
    setUp=PokeSocketTests.setUp
    socket=PokeSocketTests.socket
    packets=PokeSocketTests.packets

    async def test_live_old_socket_is_replaced_and_late_disconnect_keeps_new_player(self):
        old=self.socket(self.clients[0]);observer=self.socket(self.clients[1]);new=self.socket(self.clients[0])
        try:
            await old.connect();old_id=(await self.packets(old,{'welcome'}))['welcome']['selfId']
            await observer.connect();await self.packets(observer,{'welcome'})
            await old.send_json_to({'type':'input','keys':['d']})
            for _ in range(20):
                state=(await self.packets(old,{'control_state'}))['control_state']['state']['main']
                if state['x']>130:break
            self.assertGreater(state['x'],130)
            self.assertTrue((await new.connect())[0])
            welcome=(await self.packets(new,{'welcome'}))['welcome'];new_id=welcome['selfId']
            self.assertNotEqual(old_id,new_id)
            self.assertNotIn(old_id,{p['id'] for p in welcome['players']})
            self.assertEqual(len(welcome['players']),2)
            self.assertGreater(next(p['x'] for p in welcome['players'] if p['id']==new_id),130)
            replaced=await self.packets(observer,{'leave','join'})
            self.assertEqual(replaced['leave']['id'],old_id)
            self.assertEqual(replaced['join']['player']['id'],new_id)
            while True:
                event=await old.receive_output(timeout=2)
                if event['type']=='websocket.close':break
            self.assertEqual(event['code'],4409)
            await old.disconnect()
            self.assertIn(new_id,consumers.room.players)
            self.assertEqual(consumers.room.sessions[self.clients[0].session.session_key],new_id)
            await new.send_json_to({'type':'ping'})
            await self.packets(new,{'pong'})
        finally:
            for socket in (old,observer,new):
                if not socket.future.done():await socket.disconnect()

    async def test_reconnect_preserves_private_classroom_with_independent_controller(self):
        old=self.socket(self.clients[0]);new=self.socket(self.clients[0])
        try:
            await old.connect();old_id=(await self.packets(old,{'welcome'}))['welcome']['selfId']
            original=consumers.room.controllers[old_id]
            gate=geometry()['gates'][0]
            original.interior={'subject':gate['subject'],'gate':gate,
                               'actor':{'x':154,'y':239,'dir':'left','moving':False}}
            original.last_classroom_transition=time.monotonic()
            await new.connect();new_id=(await self.packets(new,{'welcome'}))['welcome']['selfId']
            controller=consumers.room.controllers[new_id]
            self.assertIsNot(controller,original)
            self.assertIsNot(controller.interior,original.interior)
            self.assertEqual(controller.interior['actor']['x'],154)
            self.assertIn(new_id,consumers.room.interiors)
            await old.disconnect()
            self.assertIn(new_id,consumers.room.players)
            interior=(await self.packets(new,{'control_state'}))['control_state']['state']['interior']
            self.assertEqual(interior['subject'],gate['subject'])
        finally:
            for socket in (old,new):
                if not socket.future.done():await socket.disconnect()
