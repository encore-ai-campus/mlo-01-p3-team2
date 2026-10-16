"""기존 게임의 include('ad_bridge.django_urls') 경로를 유지한다."""

from .game.urls import app_name, urlpatterns

__all__ = ["app_name", "urlpatterns"]
