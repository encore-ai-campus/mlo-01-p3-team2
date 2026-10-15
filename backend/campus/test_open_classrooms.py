"""Open classroom entrances retain private lessons and learning interactions."""
from unittest.mock import patch
from django.test import SimpleTestCase
from .doors import DOORS
from .motion import MotionController, geometry, world


class OpenClassroomTests(SimpleTestCase):
    def test_all_seven_former_classroom_thresholds_are_walkable(self):
        campus=world('campus')
        for x,y,axis in [(852.75,400.5,'y'),(1649.25,400.5,'y'),(852.75,553.5,'y'),
                         (1649.25,553.5,'y'),(480,247.5,'x'),(480,544.5,'x'),(480,859.5,'x')]:
            with self.subTest(x=x,y=y):
                a={'x':x-(20 if axis=='x' else 0),'y':y-(20 if axis=='y' else 0)}
                b={'x':x+(20 if axis=='x' else 0),'y':y+(20 if axis=='y' else 0)}
                self.assertTrue(campus.clear(a,b,{}))
        self.assertEqual(set(DOORS),{'door-storage'})

    def test_both_subjects_enter_without_door_state_and_open_both_learning_types(self):
        for gate in geometry()['gates']:
            with self.subTest(subject=gate['subject']):
                pose={'floor':'campus','x':(gate['left']+gate['right'])/2,'y':gate['y']-22,'dir':'down'}
                control=MotionController(pose,{})
                for n in range(12):
                    control.input(['s','a'],now=100+n*.04)
                    control.tick(.04,{},now=100+n*.04)
                    if control.interior:break
                self.assertIsNotNone(control.interior)
                self.assertEqual(control.interior['subject'],gate['subject'])
                for x,kind in [(170,'multiple_choice'),(470,'fill_blank')]:
                    control.interior['actor'].update(x=x,y=260)
                    event=control.command('interact',{}, {})
                    self.assertEqual(event,{'type':'learning_open','subject':gate['subject'],'questionType':kind})
                control.leave_classroom({},now=104)
                self.assertIsNone(control.interior)
                self.assertTrue(world('campus').walkable(control.pose['x'],control.pose['y'],{}))

    def test_classroom_door_is_never_offered_as_nearby_interaction(self):
        for gate in geometry()['gates']:
            control=MotionController({'floor':'campus','x':(gate['left']+gate['right'])/2,'y':gate['y']-12,'dir':'down'}, {})
            self.assertNotIn(control.hints({})['nearbyId'],{'door-class1','door-class2'})
