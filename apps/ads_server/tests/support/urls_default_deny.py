"""기본 거부 확인용 URL 설정: 표시 없는 뷰는 로그인이 필요해야 한다."""
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.urls import path


def unmarked(request):
    return HttpResponse("secret")


@login_not_required
def login_page(request):
    return HttpResponse("login")


urlpatterns = [
    path("unmarked/", unmarked),
    path("accounts/login/", login_page, name="login"),
]
