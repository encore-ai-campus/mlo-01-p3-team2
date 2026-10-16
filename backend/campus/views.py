
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect
from config.presentation import presentation_response
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.models import get_avatar, get_nickname, needs_profile_setup
from .menu_images import FILE_NAME, IMAGE_TYPES, latest_menu, storage_root
from .positions import get_position
from raffle.survey import survey_url


@login_required
@never_cache
@require_safe
def map_view(request):
    if needs_profile_setup(request.user):
        return redirect("accounts:setup")
    profile = getattr(request.user, "campus_profile", None)
    return presentation_response(request, "index.html", {
        "nickname": get_nickname(request.user),
        "view_config": {"canZoom": request.user.is_staff,
            "guidePending": bool(profile and not profile.guide_completed),
            "guideCompleteUrl": reverse("accounts-api:guide-complete")},
        "presence_config": {"socketPath": "/ws/campus/", "loginUrl": reverse("accounts:login"),
            "avatar": get_avatar(request.user), "preferencesKey": f"campus-display-v1:{request.user.pk}",
            "position": get_position(request.user), "raffleSurveyUrl": survey_url()},
    })


@login_required
@never_cache
@require_safe
def menu_photo(request):
    metadata = latest_menu()
    return JsonResponse({
        "imageUrl": reverse("campus:menu-image", args=[metadata["filename"]]) if metadata else None,
        "updatedAt": metadata["updated_at"] if metadata else None,
        "sourceName": "더좋은밥상 · 카카오 채널 프로필",
    })


@login_required
@never_cache
@require_safe
def menu_image(request, filename):
    if not FILE_NAME.fullmatch(filename):
        raise Http404
    try:
        photo = (storage_root() / filename).open("rb")
    except OSError:
        raise Http404
    content_type = dict(IMAGE_TYPES.values())[filename.rsplit(".", 1)[1]]
    return FileResponse(photo, content_type=content_type, filename="cafeteria-menu." + filename.rsplit(".", 1)[1])
