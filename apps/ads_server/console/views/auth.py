from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render, resolve_url
from django.views import View

from billing.api import grant_signup
from foundation.api import Role, SignupRateLimited, client_ip, create_advertiser, record_audit, register_attempt

from ..forms import SignupForm


class SignupView(View):
    template_name = "console/signup.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("advertiser_home")
        return render(request, self.template_name, {"form": SignupForm()})

    def post(self, request):
        try:
            register_attempt(client_ip(request))
        except SignupRateLimited as e:
            response = render(request, "console/signup_limited.html", status=429)
            response["Retry-After"] = str(e.retry_after)
            return response

        form = SignupForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():  # 가입과 지급은 한 트랜잭션: 지급이 실패하면 가입도 취소된다(설계 §4.7)
                    user = create_advertiser(data["username"], data["password"], data["nickname"], data["class_label"])
                    grant_signup(user)
                    record_audit(request, "account.signup", target=user, actor=user, detail={"class_label": user.class_label})
            except ValidationError as e:
                for field, errors in e.message_dict.items():
                    for message in errors:
                        form.add_error(field, message)
            else:
                messages.success(request, "가입이 완료되었습니다. 로그인해 주세요.")
                return redirect("login")
        return render(request, self.template_name, {"form": form}, status=400)


class ConsoleLoginView(LoginView):
    template_name = "console/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        """`next` 가 없을 때 역할별 첫 화면으로. 관리자는 관리자 화면, 광고주는 광고주 화면."""
        if self.request.user.role == Role.ADMIN:
            return resolve_url("admin:index")
        return resolve_url("advertiser_home")


class ConsoleLogoutView(LogoutView):
    """POST 만 받는다(Django 기본)."""
