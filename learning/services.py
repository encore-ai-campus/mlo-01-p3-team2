import random
import uuid
from functools import wraps
from .grading import answers_match
from .point_policy import eligibility
from django.core.exceptions import ValidationError
from django.db import transaction, connection
from django.db.models import F
from django.http import Http404
from django.utils import timezone
from .models import Subject, Difficulty, QuestionType, Question, LearningSession, SessionQuestion, UserAnswer

MAX_ATTEMPTS = 3


def question_progress(item):
    """Derive outcome from preserved answers; never rewrite historical attempts."""
    answers = list(item.answers.all())
    attempts = max((a.attempt_no for a in answers), default=0)
    if any(a.is_correct and a.attempt_no == 1 for a in answers):
        outcome = 'first_try_correct'
    elif any(a.is_correct for a in answers):
        outcome = 'retry_correct'
    elif attempts >= MAX_ATTEMPTS or (answers and item.session.completed_at):
        # Previously completed sessions used the old one-answer completion rule.
        # Keep their completion and answers intact; historical wrong results stay wrong.
        outcome = 'incorrect'
    else:
        outcome = None
    return {'outcome': outcome, 'is_finalized': outcome is not None,
            'attempt_count': attempts, 'max_attempts': MAX_ATTEMPTS,
            'remaining_attempts': 0 if outcome else max(0, MAX_ATTEMPTS - attempts)}


def session_statistics(session, items=None):
    items = list(items if items is not None else session.session_questions.select_related('session').prefetch_related('answers'))
    progress = [question_progress(item) for item in items]
    first = sum(p['outcome'] == 'first_try_correct' for p in progress)
    retry = sum(p['outcome'] == 'retry_correct' for p in progress)
    incorrect = sum(p['outcome'] == 'incorrect' for p in progress)
    answered = sum(p['attempt_count'] > 0 for p in progress)
    return {'first_try_correct_count': first, 'retry_correct_count': retry,
            'final_incorrect_count': incorrect, 'finalized_count': first + retry + incorrect,
            'pending_count': session.total_questions - first - retry - incorrect,
            'correct_count': first + retry, 'answered_count': answered,
            'final_accuracy': round((first + retry) / session.total_questions * 100, 2)}


class LearningError(Exception):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def normalize_answer(value):
    # Python identifiers are case-sensitive. Never evaluate user input.
    return value.strip()


def validate_question(question):
    question.full_clean()
    choices = list(question.choices.all())
    if question.question_type == QuestionType.MULTIPLE_CHOICE:
        if sorted(c.choice_no for c in choices) != [1, 2, 3, 4]:
            raise ValidationError('객관식 문제에는 1~4번 보기 네 개가 필요합니다.')
        if len([c for c in choices if normalize_answer(c.choice_text) == normalize_answer(question.correct_answer)]) != 1:
            raise ValidationError('정답은 보기 텍스트 중 정확히 하나와 일치해야 합니다.')
    elif choices:
        raise ValidationError('빈칸 문제에는 보기가 없어야 합니다.')


