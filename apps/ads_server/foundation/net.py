import ipaddress

from django.conf import settings


def client_ip(request):
    """클라이언트 IP. **로그인 잠금(axes)과 감사 로그가 같은 판정을 쓴다.**

    TRUSTED_PROXY_COUNT 가 0 이면 REMOTE_ADDR 만 쓴다. 프록시 뒤에서는 신뢰할 프록시 수(n)를 설정하고,
    X-Forwarded-For 의 **오른쪽에서 n번째** 값을 쓴다(우리 프록시가 덧붙인 값만 믿고 앞쪽의 위조 값은 무시).
    """
    remote = request.META.get("REMOTE_ADDR") or ""
    n = settings.TRUSTED_PROXY_COUNT
    if n > 0:
        parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(parts) >= n:
            candidate = parts[-n]
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                return remote
            return candidate
    return remote
