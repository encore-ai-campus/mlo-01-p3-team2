"""Server-controlled rewards for both multiple-choice and fill-blank answers."""
from django.conf import settings
POINTS_BY_DIFFICULTY = {'beginner': 20, 'intermediate': 50, 'advanced': 80}
def points_for(difficulty):
    policy = getattr(settings, 'LEARNING_POINTS_BY_DIFFICULTY', POINTS_BY_DIFFICULTY)
    amount = policy[difficulty]
    if type(amount) is not int or not 0 <= amount < 2**63:
        raise ValueError('Reward must be a non-negative signed 64-bit integer')
    return amount
def eligibility(answer):
    # Historical answers without a confirmed ledger remain unpaid. Calling this
    # helper must never backfill money or emit events.
    return {'eligible': answer.is_correct, 'quoted_points': points_for(answer.session_question.session.difficulty) if answer.is_correct else 0,
            'attempt_uuid': str(answer.attempt_uuid), 'status': 'not_connected'}
