"""Render backend-provided presentation data without validation or database access."""
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import hashlib
import re
from django import forms
from django.forms.utils import ErrorDict, ErrorList
from django.template import Context, Engine
from django.templatetags.static import static
from django.utils.html import escape

ALLOWED_TEMPLATES = {'index.html', 'accounts/login.html', 'accounts/signup.html',
    'accounts/profile_setup.html', 'accounts/nickname.html', 'learning/standalone.html'}

@lru_cache(maxsize=8)
def template_engine(root, debug=True):
    loaders = ['django.template.loaders.filesystem.Loader']
    if not debug:
        loaders = [('django.template.loaders.cached.Loader', loaders)]
    return Engine(dirs=[str(root / 'dist'), str(root / 'accounts/templates'), str(root / 'learning/templates')],
                  libraries={'static': 'django.templatetags.static'}, loaders=loaders)

def display_form(schema):
    # These fields are rendering objects only. is_valid/clean/save are never called.
    values = {row['name']: row.get('value') for row in schema['fields'] if row.get('value') is not None}
    form = forms.Form(data=values if schema.get('bound') else None, initial=values)
    widget_types = {'text': forms.TextInput, 'password': forms.PasswordInput, 'select': forms.Select, 'radio': forms.RadioSelect}
    for row in schema['fields']:
        kind = row['kind']
        widget = widget_types[kind](attrs=row.get('attrs', {}))
        arguments = {'label': row['label'], 'help_text': row.get('help_text', ''), 'required': row['required'], 'widget': widget}
        field = forms.ChoiceField(choices=row['choices'], **arguments) if kind in {'select', 'radio'} else forms.CharField(**arguments)
        form.fields[row['name']] = field
    form._errors = ErrorDict({key: ErrorList(messages) for key, messages in schema.get('errors', {}).items()})
    return form

def context_from_data(data):
    context = dict(data.get('context', {}))
    context['user'] = SimpleNamespace(**context.get('user', {}))
    if 'form' in context:
        context['form'] = display_form(context['form'])
    return context

def asset_version(root, relative):
    try:
        return hashlib.sha256((root / relative).read_bytes()).hexdigest()[:12]
    except OSError:
        return 'missing'

def render_document(data, root, debug=True):
    root = Path(root)
    name = data['template']
    if name not in ALLOWED_TEMPLATES:
        raise ValueError('Unsupported presentation template')
    engine = template_engine(root, debug)
    context = context_from_data(data)
    def render(name):
        return engine.get_template(name).render(Context(context))
    html = render(name)
    if name == 'index.html':
        files = {'styles': 'learning.css', 'panel': 'learning.js', 'assets': 'classroom-assets.js', 'map': 'classroom-map.js', 'controller': 'classroom.js'}
        context['learning_assets'] = {key: f'{static("learning/" + value)}?v={asset_version(root, "learning/static/learning/" + value)}' for key, value in files.items()}
        html = html.replace('<!-- learning-panels -->', render('learning/map_panels.html'), 1)
        html = html.replace('<!-- learning-assets -->', render('learning/map_assets.html'), 1)
        def version(match):
            asset = match.group('asset')
            return f'{match.group("attribute")}="{asset}?v={asset_version(root, "dist/" + asset)}"'
        html = re.sub(r'(?P<attribute>src|href)="(?P<asset>[\w.-]+\.(?:js|css))"', version, html)
        html = html.replace('<head>', f'<head>\n  <base href="{escape(static("campus/"))}">', 1)
        html = html.replace('href="./"', 'href="/"', 1)
        html = html.replace('</head>', f'<link rel="stylesheet" href="{escape(static("accounts/auth.css"))}">\n</head>', 1)
        html = html.replace('<div class="top-actions">', '<div class="top-actions">' + render('accounts/map_account.html'), 1)
        html = html.replace('<div id="settingsAccount" class="settings-account">', '<div id="settingsAccount" class="settings-account">' + render('accounts/map_settings.html'), 1)
    return html, context
