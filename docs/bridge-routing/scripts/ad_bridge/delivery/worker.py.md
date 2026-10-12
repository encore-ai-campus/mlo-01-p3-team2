# scripts/ad_bridge/delivery/worker.py

원본: `scripts/ad_bridge/delivery/worker.py` · [소스 파일](../../../../../scripts/ad_bridge/delivery/worker.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../../README.md)

## 역할

기한이 된 미접수 기록이나 만료된 전송 임대를 저장소에서 확보하고 공통 전송 코드를 실행한다. 한 묶음의 최대 건수와 중단 신호를 확인한다.

AST에서 확인한 모듈 설명:

> 기한이 된 노출 기록을 확보하고 공통 전송 함수를 호출한다.

## 선언한 심볼

### dispatch_due_impressions

참조·시그니처: `scripts/ad_bridge/delivery/worker.py::def dispatch_due_impressions(*, client, store, limit: int=100, policy: RetryPolicy | None=None, now=utc_now, should_stop=lambda: False) -> dict[str, int]`

기한이 된 미접수 기록 또는 임대가 만료된 기록을 한 묶음 전송한다.

AST에서 확인한 호출 구문:

```text
RetryPolicy
ValueError
now
range
send_once
should_stop
store.claim_due_impression
type
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from .policy import RetryPolicy, utc_now
from .sender import send_once
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
