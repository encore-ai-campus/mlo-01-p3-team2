# scripts/ad_bridge/decisions/store.py

원본: `scripts/ad_bridge/decisions/store.py` · [원본 파일](../../../../../scripts/ad_bridge/decisions/store.py)

[통합 목차](../../../ROUTING-README.md)

## 역할

개인 슬롯 결정의 소유자, 슬롯, 광고 유무와 결정 시각을 게임 DB의 발급 기록으로 보관한다. 광고가 없는 결정도 기록하며 기존 발급 기록의 소유권과 내용을 바꾸지 않도록 확인한다. 후속 노출 보고에서 사용자의 결정 소유권과 광고 유무를 판별하기 위한 저장소다. 공유 슬롯의 다중 사용자 흐름을 저장하는 구현으로 해석하면 안 된다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

### _uuid

`scripts/ad_bridge/decisions/store.py::def _uuid(value: str | UUID) -> UUID`

저장에 사용할 문자열 또는 UUID 입력을 UUID 값으로 정규화한다.

AST 호출 표기:

```text
UUID
ValueError
isinstance
str
```

### _utc_time

`scripts/ad_bridge/decisions/store.py::def _utc_time(value: str) -> datetime`

결정의 UTC 시각 문자열을 검사하고 DB 저장에 사용할 datetime 값으로 해석한다.

AST 호출 표기:

```text
ValueError
datetime.fromisoformat
isinstance
re.fullmatch
```

### remember_decision

`scripts/ad_bridge/decisions/store.py::def remember_decision(decision: Decision, subject_id: str | UUID) -> None`

개인 결정과 가명 사용자 UUID를 받아 발급 소유권 기록을 생성하거나 기존 기록과 일치하는지 확인한다. 광고 유무를 함께 저장하고 반환 값은 없다. 모델 import는 함수 내부에 있다.

선언 내부 import:

```text
from ..models import IssuedDecision
```

AST 호출 표기:

```text
IssuedDecision.objects.get_or_create
ValueError
_utc_time
_uuid
any
getattr
values.items
```

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import:

```text
from ..api.types import Decision
from datetime import datetime
from uuid import UUID
import re
```

모듈 수준 호출 표기: 추출된 표기 없음.
