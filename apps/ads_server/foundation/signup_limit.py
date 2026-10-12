import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SignupAttempt

WINDOW = timedelta(hours=1)
KEEP = timedelta(days=1)


class SignupRateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__("가입 시도가 너무 많습니다.")
        self.retry_after = retry_after  # 초


def register_attempt(ip, now=None):
    """가입 시도를 기록한다. IP 당 시간당 SIGNUP_MAX_PER_IP_PER_HOUR 회를 넘으면 SignupRateLimited.

    메모리가 아니라 DB 를 쓰므로 프로세스가 여러 개여도 일관된다. 성공·실패 모두 시도로 센다.
    """
    now = now or timezone.now()
    limit = settings.SIGNUP_MAX_PER_IP_PER_HOUR
    with transaction.atomic():
        SignupAttempt.objects.filter(created_at__lt=now - KEEP).delete()  # 오래된 행 정리(별도 스케줄러 없음)
        recent = list(
            SignupAttempt.objects.filter(ip=ip, created_at__gte=now - WINDOW).order_by("created_at")
        )
        if len(recent) >= limit:
            frees_at = recent[len(recent) - limit].created_at + WINDOW
            raise SignupRateLimited(max(1, math.ceil((frees_at - now).total_seconds())))
        SignupAttempt.objects.create(ip=ip, created_at=now)
