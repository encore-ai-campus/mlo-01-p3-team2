from django.urls import path
from . import views

urlpatterns = [
    path('csrf/', views.csrf),
    path('wallet/', views.wallet),
    path('wallet/history/', views.wallet_history),
    path('content-open/', views.content_open),
    path('sessions/', views.sessions),
    path('sessions/<int:session_id>/', views.session_detail),
    path('sessions/<int:session_id>/questions/<int:order>/', views.question_detail),
    path('sessions/<int:session_id>/questions/<int:order>/answers/', views.answers),
    path('sessions/<int:session_id>/complete/', views.completion),
]
