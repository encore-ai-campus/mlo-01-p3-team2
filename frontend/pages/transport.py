"""Forward inputs/cookies unchanged. Decisions and CSRF validation belong to backend."""
from dataclasses import dataclass
import http.client
from urllib.parse import urlsplit
from django.conf import settings
from django.http import HttpResponse

@dataclass
class BackendResponse:
    status: int
    body: bytes
    headers: list

def call_backend(request):
    destination = urlsplit(settings.BACKEND_URL)
    connection_class = http.client.HTTPSConnection if destination.scheme == 'https' else http.client.HTTPConnection
    connection = connection_class(destination.hostname, destination.port, timeout=settings.BACKEND_TIMEOUT)
    headers = {'Host': request.get_host(), 'X-Forwarded-Proto': request.scheme}
    for name in ['Cookie', 'Content-Type', 'X-CSRFToken', 'Origin', 'Referer', 'Accept', 'User-Agent']:
        value = request.headers.get(name)
        if value is not None:
            headers[name] = value
    try:
        connection.request(request.method, request.get_full_path(), body=request.body or None, headers=headers)
        response = connection.getresponse()
        return BackendResponse(response.status, response.read(), response.getheaders())
    finally:
        connection.close()

def apply_headers(response, backend, *, html=False):
    allowed = {'content-type', 'cache-control', 'location', 'expires', 'pragma', 'content-disposition',
               'vary', 'allow', 'etag', 'last-modified'}
    for key, value in backend.headers:
        if key.lower() == 'set-cookie':
            response.cookies.load(value)
        elif key.lower() in allowed and not (html and key.lower() == 'content-type'):
            response[key] = value
    return response

def passthrough(backend):
    return apply_headers(HttpResponse(backend.body, status=backend.status), backend)
