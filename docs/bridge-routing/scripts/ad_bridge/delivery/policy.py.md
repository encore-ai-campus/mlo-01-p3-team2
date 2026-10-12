# scripts/ad_bridge/delivery/policy.py

원본: `scripts/ad_bridge/delivery/policy.py` · [소스 파일](../../../../../scripts/ad_bridge/delivery/policy.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../../README.md)

## 역할

재시도 지수 대기와 전송 임대 시간을 검증·계산한다. Retry-After의 최소 대기를 로컬 지수 대기 상한보다 우선한다.

AST에서 확인한 모듈 설명:

> 노출 재전송의 대기 시간과 전송 임대 시간을 정한다.

## 선언한 심볼

### utc_now

참조·시그니처: `scripts/ad_bridge/delivery/policy.py::def utc_now() -> datetime`

UTC 현재 시각을 공급한다. AST의 datetime.now 호출과 함수 이름을 근거로 한 역할 설명이다.

AST에서 확인한 호출 구문:

```text
datetime.now
```

### RetryPolicy

참조: `scripts/ad_bridge/delivery/policy.py::RetryPolicy`

```text
@dataclass(frozen=True, slots=True)
class RetryPolicy:
```

지수 대기·Retry-After·임대 시간 정책 값과 계산을 묶는다. 기존 구현 안내에 설명된 기본 대기는 1초, 최대 지수 대기는 300초다.

### RetryPolicy.__post_init__

참조·시그니처: `scripts/ad_bridge/delivery/policy.py::def RetryPolicy.__post_init__(self)`

추정: dataclass 초기화 시 정책 값의 유효성을 검사하는 내부 메서드다. AST에서 math.isfinite·isinstance·ValueError 호출이 확인된다.

AST에서 확인한 호출 구문:

```text
ValueError
isinstance
math.isfinite
```

### RetryPolicy.delay_for

참조·시그니처: `scripts/ad_bridge/delivery/policy.py::def RetryPolicy.delay_for(self, attempts: int, retry_after: int | None=None) -> float`

전송 예약 횟수에 따른 지수 대기를 계산하고 Retry-After의 최소 대기를 지킨다. 기존 구현 안내와 AST의 max·min 호출을 근거로 한다.

AST에서 확인한 호출 구문:

```text
ValueError
max
min
type
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from dataclasses import dataclass
from datetime import datetime, timezone
import math
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
