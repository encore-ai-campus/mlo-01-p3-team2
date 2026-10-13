from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.models import needs_profile_setup
from .events import ensure_platform_session, record_content_open
from .models import ContentItem


@never_cache
@require_GET
def open_content(request, content_code):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "다시 로그인해 주세요."}, status=401)
    if needs_profile_setup(request.user):
        return JsonResponse({"error": "닉네임과 캐릭터 설정을 먼저 완료해 주세요."}, status=403)
    content = ContentItem.objects.select_related("category", "zone").filter(
        code=content_code, status=ContentItem.Status.ACTIVE,
        content_kind=ContentItem.ContentKind.EXTERNAL_LINK,
        external_url__isnull=False, zone__isnull=False,
    ).first()
    if content is None:
        return JsonResponse({"error": "콘텐츠를 찾을 수 없어요."}, status=404)
    session_uuid = ensure_platform_session(request.user, request.session)
    # A request to open a catalog item is itself the accepted event; commit before redirecting.
    record_content_open(request.user, session_uuid, content)
    return HttpResponseRedirect(content.external_url)
