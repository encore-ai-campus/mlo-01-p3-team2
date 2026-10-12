# scripts/ad_bridge/apps.py

원본: `scripts/ad_bridge/apps.py` · [소스 파일](../../../../scripts/ad_bridge/apps.py)

[통합 목차](../../ROUTING-README.md)

## 역할

광고 발급·노출 기록을 게임 DB에 보관하는 Django 앱 설정이다. 게임의 기존 INSTALLED_APPS에 ad_bridge.apps.AdBridgeConfig라는 설정 문자열을 등록할 때 진입하는 파일이다. 모듈 docstring은 이 앱이 선택적 Django 앱임을 설명한다.

이 파일은 앱 등록 설정을 제공한다. 테이블 정의·마이그레이션·광고 HTTP 전송을 직접 담당하지 않는다.

## 직접 선언

`scripts/ad_bridge/apps.py::AdBridgeConfig`

```text
class AdBridgeConfig(AppConfig)
```

Django의 AppConfig를 상속하는 앱 설정 클래스다. AST에 직접 정의된 메서드는 없다. Django에서 상속받는 메서드를 이 파일의 직접 선언으로 계산하지 않는다.

## 의존성과 탐색

- 외부 의존성: AST import `from django.apps import AppConfig`.
- [모델](models.py.md): 발급·노출 기록의 테이블 정의.
- [게임 URL 호환 파일](django_urls.py.md): 기존 게임에 URL을 연결하는 별도 진입점.

모듈과 클래스의 AST 호출 구문 목록은 비어 있다. 상속 프레임워크가 실행하는 동작은 이 호출 목록만으로 판정하지 않는다.
