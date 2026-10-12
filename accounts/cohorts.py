"""Enrollment choices and avatars shared by every cohort in a course."""
COHORT_CHOICES = (
    ("mlo-1", "MLO 1기"), ("mlo-2", "MLO 2기"), ("mlo-3", "MLO 3기"),
    ("skn-34", "SKN 34기"), ("skn-36", "SKN 36기"),
)
COHORT_FORM_CHOICES = (
    ("", "과정·기수를 선택해 주세요"),
    ("MLO", COHORT_CHOICES[:3]), ("SKN", COHORT_CHOICES[3:]),
)
COURSE_AVATARS = {"mlo": ("male-1", "female-2"), "skn": ("male-2", "female-1")}


def course_for_cohort(cohort):
    return cohort.split("-", 1)[0] if cohort in dict(COHORT_CHOICES) else ""


def allowed_avatars(cohort):
    return COURSE_AVATARS.get(course_for_cohort(cohort), ())
