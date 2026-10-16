from django.core.asgi import get_asgi_application

from config.env import load_env_for_web

load_env_for_web()  # 설정 모듈은 실제 환경변수 또는 prod — `.env` 의 값을 따르지 않는다(config/env.py)
application = get_asgi_application()
