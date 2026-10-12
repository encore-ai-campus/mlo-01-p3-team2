# scripts/ad_bridge/delivery/sender.py

원본: `scripts/ad_bridge/delivery/sender.py` · [소스 파일](../../../../../scripts/ad_bridge/delivery/sender.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../README.md)

## 역할

최초 전송과 재전송이 공유하는 HTTP 호출 및 결과 저장을 담당한다. 커밋된 노출을 한 번 전송하고 접수 확인·영구 오류·재시도 대상 오류를 구분한다.

AST에서 확인한 모듈 설명:

> 최초 전송과 재전송에 동일한 전송·결과 저장 규칙을 적용한다.

## 선언한 심볼

### ImpressionReport

참조: `scripts/ad_bridge/delivery/sender.py::ImpressionReport`

```text
@dataclass(frozen=True, slots=True)
class ImpressionReport:
```

저장된 노출 기록과 호출자에게 반환할 안전한 오류 메타데이터를 묶는 결과 값이다.

### send_once

참조·시그니처: `scripts/ad_bridge/delivery/sender.py::def send_once(*, client, store, record: StoredImpression, policy: RetryPolicy, now) -> ImpressionReport`

커밋된 임대 하나를 전송한다. 오류 원문 대신 정해진 진단 코드만 저장한다.

AST에서 확인한 호출 구문:

```text
ImpressionReport
client.report_impression
now
policy.delay_for
store.finish_impression
timedelta
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from ..api.errors import AdsHTTPError, AdsResponseError, AdsTransportError
from ..impressions.store import StoredImpression
from .policy import RetryPolicy
from dataclasses import dataclass
from datetime import timedelta
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
