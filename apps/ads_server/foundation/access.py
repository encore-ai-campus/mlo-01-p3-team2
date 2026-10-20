"""접근 통제 (설계 §5.1, 위협 T3·T4·T7).

1. 기본 거부: Django 내장 LoginRequiredMiddleware(공개 뷰만 @login_not_required 로 표시).
2. 역할 게이트: settings.ACCESS_MAP 의 접두사로 역할을 검사한다. 새 URL 을 접두사 밑에 두면 자동으로 보호된다.
3. 소유권 헬퍼: 남의 객체는 404(존재 여부를 알리지 않는다).
4. 역할 검사: 관리자·광고주 전용 서비스 함수의 첫 줄(활성 상태로 로그인한 그 역할만).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from .errors import Forbidden
from .models import Role


class RoleGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user = request.user
        for rule in settings.ACCESS_MAP:
            if path.startswith(rule["prefix"]):
                authenticated = user.is_authenticated
                if rule["hide"]:
                    if not authenticated or user.role != rule["role"]:
                        raise Http404  # 관리자 화면: 익명·다른 역할 모두에게 존재를 숨긴다
                elif authenticated and user.role != rule["role"]:
                    raise PermissionDenied  # 익명은 통과 → LoginRequiredMiddleware 가 로그인으로 보낸다
                break
        return self.get_response(request)


def owned_or_404(queryset, user, owner_field="owner", **lookup):
    """소유자가 user 인 객체 하나. 남의 객체·없는 객체·형식이 틀린 ID 모두 404 (403 이 아니다: 존재 여부를 알리지 않는다)."""
    try:
        return queryset.filter(**{owner_field: user}).get(**lookup)
    except (queryset.model.DoesNotExist, ValidationError, ValueError, TypeError):
        raise Http404


def _require_role(user, role, message):
    if not (getattr(user, "is_authenticated", False) and user.is_active and user.role == role):
        raise Forbidden(message)


def require_admin(actor):
    _require_role(actor, Role.ADMIN, "관리자만 할 수 있습니다.")


def require_advertiser(user, message="광고주만 할 수 있습니다."):
    _require_role(user, Role.ADVERTISER, message)
