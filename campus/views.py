import hashlib
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.models import get_avatar, get_nickname, needs_profile_setup
from .menu_images import FILE_NAME, IMAGE_TYPES, latest_menu, storage_root
from .positions import get_position
from raffle.survey import survey_url


def version_map_asset(match):
    asset = match.group("asset")
    try:
        content = (settings.BASE_DIR / "dist" / asset).read_bytes()
    except OSError:
        return match.group(0)
    version = hashlib.sha256(content).hexdigest()[:12]
    return f'{match.group("attribute")}="{asset}?v={version}"'


@login_required
@never_cache
@require_safe
def map_view(request):
    if needs_profile_setup(request.user):
        return redirect("accounts:setup")
    response = render(request, "index.html")
    html = response.content.decode(response.charset)
    # A changed script gets a fresh browser URL alongside the current HTML.
    html = re.sub(
        r'(?P<attribute>src|href)="(?P<asset>[\w.-]+\.(?:js|css))"',
        version_map_asset,
        html,
    )
    # Reuse the standalone HTML and all its relative CSS, JS, and photo paths.
    html = html.replace(
        "<head>", f'<head>\n  <base href="{escape(static("campus/"))}">', 1
    )
    # The home link must return to the Django view rather than the static folder.
    html = html.replace('href="./"', f'href="{escape(reverse("campus:map"))}"', 1)
    # Add account controls without changing the standalone map source.
    account_styles = f'<link rel="stylesheet" href="{escape(static("accounts/auth.css"))}">'
    html = html.replace("</head>", f"  {account_styles}\n</head>", 1)
    nickname = get_nickname(request.user)
    account_controls = render_to_string("accounts/map_account.html", {
        "nickname": nickname,
        "view_config": {"canZoom": request.user.is_staff},
        "presence_config": {"socketPath": "/ws/campus/", "loginUrl": reverse("accounts:login"), "avatar": get_avatar(request.user), "preferencesKey": f"campus-display-v1:{request.user.pk}", "position": get_position(request.user), "raffleSurveyUrl": survey_url()},
    }, request=request)
    html = html.replace('<div class="top-actions">', f'<div class="top-actions">{account_controls}', 1)
    account_settings = render_to_string("accounts/map_settings.html", {"nickname": nickname}, request=request)
    html = html.replace('<div id="settingsAccount" class="settings-account">',
                        f'<div id="settingsAccount" class="settings-account">{account_settings}', 1)
    response.content = html
    return response


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
