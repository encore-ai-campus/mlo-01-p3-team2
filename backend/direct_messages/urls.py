from django.urls import path
from . import views

urlpatterns=[
    path('status/',views.status),path('recipients/',views.recipients),
    path('conversations/',views.inbox),path('send/',views.send),
    path('conversations/<uuid:conversation_id>/',views.history),
    path('conversations/<uuid:conversation_id>/read/',views.mark_read),
]
