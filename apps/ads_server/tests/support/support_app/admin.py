from django.contrib import admin

from .models import OwnedThing

admin.site.register(OwnedThing)  # CSP nonce 가 admin 목록 화면에서 동작하는지 확인하는 테스트용
