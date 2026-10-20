import logging

from django.contrib.auth import login
from campus import session_registry
from accounts.session_policy import notify_expiry
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import DatabaseError, transaction
from django.shortcuts import redirect
from config.presentation import PresentationMixin, presentation_response as render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import FormView

from .avatars import avatar_options
from .cohorts import allowed_avatars
from .forms import LoginForm, NicknameForm, ProfileSetupForm, SignUpForm
from .models import Profile, needs_profile_setup
from campus.positions import save_position
from .session_policy import start_login
from eventing.events import SESSION_KEY, end_platform_session


class CampusLogoutView(LogoutView):
    def post(self, request, *args, **kwargs):
        # Same CSRF-protected POST saves the final frame before deleting the session.
        key = request.session.session_key
        if request.user.is_authenticated:
            snapshot = session_registry.latest(key, request.user.pk)
            if snapshot:
                try:
                    save_position(request.user, *snapshot, session_uuid=request.session.get(SESSION_KEY))
                except DatabaseError:
                    logging.getLogger(__name__).exception("Could not save server-owned logout position")
        if request.user.is_authenticated:
            end_platform_session(request.user, request.session, "LOGOUT")
        response = super().post(request, *args, **kwargs)
        if key:
            notify_expiry(key, "signed_out")
        return response


class CampusLoginView(PresentationMixin, LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        start_login(self.request.session, self.request.user)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session_expired_message"] = {
            "idle": "활동이 없어 자동 로그아웃됐습니다. 다시 로그인해 주세요.",
            "maximum": "로그인 유지 시간이 끝났습니다. 다시 로그인해 주세요.",
            "replaced": "다른 브라우저에서 같은 계정으로 로그인해 기존 접속이 종료됐습니다.",
        }.get(self.request.GET.get("expired"), "")
        return context

    def get_success_url(self):
        return reverse("accounts:setup") if needs_profile_setup(self.request.user) else super().get_success_url()


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class SignUpView(PresentationMixin, FormView):
    template_name = "accounts/signup.html"
    form_class = SignUpForm
    success_url = reverse_lazy("accounts:setup")
    http_method_names = ["get", "post", "head", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:setup" if needs_profile_setup(request.user) else "campus:map")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            from learning.point_integration import ensure_wallet
            ensure_wallet(user)
        login(self.request, user)
        start_login(self.request.session, user)
        return super().form_valid(form)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def profile_setup_view(request):
    profile = Profile.objects.filter(user=request.user).first()
    if profile is None or profile.setup_complete:
        return redirect("campus:map")
    form = ProfileSetupForm(request.POST if request.method == "POST" else None, cohort=profile.cohort)
    if request.method == "POST" and form.is_valid():
        # A single conditional write freezes the first successful selection, even across tabs.
        Profile.objects.filter(pk=profile.pk, cohort=profile.cohort, setup_complete=False).update(
            nickname=form.cleaned_data["nickname"], avatar=form.cleaned_data["avatar"], setup_complete=True,
        )
        return redirect("campus:map")
    return render(request, "accounts/profile_setup.html", {
        "form": form, "cohort_label": profile.get_cohort_display(), "course_label": profile.course.upper(),
        "avatar_options": avatar_options(allowed_avatars(profile.cohort)),
    })


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def nickname_view(request):
    if needs_profile_setup(request.user):
        return redirect("accounts:setup")
    profile = Profile.objects.filter(user=request.user).first() or Profile(user=request.user)
    form = NicknameForm(request.POST if request.method == "POST" else None, instance=profile)
    if request.method == "POST" and form.is_valid():
        profile = form.save(commit=False)
        # Leave location checkpoints written by another open map untouched.
        profile.save(update_fields=["nickname"] if profile.pk else None)
        return redirect("campus:map")
    return render(request, "accounts/nickname.html", {"form": form})
