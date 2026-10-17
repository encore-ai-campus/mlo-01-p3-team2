"""부하 시험용 계정 N개와 로그인 세션을 만든다. 실제 로그인과 같은 경로(start_login)를 쓴다.

사용(백엔드 컨테이너 안): python /load/seed.py 100 [--questions]  →  /data/sessions.json (세션 키 목록)
--questions: 교실 학습용 예제 문제은행도 넣는다(부하 시험 DB 만. 사람이 쓰는 개발 서버 DB 에는 넣지 않는다)
"""
import json
import os
import sys
from importlib import import_module

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model  # noqa: E402

from accounts.avatars import DEFAULT_AVATAR  # noqa: E402
from accounts.models import Profile  # noqa: E402
from accounts.session_policy import start_login  # noqa: E402
from django.core.management import call_command  # noqa: E402

if "--questions" in sys.argv:
    call_command("seed_learning_questions", verbosity=0)  # 실사용 모방의 교실 학습(예제 문제은행, 이미 있으면 그대로)

count = int(next((arg for arg in sys.argv[1:] if arg.isdigit()), 100))
store = import_module(settings.SESSION_ENGINE).SessionStore
keys = []
for i in range(count):
    user, created = get_user_model().objects.get_or_create(username=f"load{i:03d}")
    if created:
        user.set_password(f"load-pass-{i:03d}-x")
        user.save()
    Profile.objects.update_or_create(user=user, defaults={
        "nickname": f"부하{i:03d}", "avatar": DEFAULT_AVATAR, "setup_complete": True, "guide_completed": True,
    })
    session = store()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    start_login(session, user)  # 정책 시각·단일 로그인 소유·플랫폼 세션·저장(실제 로그인과 같다)
    keys.append(session.session_key)

with open("/data/sessions.json", "w", encoding="utf-8") as f:
    json.dump(keys, f)
print(f"seeded {len(keys)} sessions")
