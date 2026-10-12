# scripts/ad_bridge/migrations/0001_initial.py

원본: `scripts/ad_bridge/migrations/0001_initial.py` · [소스 파일](../../../../../scripts/ad_bridge/migrations/0001_initial.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../README.md)

## 역할

브리지의 발급 결정과 노출 기록 저장소를 생성하는 최초 Django 마이그레이션이다.

## 선언한 심볼

### Migration

참조: `scripts/ad_bridge/migrations/0001_initial.py::Migration`

```text
class Migration(migrations.Migration):
```

최초 저장소 모델을 생성하는 마이그레이션 선언이다. AST에서 migrations.CreateModel 호출이 확인된다.

AST에서 확인한 호출 구문:

```text
migrations.CreateModel
models.BooleanField
models.CharField
models.DateTimeField
models.OneToOneField
models.TextField
models.UUIDField
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from django.db import migrations, models
import django.db.models.deletion
import uuid
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
