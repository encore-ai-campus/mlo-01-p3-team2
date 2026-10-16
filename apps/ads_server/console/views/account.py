"""광고주 내 정보(Step 3-2f): 닉네임·반 수정과 비밀번호 변경. 규칙은 foundation 서비스(S2), 예외의 화면 변환은 console/errors."""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing import api as billing
from campaigns import api as campaigns
from foundation.api import change_password, errors, update_profile

from ..errors import submit
from ..forms import PasswordChangeForm, ProfileForm
from .common import present


def _page(request, profile_form=None, password_form=None, status=200):
    profile_form = profile_form or ProfileForm(initial={"nickname": request.user.nickname, "class_label": request.user.class_label})
    try:
        balance = billing.get_wallet(request.user, now=timezone.now()).balance
    except errors.NotFound:  # 가입 절차를 거치지 않은 옛 계정(포인트 화면과 같다)
        balance = None
    summary = {"joined": request.user.created_at, "balance": balance,  # 오른쪽 계정 요약(시안 v2)
               "active_campaigns": sum(1 for c in campaigns.list_campaigns(request.user) if c.status == campaigns.CampaignStatus.ACTIVE)}
    return present(request, "console/my_account.html", {"profile_form": profile_form, "password_form": password_form or PasswordChangeForm(), "summary": summary},
                   status=status)


def my_account(request):
    if request.method != "POST":
        return _page(request)
    form = ProfileForm(request.POST)
    _, status = submit(form, lambda d: update_profile(request.user, **d))
    if status is None:
        messages.success(request, "내 정보를 바꿨습니다.")
        return redirect("my_account")
    return _page(request, profile_form=form, status=status)


@require_POST
def my_password(request):
    """현재 비밀번호가 틀리면 400, 확인한 뒤 계정 상태가 바뀌었으면(비활성화·관리자 초기화) 409.
    로그인과 합쳐 5번 틀리면 axes 미들웨어가 응답을 잠금(429)으로 바꾼다(서비스가 같은 계수를 쓴다)."""
    form = PasswordChangeForm(request.POST)
    _, status = submit(form, lambda d: change_password(request.user, d["current_password"], d["new_password"], request=request))
    if status is None:
        messages.success(request, "비밀번호를 바꿨습니다. 다른 기기의 로그인은 끝났습니다.")
        return redirect("my_account")
    return _page(request, password_form=form, status=status)
