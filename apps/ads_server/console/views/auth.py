from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View

from billing.api import register_advertiser
from foundation.api import SignupRateLimited, client_ip, register_attempt

from ..errors import form_errors
from ..forms import SignupForm
from .home import home_url


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
                register_advertiser(data["username"], data["password"], data["nickname"], data["class_label"], request=request)  # 가입·지급·감사가 한 트랜잭션
            except ValidationError as e:
                form_errors(form, e)
            else:
                messages.success(request, "가입이 완료되었습니다. 로그인해 주세요.")
                return redirect("login")
        return render(request, self.template_name, {"form": form}, status=400)


class ConsoleLoginView(LoginView):
    template_name = "console/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        """`next` 가 없을 때 역할별 첫 화면으로."""
        return home_url(self.request.user)


class ConsoleLogoutView(LogoutView):
    """POST 만 받는다(Django 기본)."""
