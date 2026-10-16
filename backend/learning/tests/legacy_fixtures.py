"""Historical short sessions for backward-compatibility tests; not production session creation."""
from learning.models import Question, LearningSession, SessionQuestion
from learning import services
from django.apps import apps
from django.utils import timezone
from importlib import import_module
from eventing.models import PlatformSession, MapFloor
from eventing.catalog import floor_uuid


def prepare_event_context(user):
    # TransactionTestCase flushes seed rows between tests. Recreate only the
    # learning catalogue in these disposable test databases, never at runtime.
    MapFloor.objects.get_or_create(code='campus', defaults={'floor_uuid': floor_uuid('campus'), 'name': '18층 캠퍼스'})
    import_module('eventing.migrations.0007_learning_catalog').add_learning(apps, None)
    if not PlatformSession.objects.filter(user=user, ended_at__isnull=True).exists():
        now = timezone.now()
        PlatformSession.objects.create(user=user, started_at=now, last_seen_at=now)

def start_legacy_session(user, kind, difficulty):
    prepare_event_context(user)
    questions = list(Question.objects.filter(question_type=kind, difficulty=difficulty, is_active=True))
    if len(questions) >= 10:
        return services.start_learning_session(user,kind,difficulty)
    for q in questions:
        services.validate_question(q)
    session=LearningSession.objects.create(user=user,question_type=kind,difficulty=difficulty,total_questions=len(questions))
    for order,q in enumerate(questions,1):
        SessionQuestion.objects.create(session=session,question=q,question_order=order)
    return session
