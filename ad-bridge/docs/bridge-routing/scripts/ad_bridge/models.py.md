# ad-bridge/scripts/models.py

원본: `ad-bridge/scripts/models.py` · [소스 파일](../../../../scripts/models.py)

[라우팅 목차](../../ROUTING-README.md) · [구현 안내](../../../../scripts/README.md)

## 역할

개인 결정의 발급 소유권과 노출·전송 상태를 게임 DB에 저장하는 Django 모델 정의다. Django 모델 탐색을 위해 패키지 루트에 위치한다.

AST에서 확인한 모듈 설명:

> 개인 광고의 소유권과 최초 노출 요청을 게임 DB에 고정한다.

## 선언한 심볼

### IssuedDecision

참조: `ad-bridge/scripts/models.py::IssuedDecision`

```text
class IssuedDecision(models.Model):
```

개인 광고 결정의 내부 소유자 owner_id와 발급 당시 광고 가명 subject_id를 별도로 저장한다. owner_id는 게임 서버의 소유권 검사에만 사용한다. subject_id는 최초 노출과 재전송에 사용할 값이며 비밀 교체 시에도 덮어쓰지 않는다. 기존 기록은 0003 마이그레이션에서 owner_id가 None으로 남는다. 필드별 동작은 저장소·마이그레이션 검사로 확인하며 AST의 심볼 존재만으로 보장하지 않는다.

AST에서 확인한 호출 구문:

```text
models.BooleanField
models.DateTimeField
models.UUIDField
```

### Impression

참조: `ad-bridge/scripts/models.py::Impression`

```text
class Impression(models.Model):
```

결정당 최초 노출 ID·시각, 전송 상태·판정 결과·재전송 일정을 저장하는 모델이다. subject_id는 연결된 결정의 발급 당시 가명을 예약 시 복사한 값이다. 내부 소유자는 별도 중복 필드 없이 연결된 IssuedDecision.owner_id로 확인한다.

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

참조: `ad-bridge/scripts/models.py::Impression.Meta`

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
