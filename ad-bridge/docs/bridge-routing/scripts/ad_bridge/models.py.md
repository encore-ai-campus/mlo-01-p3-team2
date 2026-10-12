# scripts/ad_bridge/models.py

원본: `scripts/ad_bridge/models.py` · [소스 파일](../../../../scripts/ad_bridge/models.py)

[라우팅 목차](../../ROUTING-README.md) · [구현 안내](../../../../README.md)

## 역할

개인 결정의 발급 소유권과 노출·전송 상태를 게임 DB에 저장하는 Django 모델 정의다. Django 모델 탐색을 위해 패키지 루트에 위치한다.

AST에서 확인한 모듈 설명:

> 개인 광고의 소유권과 최초 노출 요청을 게임 DB에 고정한다.

## 선언한 심볼

### IssuedDecision

참조: `scripts/ad_bridge/models.py::IssuedDecision`

```text
class IssuedDecision(models.Model):
```

개인 광고 결정의 소유자·슬롯·광고 유무를 저장하는 모델이다. 세부 필드 명세는 이 AST 기반 탐색 문서의 범위에 포함하지 않는다.

AST에서 확인한 호출 구문:

```text
models.BooleanField
models.DateTimeField
models.UUIDField
```

### Impression

참조: `scripts/ad_bridge/models.py::Impression`

```text
class Impression(models.Model):
```

결정당 최초 노출 ID·시각, 전송 상태·판정 결과·재전송 일정을 저장하는 모델이다. 세부 필드 명세는 이 AST 기반 탐색 문서의 범위에 포함하지 않는다.

AST에서 확인한 호출 구문:

```text
models.CharField
models.DateTimeField
models.OneToOneField
models.PositiveIntegerField
models.PositiveSmallIntegerField
models.TextField
models.UUIDField
```

### Impression.Meta

참조: `scripts/ad_bridge/models.py::Impression.Meta`

```text
class Meta:
```

Impression 모델의 메타 설정 클래스다. AST에서 models.Index 호출이 확인된다. 인덱스의 세부 필드 구성은 이 문서에서 추출하지 않는다.

AST에서 확인한 호출 구문:

```text
models.Index
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from django.db import models
import uuid
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
