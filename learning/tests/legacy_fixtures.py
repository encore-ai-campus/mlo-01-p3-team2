"""Historical short sessions for backward-compatibility tests; not production session creation."""
from learning.models import Question, LearningSession, SessionQuestion
from learning import services

def start_legacy_session(user, kind, difficulty):
    questions = list(Question.objects.filter(question_type=kind, difficulty=difficulty, is_active=True))
    if len(questions) >= 10:
        return services.start_learning_session(user,kind,difficulty)
    for q in questions:
        services.validate_question(q)
    session=LearningSession.objects.create(user=user,question_type=kind,difficulty=difficulty,total_questions=len(questions))
    for order,q in enumerate(questions,1):
        SessionQuestion.objects.create(session=session,question=q,question_order=order)
    return session
