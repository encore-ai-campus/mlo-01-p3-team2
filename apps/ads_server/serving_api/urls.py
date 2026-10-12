from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("decisions", views.create_decision),
    path("decisions/<str:decision_id>", views.get_decision),
    path("decisions/<str:decision_id>/reactions/<str:reaction_id>", views.reaction),  # 형식이 틀린 ID 는 뷰에서 404(없는 것과 같다)
]
