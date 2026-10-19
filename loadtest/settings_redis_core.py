"""실험용(운영 설정이 아니다): Redis 기본 채널 계층(RedisChannelLayer)으로 PubSub 계층과 비교한다(계획 M2)."""
from config.settings import *  # noqa: F401,F403

CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [CAMPUS_REDIS_URL]}}}  # noqa: F405
