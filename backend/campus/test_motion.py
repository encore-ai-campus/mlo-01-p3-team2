"""Rules moved from browser geometry to the authoritative controller."""
import math

from django.test import SimpleTestCase

from .doors import DOORS, distance, footprint
from .motion import ControlError, MotionController, SPEED, geometry, world
from .positions import DEFAULT_POSITION


class ServerMotionTests(SimpleTestCase):
    def controller(self, floor='campus', **position):
        spawn = world(floor).data['spawn']
        return MotionController({'floor': floor, 'x': spawn[0], 'y': spawn[1], 'dir': 'up', **position})

    def test_worlds_and_classrooms_have_reachable_spawns(self):
        for name in ('campus', 'rooftop', 'python', 'sql'):
            with self.subTest(name=name):
                self.assertTrue(world(name).walkable(*world(name).data['spawn']))

    def test_speed_and_direction_are_stable_for_diagonal_inputs(self):
        controller = self.controller('rooftop', x=1900, y=1100)
        controller.input(['d', 's'], now=10)
        directions = []
        for tick in range(6):
            controller.tick(.02, now=10 + tick*.02)
            directions.append(controller.pose['dir'])
        self.assertEqual(set(directions), {'right'})
        self.assertEqual(SPEED, 156.25)
        self.assertTrue(controller.pose['moving'])

    def test_missing_key_refresh_stops_movement_and_large_tick_is_capped(self):
        controller = self.controller('rooftop', x=1900, y=1100)
        controller.input(['d'], now=10)
        start = controller.pose.copy()
        controller.tick(10, now=10)
        self.assertLess(math.hypot(controller.pose['x']-start['x'], controller.pose['y']-start['y']), 15)
        after = controller.pose.copy()
        controller.tick(.04, now=11)
        self.assertEqual((controller.pose['x'], controller.pose['y']), (after['x'], after['y']))
        self.assertFalse(controller.pose['moving'])

    def test_invalid_keyboard_packets_do_not_replace_accepted_input(self):
        controller = self.controller()
        controller.input(['w'], now=10)
        for invalid in (None, {}, 'w', ['teleport'], ['w']*9, [1]):
            with self.assertRaises(ControlError):
                controller.input(invalid, now=11)
        self.assertEqual(controller.keys, {'w'})

    def test_classroom_wall_and_desk_collision_prevent_tunnelling(self):
        for subject in ('python', 'sql'):
            room = world(subject)
            self.assertFalse(room.walkable(15, 250))
            self.assertFalse(room.walkable(115, 180))
            actor = {'x': 320, 'y': 455, 'moving': False}
            room.move(actor, -2000, 0)
            self.assertGreaterEqual(actor['x'], 23)
            self.assertTrue(room.walkable(actor['x'], actor['y']))

    def test_all_learning_desk_approaches_are_reachable_in_both_classrooms(self):
        for subject in ('python', 'sql'):
            room = world(subject)
            start = dict(zip(('x', 'y'), room.data['spawn']))
            for obj in room.data['objects']:
                if obj.get('action') == 'learning':
                    end = dict(zip(('x', 'y'), obj['interactionPoint']))
                    self.assertTrue(room.walkable(end['x'], end['y']))
                    self.assertIsNotNone(room.route(start, end), obj['id'])

    def test_open_classroom_gate_enters_its_subject_without_door_state(self):
        for gate in geometry()['gates']:
            x = (gate['left'] + gate['right']) / 2
            doors = {}
            self.assertTrue(world('campus').walkable(x, gate['y']+4.5, doors))
            controller = MotionController({'floor': 'campus', 'x': x, 'y': gate['y']-1, 'dir': 'down'}, doors)
            controller.input(['s'], now=10)
            controller.tick(.04, doors, now=10)
            self.assertEqual(controller.interior['subject'], gate['subject'])

    def test_each_painted_learning_zone_selects_the_correct_type_on_the_server(self):
        controller = self.controller()
        for gate in geometry()['gates']:
            for x, kind in ((180, 'multiple_choice'), (480, 'fill_blank')):
                controller.interior = {'subject': gate['subject'], 'gate': gate,
                    'actor': {'x': x, 'y': 280, 'dir': 'up', 'moving': False}}
                self.assertEqual(controller.command('interact', {}),
                    {'type': 'learning_open', 'subject': gate['subject'], 'questionType': kind})
            controller.interior['actor'].update(x=320, y=280)
            with self.assertRaises(ControlError):
                controller.command('interact', {})

    def test_exit_requires_the_classroom_doorway(self):
        controller = self.controller()
        gate = geometry()['gates'][0]
        doors = {}
        controller.interior = {'subject': gate['subject'], 'gate': gate,
            'actor': {'x': 320, 'y': 280, 'dir': 'down', 'moving': False}}
        with self.assertRaises(ControlError):
            controller.command('interact', {}, doors)
        controller.interior['actor']['y'] = 478
        controller.command('interact', {}, doors)
        self.assertIsNone(controller.interior)
        self.assertLess(controller.pose['y'], gate['y'])

    def test_booth_open_requires_its_central_interaction_point(self):
        controller = self.controller('rooftop')
        for obj in controller.world.data['objects']:
            if obj.get('action') != 'booth':
                continue
            with self.assertRaises(ControlError):
                controller.command('open_booth', {'objectId': obj['id']})
            controller.pose.update(zip(('x', 'y'), obj['interactionPoint']))
            self.assertEqual(controller.command('open_booth', {'objectId': obj['id']})['objectId'], obj['id'])

    def test_floor_transfer_must_be_offered_near_a_portal_before_commit(self):
        controller = self.controller()
        with self.assertRaises(ControlError):
            controller.command('transfer', {'floor': 'rooftop'})
        with self.assertRaises(ControlError):
            controller.command('prepare_transfer', {'objectId': 'campus-roof-stairs'})
        controller.pose.update(x=2280, y=912)
        offer = controller.command('prepare_transfer', {'objectId': 'campus-roof-stairs'})
        self.assertEqual(offer['floor'], 'rooftop')
        before = controller.pose.copy()
        controller.input(['w'], now=10)
        controller.tick(.04, now=10)
        self.assertEqual((controller.pose['x'], controller.pose['y']), (before['x'], before['y']))
        controller.command('transfer', {'floor': 'rooftop'})
        self.assertEqual(controller.pose['floor'], 'rooftop')
        self.assertTrue(controller.world.walkable(controller.pose['x'], controller.pose['y']))

    def test_navigation_rejects_out_of_bounds_or_solid_destinations(self):
        controller = self.controller()
        for point in ({'x': -1, 'y': 100}, {'x': math.inf, 'y': 100}, {'x': True, 'y': 100}, {'x': 0, 'y': 0}):
            with self.assertRaises(ControlError):
                controller.command('navigate', point)

    def test_sliding_door_parks_along_the_wall_and_clears_its_threshold(self):
        door = DOORS['door-storage']
        closed, opened = footprint(door, False), footprint(door, True)
        player = {'x': closed['x'] + closed['w']/2, 'y': closed['y'] + closed['h']/2}
        self.assertEqual(distance(closed, player), 0)
        self.assertGreater(distance(opened, player), 5.5)
        self.assertEqual(closed['w'], opened['w'])
        self.assertEqual(closed['h'], opened['h'])
