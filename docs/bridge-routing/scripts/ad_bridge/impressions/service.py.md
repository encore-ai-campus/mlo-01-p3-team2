# scripts/ad_bridge/impressions/service.py

원본: `scripts/ad_bridge/impressions/service.py` · [소스 파일](../../../../../scripts/ad_bridge/impressions/service.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../README.md)

## 역할

게임의 최초 노출 알림을 저장소에 예약한 다음 공통 전송 코드로 전달한다. 중복 알림은 기존 기록을 반환하고, 미접수 기록의 재전송은 delivery 작업자가 맡는다.

AST에서 확인한 모듈 설명:

> 게임에서 받은 첫 노출 알림을 저장하고 전송한다.

## 선언한 심볼

### report_impression_once

참조·시그니처: `scripts/ad_bridge/impressions/service.py::def report_impression_once(*, client, store, decision_id, subject_id, occurred_at: str, policy: RetryPolicy | None=None, now=utc_now) -> ImpressionReport`

최초 알림만 즉시 전송한다. 중복 알림의 재전송은 별도 작업자가 담당한다.

AST에서 확인한 호출 구문:

```text
ImpressionReport
RetryPolicy
now
send_once
store.reserve_impression
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from ..delivery.policy import RetryPolicy, utc_now
from ..delivery.sender import ImpressionReport, send_once
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
