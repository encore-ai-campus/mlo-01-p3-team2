from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def proxy_count_check(app_configs, **kwargs):
    """TLS 종단 프록시 뒤(SECURE_PROXY_SSL_HEADER)인데 신뢰할 프록시 수가 0 이면 모든 요청이 프록시 IP 하나로 보인다(설계 §10 "가입 시도 제한", 6-3h).

    임시방편: 설정 조합으로 추정한다 — TLS 를 종단하지 않는 프록시, 프록시 없이 수를 1 이상으로 둔 경우(XFF 위조)는 잡지 못한다. 배포 방식(§7-14)이 정해지면 보완.
    """
    if settings.SECURE_PROXY_SSL_HEADER and settings.TRUSTED_PROXY_COUNT <= 0:  # 0 이하면 client_ip 가 REMOTE_ADDR(프록시)만 쓴다
        return [Warning(
            "BEHIND_TLS_PROXY 가 켜져 있는데 TRUSTED_PROXY_COUNT 가 0 이하다 — 모든 요청이 프록시 IP 하나로 보여 가입 제한·로그인 잠금·감사 로그의 IP 가 무너진다.",
            hint="리버스 프록시 뒤라면 TRUSTED_PROXY_COUNT 를 신뢰할 프록시 수로 설정한다(README 배포 점검).",
            id="foundation.W001",
        )]
    return []
