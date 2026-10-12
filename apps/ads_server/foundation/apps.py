from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class FoundationConfig(AppConfig):
    name = "foundation"
    label = "foundation"  # 고정: 폴더·패키지를 옮겨도 마이그레이션과 FK 가 깨지지 않게(설계 R3)

    def ready(self):
        from . import checks, signals  # noqa: F401  (배포 점검 · 인증 사건 → 감사 로그)


class AuditedAdminConfig(AdminConfig):
    """`django.contrib.admin` 대신 등록해 기본 관리자 사이트를 `AuditedAdminSite` 로 바꾼다."""

    default_site = "foundation.admin_site.AuditedAdminSite"
