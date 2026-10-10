"""서비스의 예외를 화면으로 바꾸는 **한 곳**(설계 §6.6 규칙 2, 계획 §8.1.1). 뷰는 서비스를 부르고, 예외는 여기로 넘긴다.

- 입력 오류(`ValidationError`, 위치가 있는 `InvalidRequest`, 이미지 거절)와 상태 충돌(409)은 **폼 오류**나 메시지가 된다.
- 없음(404)·권한 없음(403)은 화면에 적지 않고 그 HTTP 응답으로, 서버 쪽 문제(5xx)와 모르는 예외는 그대로 다시 던진다.
"""
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.http import Http404

from assets.api import ImageRejected
from foundation.api import errors


def _not_shown(error):
    """화면에 적지 않을 예외면 알맞게 던진다."""
    if isinstance(error, errors.NotFound):
        raise Http404 from error
    if isinstance(error, errors.Forbidden):
        raise PermissionDenied(str(error)) from error
    if isinstance(error, errors.ApiError) and error.status >= 500:
        raise error
    if not isinstance(error, (ValidationError, ImageRejected, errors.ApiError)):
        raise error


def _field(form, pointer, pointers):
    """서비스 오류의 위치(`/name`, `/campaign/name`) → 폼 칸. 정한 대응이 없으면 위치의 마지막 조각이 폼의 칸일 때 그 칸, 아니면 폼 전체."""
    if pointers and pointer in pointers:
        return pointers[pointer]
    last = pointer.rsplit("/", 1)[-1]
    return last if last in form.fields else None


def form_errors(form, error, pointers=None, image_field=None):
    """`error` 를 `form` 의 오류로 붙인다. `pointers`: 서비스 오류 위치 → 폼 칸 이름. `image_field`: 이미지 거절을 붙일 칸."""
    _not_shown(error)
    if isinstance(error, ValidationError):
        if hasattr(error, "error_dict"):
            for field, messages in error.message_dict.items():
                form.add_error(field if field != NON_FIELD_ERRORS and field in form.fields else None, messages)
        else:
            form.add_error(None, error.messages)
    elif isinstance(error, ImageRejected):
        form.add_error(image_field, str(error))
    elif error.errors:
        for item in error.errors:
            form.add_error(_field(form, item.get("pointer", ""), pointers), item["message"])
    else:
        form.add_error(None, message_of(error))


def message_of(error):
    """폼이 없는 동작(목록의 버튼 등)의 결과 메시지 한 줄."""
    _not_shown(error)
    if isinstance(error, ValidationError):
        return " ".join(error.messages)
    if isinstance(error, ImageRejected):
        return str(error)
    if error.errors:
        return " ".join(item["message"] for item in error.errors)
    return error.detail or error.title
