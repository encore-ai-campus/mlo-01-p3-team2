from django.conf import settings
from django.urls import include, path, re_path

from ui import routes, views


def _named(table):
    return [path(route, views.display, name=name) for route, name in table]


urlpatterns = [
    path("health/", views.health),
    re_path(r"^api/media/", views.not_public),
    path(settings.ADMIN_URL_PATH + "operator/", include((_named(routes.OPERATOR), "operator"))),
    path(settings.ADMIN_URL_PATH, include((_named(routes.ADMIN), "admin"))),
    *_named(routes.CONSOLE),
    re_path(r"^", views.display),  # 나머지(관리 사이트의 다른 화면·이미지·클릭 이동 등)도 그대로 넘긴다
]
