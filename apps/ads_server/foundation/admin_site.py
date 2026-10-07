"""관리자 사이트. 관리자 본인의 비밀번호 변경도 감사 로그에 남긴다(위협 T23).

`UserAdmin` 은 다른 사용자의 비밀번호 초기화만 기록한다. 본인 변경은 AdminSite 의 별도 뷰라 여기서 잡는다.
"""
from django.contrib import admin

from .audit import record_audit


class AuditedAdminSite(admin.AdminSite):
    def password_change(self, request, extra_context=None):
        response = super().password_change(request, extra_context)
        if request.method == "POST" and response.status_code == 302:  # 성공(리다이렉트)일 때만
            record_audit(request, "account.password_changed", target=request.user, actor=request.user)
        return response
