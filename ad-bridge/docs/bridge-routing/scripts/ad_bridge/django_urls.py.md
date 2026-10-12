# scripts/ad_bridge/django_urls.py

원본: `scripts/ad_bridge/django_urls.py` · [소스 파일](../../../../scripts/ad_bridge/django_urls.py)

[통합 목차](../../ROUTING-README.md)

## 역할

기존 게임의 아래 URL 연결 사용법을 유지하는 호환 파일이다. 실제 경로 정의는 game.urls에 있다. 아래는 호출 예시이며 이 파일의 함수 선언이 아니다.

```text
include("ad_bridge.django_urls")
```

AST import는 `from .game.urls import app_name, urlpatterns`다. 이 파일에서 app_name·urlpatterns를 가져와 기존 include에서 사용할 수 있게 한다. 새로운 뷰나 HTTP 경로를 이 파일에 중복 정의하지 않는다.

## 직접 선언

직접 선언한 클래스·함수·메서드는 없다. 가져온 app_name·urlpatterns는 이 파일에서 정의한 함수가 아니다.

## 의존성과 탐색

- [게임 URL 정의](game/urls.py.md): 가져오는 app_name·urlpatterns의 원본 모듈.
- [게임 뷰](game/views.py.md): 결정 요청·노출 알림을 처리하는 함수.

AST 호출 구문 목록은 비어 있다. 이 사실은 import나 Django의 URL 해석이 실행되지 않는다는 뜻은 아니다.
