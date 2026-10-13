from django.urls import include, path, re_path
from pages import views

account_patterns = [path(route, views.display, name=name) for route, name in [
    ('login/', 'login'), ('signup/', 'signup'), ('setup/', 'setup'), ('nickname/', 'nickname'), ('logout/', 'logout'),
    ('session/status/', 'session-status'), ('session/activity/', 'session-activity')]]
urlpatterns = [
    path('', include(([path('', views.display, name='map')], 'campus'), namespace='campus')),
    path('accounts/', include((account_patterns, 'accounts'), namespace='accounts')),
    path('learning/', views.display, name='learning-home'),
    re_path(r'^api/.*$', views.forward),
    path('content/<slug:content_code>/open/', views.forward, name='content-open'),
    path('health/', views.health),
]
