# scripts/ad_bridge/__init__.py

원본: `scripts/ad_bridge/__init__.py` · [원본 파일](../../../../scripts/ad_bridge/__init__.py)

[통합 목차](../../ROUTING-README.md)

## 역할

호출자가 패키지 루트에서 광고 통신 클래스·설정·예외·응답 타입을 가져올 수 있게 재노출한다. 기능별 폴더로 이동한 뒤에도 기존 공개 import 경로를 유지하는 파일이다. 직접 HTTP 요청이나 게임 DB 저장을 수행하는 진입 함수는 선언하지 않는다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

직접 선언한 클래스·함수·메서드 없음.

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import:

```text
from .api.client import AdsClient
from .api.config import AdsConfig
from .api.errors import AdsError, AdsHTTPError, AdsResponseError, AdsTransportError
from .api.types import Ad, Decision, Reaction
```

모듈 수준 호출 표기: 추출된 표기 없음.
