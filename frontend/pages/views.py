import http.client
import json
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from .transport import call_backend, apply_headers, passthrough
from .rendering import render_document

def unavailable(request):
    if request.path.startswith('/api/'):
        return JsonResponse({'error': 'backend_unavailable', 'message': '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.'}, status=502)
    return HttpResponse('<!doctype html><html lang="ko"><meta charset="utf-8"><title>연결 확인</title><main><h1>서버 연결을 확인해 주세요</h1><p>잠시 후 다시 시도해 주세요.</p></main></html>', status=502)

def forward(request, **kwargs):
    try:
        return passthrough(call_backend(request))
    except (OSError, http.client.HTTPException, TimeoutError):
        return unavailable(request)

def display(request, **kwargs):
    try:
        backend = call_backend(request)
    except (OSError, http.client.HTTPException, TimeoutError):
        return unavailable(request)
    if backend.status not in {200, 400}:
        return passthrough(backend)
    try:
        data = json.loads(backend.body)
        if 'presentation' not in data:
            return passthrough(backend)
        html, _ = render_document(data['presentation'], settings.BASE_DIR, settings.DEBUG)
    except (ValueError, KeyError, TypeError):
        return unavailable(request)
    return apply_headers(HttpResponse(html, status=backend.status), backend, html=True)

@require_GET
def health(request):
    return JsonResponse({'service': 'frontend', 'status': 'ok'})
