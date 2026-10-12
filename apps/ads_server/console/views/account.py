"""광고주 내 정보(Step 3-2f): 닉네임·반 수정과 비밀번호 변경. 규칙은 foundation 서비스(S2), 예외의 화면 변환은 console/errors."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from foundation.api import change_password, update_profile

from ..errors import HANDLED, form_errors
from ..forms import PasswordChangeForm, ProfileForm


def _page(request, profile_form=None, password_form=None, status=200):
    profile_form = profile_form or ProfileForm(initial={"nickname": request.user.nickname, "class_label": request.user.class_label})
    return render(request, "console/my_account.html", {"profile_form": profile_form, "password_form": password_form or PasswordChangeForm()}, status=status)


def my_account(request):
    if request.method != "POST":
        return _page(request)
    form = ProfileForm(request.POST)
    if form.is_valid():
        try:
            update_profile(request.user, **form.cleaned_data)
        except HANDLED as e:
            form_errors(form, e)
        else:
            messages.success(request, "내 정보를 바꿨습니다.")
            return redirect("my_account")
    return _page(request, profile_form=form, status=400)


@require_POST
def my_password(request):
    """현재 비밀번호가 틀리면 400. 로그인과 합쳐 5번 틀리면 axes 미들웨어가 응답을 잠금(429)으로 바꾼다(서비스가 같은 계수를 쓴다)."""
    form = PasswordChangeForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            change_password(request.user, data["current_password"], data["new_password"], request=request)
        except HANDLED as e:
            form_errors(form, e)
        else:
            messages.success(request, "비밀번호를 바꿨습니다. 다른 기기의 로그인은 끝났습니다.")
            return redirect("my_account")
    return _page(request, password_form=form, status=400)
