from django.test import TestCase
from accounts.forms import SignUpForm, ProfileSetupForm
from accounts.cohorts import COHORT_FORM_CHOICES, allowed_avatars, course_for_cohort
from eventing.catalog import class_group_uuid
from eventing.models import ClassGroup

class AioCohortTests(TestCase):
    def test_signup_saves_aio_and_offers_the_same_avatars_as_skn(self):
        form = SignUpForm(data={"username":"aio_test_user","cohort":"aio-4","password1":"AioUniqueSignup9!","password2":"AioUniqueSignup9!"})
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.campus_profile.cohort, "aio-4")
        self.assertFalse(user.campus_profile.setup_complete)
        self.assertEqual(course_for_cohort("aio-4"), "aio")
        self.assertEqual(allowed_avatars("aio-4"), allowed_avatars("skn-34"))
        for avatar in ["male-2", "female-1"]:
            setup=ProfileSetupForm(data={"nickname":"AIO유저","avatar":avatar},cohort="aio-4")
            self.assertTrue(setup.is_valid(), setup.errors)
        for avatar in ["male-1", "female-2"]:
            self.assertFalse(ProfileSetupForm(data={"nickname":"AIO유저","avatar":avatar},cohort="aio-4").is_valid())

    def test_groups_are_separate_and_existing_avatar_rules_remain(self):
        groups=dict(COHORT_FORM_CHOICES[1:])
        self.assertEqual(groups["AIO"], (("aio-4", "AIO 4기"),))
        self.assertEqual([v[0] for v in groups["SKN"]], ["skn-34", "skn-36"])
        self.assertEqual(allowed_avatars("mlo-1"), ("male-1", "female-2"))
        self.assertEqual(allowed_avatars("aio-999"), ())

    def test_events_resolve_to_the_seeded_aio_class_group(self):
        row=ClassGroup.objects.get(code="aio-4")
        self.assertEqual(row.class_group_uuid, class_group_uuid("aio-4"))
        self.assertNotEqual(class_group_uuid("aio-4"), class_group_uuid(""))