def learning_write_transaction(view):
    """Acquire SQLite's writer slot before reading; never upgrade a read lock.

    A zero-row UPDATE obtains a transaction-scoped write reservation without
    changing any record. PostgreSQL retains the existing row-lock behavior.
    This also works inside an outer atomic block; no PRAGMA or timeout changes.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        with transaction.atomic():
            if connection.vendor == 'sqlite':
                table = connection.ops.quote_name(LearningSession._meta.db_table)
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE {table} SET correct_count = correct_count WHERE 0')
            return view(*args, **kwargs)
    return wrapped


@learning_write_transaction
def start_learning_session(user, question_type, difficulty, subject=Subject.PYTHON):
    if subject not in Subject.values or question_type not in QuestionType.values or difficulty not in Difficulty.values:
        raise LearningError('유효한 문제 유형과 난이도를 선택하세요.')
    pool = list(Question.objects.filter(is_active=True, subject=subject, question_type=question_type, difficulty=difficulty).prefetch_related('choices'))
    if not pool:
        raise LearningError('해당 유형과 난이도의 활성 문제가 없습니다.', 'empty_question_pool', 409)
    if len(pool) < 10:
        raise LearningError('활성 문제가 10개 이상 필요합니다.', 'insufficient_question_pool', 409)
    selected = random.sample(pool, 10)
    for question in selected:
        validate_question(question)
    session = LearningSession.objects.create(user=user, subject=subject, question_type=question_type, difficulty=difficulty, total_questions=len(selected))
    for order, question in enumerate(selected, 1):
        # save/full_clean also verifies type/difficulty relationships.
        SessionQuestion.objects.create(session=session, question=question, question_order=order)
    return session


def owned_session(user, session_id, lock=False):
    query = LearningSession.objects.select_for_update() if lock else LearningSession.objects
    try:
        return query.get(pk=session_id, user=user)
    except LearningSession.DoesNotExist:
        raise Http404('세션을 찾을 수 없습니다.')


def session_question(session, order):
    try:
        return session.session_questions.select_related('question').prefetch_related('question__choices').get(question_order=order)
    except SessionQuestion.DoesNotExist:
        raise Http404('문제를 찾을 수 없습니다.')


def get_current_question(user, session_id, order):
    session = owned_session(user, session_id)
    item = session_question(session, order)
    if item.started_at is None:
        # Only the timestamp changes; conditional UPDATE preserves the first
        # viewer timestamp even when two requests arrive at the same time.
        SessionQuestion.objects.filter(pk=item.pk, started_at__isnull=True).update(started_at=timezone.now())
        item.refresh_from_db(fields=['started_at'])
    return item


def score_session(session):
    stats = session_statistics(session)
    return stats['answered_count'], stats['correct_count']


@learning_write_transaction
def submit_answer(user, session_id, order, answer, submission_request_uuid=None):
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 10000:
        raise LearningError('답안은 1~10000자의 비어 있지 않은 문자열이어야 합니다.')
    session = owned_session(user, session_id, lock=True)
    request_uuid = None
    if submission_request_uuid is not None:
        try:
            request_uuid = uuid.UUID(str(submission_request_uuid))
        except (ValueError, TypeError, AttributeError):
            raise LearningError('요청 UUID 형식이 올바르지 않습니다.', 'invalid_submission_uuid')
        previous = UserAnswer.objects.select_related('session_question').filter(submission_request_uuid=request_uuid).first()
        if previous:
            if previous.session_question.session_id != session.pk or previous.session_question.question_order != order or previous.submitted_answer != answer:
                raise LearningError('요청 UUID가 다른 제출에 사용되었습니다.', 'submission_uuid_conflict', 409)
            return previous
    if session.completed_at:
        raise LearningError('완료된 세션에는 제출할 수 없습니다.', 'session_completed', 409)
    item = session_question(session, order)
    if item.started_at is None:
        raise LearningError('문제를 먼저 조회하세요.', 'question_not_viewed', 409)
    item._prefetched_objects_cache['answers'] = list(item.answers.all())
    progress = question_progress(item)
    if progress['is_finalized']:
        code = 'attempt_limit_reached' if progress['outcome'] == 'incorrect' else 'question_finalized'
        raise LearningError('이미 확정된 문제에는 더 제출할 수 없습니다.', code, 409)
    question = item.question
    validate_question(question)
    if question.question_type == QuestionType.MULTIPLE_CHOICE:
        if normalize_answer(answer) not in [normalize_answer(c.choice_text) for c in question.choices.all()]:
            raise LearningError('보기 중 하나의 텍스트를 제출하세요.', 'invalid_choice')
    attempt = progress['attempt_count'] + 1
    if attempt > MAX_ATTEMPTS:
        raise LearningError('문제당 최대 3회만 제출할 수 있습니다.', 'attempt_limit_reached', 409)
    result = UserAnswer.objects.create(session_question=item, submitted_answer=answer,
                                      is_correct=answers_match(question.subject, question.question_type, answer, question.correct_answer), attempt_no=attempt, submission_request_uuid=request_uuid)
    item._prefetched_objects_cache['answers'].append(result)
    # A finalized correct question cannot be submitted again. Wrong attempts
    # do not change the score; avoid a full-session rescan and model validation.
    if result.is_correct:
        LearningSession.objects.filter(pk=session.pk).update(correct_count=F('correct_count') + 1)
    result.response_snapshot = answer_payload(result)
    UserAnswer.objects.filter(pk=result.pk).update(response_snapshot=result.response_snapshot)
    return result


@learning_write_transaction
def complete_session(user, session_id):
    session = owned_session(user, session_id, lock=True)
    if session.completed_at:
        return session
    stats = session_statistics(session)
    if stats['finalized_count'] != session.total_questions:
        raise LearningError('모든 문제가 정답 또는 3회 오답으로 확정되어야 완료할 수 있습니다.', 'unfinalized_questions', 409)
    session.correct_count = stats['correct_count']
    session.completed_at = timezone.now()
    session.save(update_fields=['correct_count', 'completed_at'])
    return session


def answer_payload(result):
    if result.response_snapshot:
        return result.response_snapshot
    progress = question_progress(result.session_question)
    question = result.session_question.question
    revealed = progress['is_finalized']
    data = {'is_correct': result.is_correct, 'attempt_no': result.attempt_no,
            'explanation': question.explanation if revealed else '',
            'question_finished': revealed, 'answer_revealed': revealed,
            'attempts_remaining': progress['remaining_attempts'], **progress,
            'attempt_uuid': str(result.attempt_uuid),
            'submission_request_uuid': str(result.submission_request_uuid) if result.submission_request_uuid else None,
            'points': eligibility(result)}
    if revealed:
        data['correct_answer'] = question.correct_answer
        if question.question_type == QuestionType.MULTIPLE_CHOICE:
            choice = next(c for c in question.choices.all() if normalize_answer(c.choice_text) == normalize_answer(question.correct_answer))
            data['correct_choice_no'] = choice.choice_no
    return data
