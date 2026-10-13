from django.apps import AppConfig


class ConsoleConfig(AppConfig):
    name = "console"
    label = "console"  # 고정(설계 R3)

    def ready(self):
        from django.contrib import admin

        admin.site.index_template = "operator/admin_index.html"  # 관리자 첫 화면에 반응 처리 현황 카드와 운영 동작 링크(설계 D3-6: 관리자 화면은 admin 안)
