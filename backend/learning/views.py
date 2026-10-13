import json
import logging
import os
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.db.models import Sum, Count
from django.http import JsonResponse, Http404
from config.presentation import presentation_response as render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from . import services
from .models import PointLedger
from .point_integration import wallet_balance
from .point_policy import points_for
from eventing.events import SESSION_KEY

logger = logging.getLogger(__name__)


@login_required
@require_GET
def learning_page(request):
    return render(request, 'learning/standalone.html')


def csrf_failure(request, reason=''):
    return JsonResponse({'error': 'csrf_failed', 'message': 'CSRF 토큰을 확인하세요.'}, status=403)


def endpoint(method):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method != method:
                response = JsonResponse({'error': 'method_not_allowed'}, status=405)
                response['Allow'] = method
                return response
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'authentication_required'}, status=401)
            try:
                return view(request, *args, **kwargs)
            except services.LearningError as error:
                return JsonResponse({'error': error.code, 'message': str(error)}, status=error.status)
            except ValidationError as error:
                return JsonResponse({'error': 'validation_error', 'message': '; '.join(error.messages)}, status=400)
            except Http404:
                return JsonResponse({'error': 'not_found'}, status=404)
            except OperationalError as error:
                if 'locked' not in str(error).lower():
                    raise
                # Route template excludes user/session identifiers and query data.
                route = request.resolver_match.route if request.resolver_match else '<unresolved>'
                logger.warning('learning_db_locked path=%s pid=%s exception_type=%s',
                               route, os.getpid(), type(error).__name__)
                return JsonResponse({'error': 'database_busy', 'message': '잠시 후 재시도하세요.'}, status=503)
        return wrapped
    return decorator


def body(request):
    if request.content_type != 'application/json':
        raise services.LearningError('Content-Type: application/json이 필요합니다.', 'unsupported_media_type', 415)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise services.LearningError('올바른 JSON을 보내세요.', 'invalid_json')
    if not isinstance(data, dict):
        raise services.LearningError('JSON 객체가 필요합니다.', 'invalid_json')
    return data


def session_data(session):
    items = list(session.session_questions.select_related('session').prefetch_related('answers'))
    stats = services.session_statistics(session, items)
    answered, correct = stats['answered_count'], stats['correct_count']
    data = {'session_id': session.pk, 'subject': session.subject, 'question_type': session.question_type, 'difficulty': session.difficulty,
            'total_questions': session.total_questions, 'correct_count': correct,
            'answered_count': answered, 'unanswered_count': session.total_questions - answered,
            'incorrect_count': answered - correct, 'accuracy': round(correct / session.total_questions * 100, 2),
            **stats,
            'started_at': session.started_at.isoformat(),
            'completed_at': session.completed_at.isoformat() if session.completed_at else None,
            'questions': [{'question_id': i.question_id, 'question_order': i.question_order,
                           'started_at': i.started_at.isoformat() if i.started_at else None,
                           'answered': bool(list(i.answers.all())),
                           **services.question_progress(i)} for i in items]}
    data['passed'] = (session.correct_count >= 7) if session.completed_at and session.total_questions == 10 else None
    data['pass_threshold'] = 7
    correct_answers = [answer for item in items for answer in item.answers.all() if answer.is_correct]
    quoted = [answer.response_snapshot.get('points', {}).get('quoted_points') for answer in correct_answers]
    paid = PointLedger.objects.filter(answer__session_question__session=session).aggregate(total=Sum('delta'), count=Count('pk'))
    data['points_summary'] = {'status': 'connected', 'eligible_count': correct,
                              'quoted_total': sum(quoted) if all(isinstance(value, int) for value in quoted) else None,
                              'granted_total': paid['total'] or 0, 'granted_count': paid['count'],
                              'unpaid_legacy_count': sum(a.response_snapshot.get('points', {}).get('status', 'not_connected') == 'not_connected' for a in correct_answers),
                              'wallet_balance': wallet_balance(session.user)}

    if session.completed_at:
        data['wrong_questions'] = []
        for item in items:
            if services.question_progress(item)['outcome'] != 'incorrect':
                continue
            last = max(item.answers.all(), key=lambda a: a.attempt_no, default=None)
            if not last or last.attempt_no < services.MAX_ATTEMPTS:
                continue
            question = item.question
            data['wrong_questions'].append({
                'question_order': item.question_order, 'question_text': question.question_text,
                'question_type': question.question_type, 'code_snippet': question.code_snippet,
                'submitted_answer': last.submitted_answer, 'explanation': question.explanation,
                **revealed_answer(question)})
    return data


def revealed_answer(question):
    data = {'correct_answer': question.correct_answer}
    if question.question_type == 'multiple_choice':
        choice = next((c for c in question.choices.all()
                       if services.normalize_answer(c.choice_text) == services.normalize_answer(question.correct_answer)), None)
        if choice:
            data['correct_choice_no'] = choice.choice_no
    return data


@ensure_csrf_cookie
@endpoint('GET')
def csrf(request):
    return JsonResponse({'detail': 'CSRF cookie set'})


@endpoint('GET')
def wallet(request):
    return JsonResponse({'balance': wallet_balance(request.user)})


@endpoint('POST')
def content_open(request):
    data = body(request)
    content, point_wallet = services.open_learning_content(request.user, request.session.get(SESSION_KEY),
        data.get('subject', 'python'), data.get('question_type'))
    return JsonResponse({'content_uuid': str(content.pk), 'wallet_balance': point_wallet.balance,
                         'points_by_difficulty': {level: points_for(level) for level in services.Difficulty.values}}, status=201)


@endpoint('POST')
def sessions(request):
    data = body(request)
    session = services.start_learning_session(request.user, data.get('question_type'), data.get('difficulty'), data.get('subject', 'python'))
    return JsonResponse(session_data(session), status=201)


@endpoint('GET')
def session_detail(request, session_id):
    return JsonResponse(session_data(services.owned_session(request.user, session_id)))


@endpoint('GET')
def question_detail(request, session_id, order):
    item = services.get_current_question(request.user, session_id, order)
    question = item.question
    data = {field: getattr(question, field) for field in ['question_id', 'subject', 'question_type', 'difficulty', 'category', 'question_text', 'code_snippet']}
    data['question_uuid'] = str(question.question_uuid)
    if question.question_type == 'multiple_choice':
        data['choices'] = [{'choice_uuid': str(c.choice_uuid), 'choice_no': c.choice_no, 'choice_text': c.choice_text} for c in question.choices.all()]
    return JsonResponse({'session_id': session_id, 'question_order': order, 'total_questions': item.session.total_questions,
                         'started_at': item.started_at.isoformat(), 'question': data,
                         **services.question_progress(item)})


@endpoint('POST')
def answers(request, session_id, order):
    data = body(request)
    services.parse_uuid4(data.get('submission_request_uuid'))
    result = services.submit_answer(request.user, session_id, order, data.get('answer'), data.get('submission_request_uuid'),
        choice_uuid=data.get('choice_uuid'), platform_session_uuid=request.session.get(SESSION_KEY))
    return JsonResponse(services.answer_payload(result), status=201)


@endpoint('POST')
def completion(request, session_id):
    return JsonResponse(session_data(services.complete_session(request.user, session_id)))
