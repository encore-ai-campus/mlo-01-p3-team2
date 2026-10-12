# scripts/ad_bridge/migrations/0002_impression_retry.py

원본: `scripts/ad_bridge/migrations/0002_impression_retry.py` · [소스 파일](../../../../../scripts/ad_bridge/migrations/0002_impression_retry.py)

[라우팅 목차](../../../ROUTING-README.md) · [구현 안내](../../../../../README.md)

## 역할

재전송 필드와 인덱스를 추가하고, 이전 버전의 미접수 기록을 동일 반응 ID로 다시 처리할 수 있게 보존하는 마이그레이션이다.

## 선언한 심볼

### recover_pending

참조·시그니처: `scripts/ad_bridge/migrations/0002_impression_retry.py::def recover_pending(apps, schema_editor)`

이전 버전의 미확인 기록도 같은 반응 ID로 다시 처리할 수 있게 만든다.

AST에서 확인한 호출 구문:

```text
Impression.objects.using
apps.get_model
rows.filter
rows.filter(delivery_state='SENDING').update
rows.filter(delivery_state='UNCONFIRMED').update
timezone.now
```

### Migration

참조: `scripts/ad_bridge/migrations/0002_impression_retry.py::Migration`

```text
class Migration(migrations.Migration):
```

재전송 관련 스키마 변경과 기존 기록 복구를 묶는 마이그레이션 선언이다. AST에서 AddField·AddIndex·RunPython 호출이 확인된다.

AST에서 확인한 호출 구문:

```text
migrations.AddField
migrations.AddIndex
migrations.RunPython
models.CharField
models.DateTimeField
models.Index
models.PositiveIntegerField
models.PositiveSmallIntegerField
models.UUIDField
```

## 모듈 의존성·검증 범위

AST에서 확인한 모듈 import:

```text
from django.db import migrations, models
from django.utils import timezone
```

심볼과 시그니처는 routing-doc-sync의 AST 분석 결과를 사용했다. 역할 설명은 위 모듈·심볼 설명과 구현 안내를 근거로 하며, 이름·호출 구문에서 해석한 부분은 추정으로 표시했다. 호출 구문 목록은 정적 문법 정보이며 실제 실행 순서·호출 횟수·런타임 호출 그래프를 보장하지 않는다.
