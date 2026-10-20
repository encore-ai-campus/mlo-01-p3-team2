"""Backend-owned form state and permissions; no HTML rendering or UI imports."""
from django import forms
from django.http import JsonResponse
from django.middleware.csrf import get_token
from accounts.session_policy import session_context


def form_state(form):
    fields = []
    for bound in form:
        field = bound.field
        widget = field.widget
        kind = 'password' if isinstance(widget, forms.PasswordInput) else 'radio' if isinstance(widget, forms.RadioSelect) else 'select' if isinstance(widget, forms.Select) else 'text'
        attrs = dict(widget.attrs)
        for attribute in ('max_length', 'min_length'):
            value = getattr(field, attribute, None)
            if value is not None:
                attrs[attribute.replace('_', '')] = value
        def choices(rows):
            return [[str(key), choices(label) if isinstance(label, (list, tuple)) else str(label)] for key, label in rows]
        fields.append({'name': bound.name, 'label': str(field.label or ''), 'kind': kind,
                       'required': field.required, 'help_text': str(field.help_text or ''),
                       'attrs': attrs, 'value': None if kind == 'password' else bound.value(),
                       'choices': choices(getattr(field, 'choices', ()))})
    return {'fields': fields, 'errors': {key: [str(message) for message in messages] for key, messages in form.errors.items()},
            'bound': form.is_bound}


def presentation_response(request, template, context=None, status=200):
    context = {key: value for key, value in (context or {}).items() if key not in {'view', 'site'}}
    if 'form' in context:
        context['form'] = form_state(context['form'])
    context['user'] = {'is_authenticated': request.user.is_authenticated,
                       'is_staff': request.user.is_staff if request.user.is_authenticated else False}
    context['csrf_token'] = get_token(request)
    context.update(session_context(request))
    response = JsonResponse({'presentation': {'template': template, 'context': context}}, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


class PresentationMixin:
    def render_to_response(self, context, **response_kwargs):
        return presentation_response(self.request, self.template_name, context,
                                     status=response_kwargs.get('status', 200))
