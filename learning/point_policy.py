"""Eligibility and configurable quote only. No operational wallet writes."""
from django.conf import settings
POINTS_BY_DIFFICULTY = {'beginner': 20, 'intermediate': 50, 'advanced': 80}
def points_for(difficulty):
    policy = getattr(settings, 'LEARNING_POINTS_BY_DIFFICULTY', POINTS_BY_DIFFICULTY)
    amount = policy[difficulty]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError('Reward must be a non-negative integer')
    return amount
def eligibility(answer):
    return {'eligible': answer.is_correct, 'quoted_points': points_for(answer.session_question.session.difficulty) if answer.is_correct else 0,
            'attempt_uuid': str(answer.attempt_uuid), 'status': 'not_connected'}
