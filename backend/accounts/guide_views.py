from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Profile


@never_cache
@require_POST
def complete_guide(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    updated = Profile.objects.filter(user=request.user, setup_complete=True).update(guide_completed=True)
    if not updated:
        return JsonResponse({'error': 'profile_setup_required'}, status=409)
    response = JsonResponse({'guideCompleted': True})
    response['Cache-Control'] = 'private, no-store'
    return response
