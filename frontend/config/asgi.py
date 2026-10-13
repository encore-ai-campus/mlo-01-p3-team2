import os
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_application = get_asgi_application()
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from pages.sockets import BackendSocket

application = ProtocolTypeRouter({'http': django_application,
    'websocket': URLRouter([path('ws/campus/', BackendSocket.as_asgi())])})
