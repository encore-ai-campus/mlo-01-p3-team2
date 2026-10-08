import json
import logging

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
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


class CampusLogoutView(LogoutView):
    def post(self, request, *args, **kwargs):
        # Same CSRF-protected POST saves the final frame before deleting the session.
        raw = request.POST.get("last_position", "")
        if request.user.is_authenticated and 0 < len(raw) <= 1024:
            try:
                save_position(request.user, json.loads(raw))
            except (ValueError, RecursionError):
                pass
            except DatabaseError:
                logging.getLogger(__name__).exception("Could not save the logout position")
        return super().post(request, *args, **kwargs)


class CampusLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse("accounts:setup") if needs_profile_setup(self.request.user) else super().get_success_url()


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class SignUpView(FormView):
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
        login(self.request, user)
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
