"""화면 데이터(설계 §6.6 "6-15 분리"): 백엔드는 우리 화면의 HTML 을 그리지 않고 `{"presentation": {"template", "context"}}` 를 돌려준다.
프론트(apps/ads_frontend)가 같은 템플릿으로 그린다 — 시험은 그 렌더러를 그대로 써서 HTML 을 본다(tests/presentation.py).

값의 모양: 값 객체(dataclass)는 필드 + 속성, UUID 는 문자열, 시각·날짜는 표시를 붙인 ISO(`{"$dt": …}`·`{"$date": …}`), 폼은 `{"$form": …}`
(칸마다 그리는 데 필요한 것 — 프론트가 같은 위젯으로 다시 만든다), 쪽 나누기는 `{"$page": …}`. 그 밖의 것(ORM 객체 등)은 실수로 새지 않게
TypeError 다(§6.6 규칙 4). 콘솔 뷰·오류 화면·로그인 잠금이 이것 하나를 쓴다(foundation 이라 계층과 상관없이 부를 수 있다)."""
import dataclasses
import datetime
import inspect
import uuid

from django import forms
from django.contrib.messages import get_messages
from django.core.paginator import Page
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.functional import Promise

SKIPPED = {"view", "site"}  # Django 의 클래스 뷰가 문맥에 넣는 객체 — 화면이 쓰지 않는다


def present(request, template, context=None, status=200, session=True):
    """`render(request, template, context, status)` 자리에 쓴다. 문맥 처리기(사용자·메시지·CSRF)가 하던 것도 여기서 싣는다.
    `session=False`: 세션을 건드리지 않는 화면(오류 화면 — 제목·문구만 그린다). 사용자·메시지·CSRF 토큰을 싣지 않아 그 사이의 안내 메시지를 먹지 않고
    `Vary: Cookie`·쿠키를 남기지 않는다(이미지 오류 응답에 쿠키가 없게, 계약 C3). DB 장애의 500 이 세션을 읽다 다시 실패할 일도 없다(6-16e)."""
    data = {key: to_data(value) for key, value in (context or {}).items() if key not in SKIPPED}
    if session:
        data["user"] = _user(getattr(request, "user", None))  # 인증 미들웨어 앞에서 끊는 오류(본문 크기 등)에는 사용자가 아직 없다
        data["messages"] = [{"message": str(m), "tags": m.tags, "level_tag": m.level_tag} for m in get_messages(request)]
        data["csrf_token"] = get_token(request)
    return JsonResponse({"presentation": {"template": template, "context": data}}, status=status)


def to_data(value):
    if value is None or isinstance(value, (bool, int, float, str)):  # str 의 하위 클래스(TextChoices)도 값 그대로
        return value
    if isinstance(value, (uuid.UUID, Promise)):  # Promise: 번역 지연 문자열(관리 사이트의 앱·모델 이름 등)
        return str(value)
    if isinstance(value, datetime.datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"$date": value.isoformat()}
    if isinstance(value, forms.BaseForm):
        return {"$form": _form(value)}
    if isinstance(value, Page):
        return {"$page": {"items": [to_data(v) for v in value], "number": value.number, "num_pages": value.paginator.num_pages,
                          "count": value.paginator.count}}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        data = {f.name: to_data(getattr(value, f.name)) for f in dataclasses.fields(value)}
        data.update({name: to_data(getattr(value, name)) for name, _ in inspect.getmembers(type(value), lambda a: isinstance(a, property))})
        return data
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return {k: to_data(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {str(k): to_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_data(v) for v in value]
    raise TypeError(f"화면 데이터로 보낼 수 없는 값: {type(value).__name__}")


def _form(form):
    """프론트가 같은 위젯으로 같은 HTML 을 그리는 데 필요한 것. 값은 위젯이 받는 그대로(`BoundField.value()` — 시간대 변환까지 한 값)."""
    fields = []
    for bound in form:
        field, widget = bound.field, bound.field.widget
        fields.append({
            "name": bound.name, "label": str(bound.label), "help_text": str(field.help_text or ""), "required": field.required,
            "disabled": field.disabled, "widget": _widget_name(widget), "input_type": widget.input_type if isinstance(widget, forms.widgets.Input) else None, "attrs": to_data(widget.attrs),
            "format": getattr(widget, "format", None), "choices": [[str(k), str(v)] for k, v in widget.choices] if hasattr(widget, "choices") else None,
            "value": None if _never_rendered(widget) else to_data(bound.value()), "errors": [str(e) for e in bound.errors],
        })
    return {"prefix": form.prefix, "auto_id": form.auto_id, "bound": form.is_bound, "fields": fields,
            "non_field_errors": [str(e) for e in form.non_field_errors()],
            "extra": {name: to_data(getattr(form, name)) for name in getattr(form, "PRESENTED", ())}}


def _never_rendered(widget):
    """값을 그리지 않는 위젯(파일·비밀번호)은 값을 싣지 않는다 — 올린 파일 객체나 비밀번호가 화면 데이터로 나가지 않게."""
    return isinstance(widget, forms.FileInput) or (isinstance(widget, forms.PasswordInput) and not widget.render_value)


def _widget_name(widget):
    """Django 위젯의 이름(프론트가 같은 클래스로 다시 만든다). 우리 위젯은 Django 위젯을 그대로 쓴다 — 하위 클래스면 실수이므로 TypeError."""
    if type(widget).__module__.startswith("django.forms"):
        return type(widget).__name__
    raise TypeError(f"Django 위젯이 아니다: {type(widget).__name__}")


def _user(user):
    if user is None or not user.is_authenticated:
        return {"is_authenticated": False, "is_active": False, "is_staff": False}
    data = {"is_authenticated": True, "is_active": user.is_active, "is_staff": user.is_staff, "username": user.username,
            "role": user.role, "nickname": user.nickname, "class_label": user.class_label,
            "get_username": user.get_username(), "has_usable_password": user.has_usable_password()}  # get_* 는 관리 템플릿이 부르는 메서드의 값
    if hasattr(user, "get_short_name"):  # 없으면 관리 템플릿은 빈 값으로 본다 — 싣지 않으면 프론트도 같다
        data["get_short_name"] = user.get_short_name()
    return data
