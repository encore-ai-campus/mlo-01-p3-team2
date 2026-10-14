"""화면 데이터를 HTML 로 그린다(설계 §6.6 "6-15 분리"). DB·검증 없이, 백엔드가 준 값만으로.

백엔드 시험도 이 파일을 그대로 써서 화면을 그린다(apps/ads_server/tests/presentation.py) — 그래서 설정의 TEMPLATES 대신 화면 전용 엔진을 쓰고,
설정은 두 쪽에 같은 것(STATIC_URL·URL 이름)만 기댄다. 값의 모양은 백엔드 foundation/presentation.py 와 짝이다."""
import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import django
from django import forms
from django.forms.utils import ErrorDict, ErrorList
from django.middleware.csp import get_nonce
from django.template import Context, Engine
from django.utils.datastructures import MultiValueDict

ROOT = Path(__file__).resolve().parent
ADMIN_TEMPLATES = Path(django.__file__).parent / "contrib/admin/templates"  # 운영 화면은 Django admin 의 모양을 상속한다(admin/base_site.html)
LIBRARIES = {
    "static": "django.templatetags.static",
    "i18n": "django.templatetags.i18n",
    "tz": "django.templatetags.tz",
    "console_format": "ui.templatetags.console_format",
    "console_chart": "ui.templatetags.console_chart",
    "kst": "ui.templatetags.kst",
}
WIDGETS = {cls.__name__: cls for cls in (
    forms.TextInput, forms.NumberInput, forms.EmailInput, forms.URLInput, forms.PasswordInput, forms.HiddenInput, forms.Textarea,
    forms.DateInput, forms.DateTimeInput, forms.TimeInput, forms.CheckboxInput, forms.Select, forms.SelectMultiple, forms.RadioSelect,
    forms.CheckboxSelectMultiple, forms.FileInput, forms.ClearableFileInput,
)}
MULTIPLE = (forms.SelectMultiple, forms.CheckboxSelectMultiple)


@lru_cache(maxsize=1)
def engine():
    return Engine(dirs=[str(ROOT / "templates"), str(ADMIN_TEMPLATES)], libraries=LIBRARIES,
                  loaders=[("django.template.loaders.cached.Loader", ["django.template.loaders.filesystem.Loader"])])


def render(request, presentation):
    """`(HTML, 문맥)`. 문맥에는 요청(현재 경로·메뉴 표시·`{% querystring %}`)과 이 응답의 CSP nonce 를 더한다."""
    context = {key: from_data(value) for key, value in presentation["context"].items()}
    context["messages"] = [Message(**m) for m in context.get("messages", [])]
    context["request"] = request
    context["csp_nonce"] = get_nonce(request)
    template_context = Context(context)
    # RequestContext 는 쓰지 않는다: 늘 붙는 CSRF 문맥 처리기가 프론트 요청으로 새 토큰을 만들어 백엔드의 토큰을 덮는다(백엔드가 거절).
    # `{% querystring %}` 은 context.request 만 본다
    template_context.request = request
    return engine().get_template(presentation["template"]).render(template_context), context


class Record(dict):
    """값 객체·사전. 템플릿은 사전처럼(`a.b` 는 키 먼저), 서식 필터의 파이썬 코드는 속성처럼(`getattr(totals, name)`) 읽는다."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class Message(SimpleNamespace):
    def __str__(self):
        return self.message


class DisplayPage(list):
    """쪽 나누기(Django `Page` 와 같은 이름으로): 줄을 돌고, 번호·앞뒤 쪽을 묻는다."""

    def __init__(self, items, number, num_pages):
        super().__init__(items)
        self.number, self.paginator = number, SimpleNamespace(num_pages=num_pages)
        self.has_previous, self.has_next = number > 1, number < num_pages
        self.previous_page_number, self.next_page_number = number - 1, number + 1


def from_data(value):
    if isinstance(value, list):
        return [from_data(v) for v in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        (key, inner), = value.items()
        if key == "$dt":
            return datetime.datetime.fromisoformat(inner)
        if key == "$date":
            return datetime.date.fromisoformat(inner)
        if key == "$form":
            return display_form(inner)
        if key == "$page":
            return DisplayPage(from_data(inner["items"]), inner["number"], inner["num_pages"])
    return Record({k: from_data(v) for k, v in value.items()})


def display_form(schema):
    """그리기만 하는 폼 — 검증하지 않는다(`is_valid`·`clean` 을 부르지 않는다). 백엔드 폼과 같은 위젯·속성·값·오류라 같은 HTML 이 나온다."""
    form = forms.Form(prefix=schema["prefix"], auto_id=schema["auto_id"])
    values = {}
    for row in schema["fields"]:
        attrs = {**from_data(row["attrs"]), **({"type": row["input_type"]} if row["input_type"] else {})}  # Input 은 type 을 꺼내 입력 종류로 둔다(datetime-local 등)
        widget = WIDGETS[row["widget"]](attrs=attrs, **({"format": row["format"]} if row["format"] else {}))
        if row["choices"] is not None:
            widget.choices = [tuple(c) for c in row["choices"]]
        form.fields[row["name"]] = forms.Field(required=row["required"], label=row["label"], help_text=row["help_text"],
                                               disabled=row["disabled"], widget=widget)
        values[row["name"]] = from_data(row["value"])
    if schema["bound"]:  # 제출한 값을 다시 그린다 — 위젯이 읽는 자리(접두사 붙은 이름)에 둔다
        form.is_bound = True
        form.data = MultiValueDict({form.add_prefix(name): (v if isinstance(form.fields[name].widget, MULTIPLE) else [v])
                                    for name, v in values.items() if v is not None})
    else:
        form.initial = values
    errors = ErrorDict()
    for row in schema["fields"]:
        if row["errors"]:
            errors[row["name"]] = ErrorList(row["errors"], renderer=form.renderer, field_id=form[row["name"]].auto_id)
    if schema["non_field_errors"]:
        errors[forms.forms.NON_FIELD_ERRORS] = ErrorList(schema["non_field_errors"], error_class="nonfield", renderer=form.renderer)
    form._errors = errors  # 정해 두면 errors 를 물어도 검증하지 않는다
    for name, value in schema["extra"].items():
        setattr(form, name, from_data(value))
    return form
