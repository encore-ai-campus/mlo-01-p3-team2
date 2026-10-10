"""한 번만 쓰는 폼 토큰. 새로 고침·뒤로 가기로 같은 폼이 다시 제출돼도 한 번만 처리한다(키 발급·광고 만들기처럼 두 번 하면 안 되는 동작).

토큰은 비밀이 아니다(CSRF 가 따로 지킨다). 세션에 용도와 함께 두고, 쓰면 지운다. 세션에 쌓이지 않게 최근 것만 둔다.
"""
import secrets

SESSION_KEY = "console_once"
KEEP = 20


def issue(request, purpose):
    pending = request.session.get(SESSION_KEY, {})
    token = secrets.token_urlsafe(16)
    pending[token] = purpose
    request.session[SESSION_KEY] = dict(list(pending.items())[-KEEP:])
    return token


def consume(request, purpose, token):
    """처음 쓰는 그 용도의 토큰이면 지우고 True. 이미 썼거나 모르는 토큰이면 False."""
    pending = request.session.get(SESSION_KEY, {})
    if not isinstance(token, str) or pending.get(token) != purpose:
        return False
    del pending[token]
    request.session[SESSION_KEY] = pending
    return True
