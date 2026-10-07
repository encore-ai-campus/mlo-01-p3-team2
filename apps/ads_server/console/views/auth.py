from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View

from foundation.api import SignupRateLimited, client_ip, create_advertiser, register_attempt

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
                create_advertiser(data["username"], data["password"], data["nickname"], data["class_label"])
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


class ConsoleLogoutView(LogoutView):
    """POST 만 받는다(Django 기본)."""
