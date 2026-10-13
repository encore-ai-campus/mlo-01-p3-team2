"""Backend chooses lunch; browser only animates the returned result."""
import secrets
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from accounts.models import needs_profile_setup

OPTIONS = ('한식', '일식', '양식', '중식', '분식', '패스트푸드', '베트남음식', '구내식당')

@never_cache
@require_POST
def spin(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인 후 이용해 주세요.'}, status=401)
    if needs_profile_setup(request.user):
        return JsonResponse({'error': '프로필 설정을 먼저 완료해 주세요.'}, status=403)
    index = secrets.randbelow(len(OPTIONS))
    return JsonResponse({'index': index, 'label': OPTIONS[index],
                         'jitter': secrets.randbelow(28001) / 1000 - 14,
                         'turns': 5 + secrets.randbelow(3)})
