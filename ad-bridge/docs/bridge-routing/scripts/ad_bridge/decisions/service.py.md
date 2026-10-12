# scripts/ad_bridge/decisions/service.py

원본: `scripts/ad_bridge/decisions/service.py` · [원본 파일](../../../../../scripts/ad_bridge/decisions/service.py)

[통합 목차](../../../ROUTING-README.md)

## 역할

게임 측 광고 결정 발급 흐름을 조정한다. 주입받은 클라이언트로 결정을 요청하고 주입받은 저장소에 소유권 기록을 저장한 결과만 반환한다. 저수준 클라이언트를 직접 호출할 때와 달리 게임 DB의 발급 기록 저장까지 묶는 위치다. 자동 재시도·화면 표시·노출 보고는 이 함수의 책임이 아니다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

### create_decision

`scripts/ad_bridge/decisions/service.py::def create_decision(*, client, store, slot_id, subject_id) -> Decision`

클라이언트로 광고 결정을 요청한 뒤 저장소의 소유권 저장을 완료하고 같은 결정 객체를 반환한다. 광고 없음도 저장한다. 저장 실패를 정상 발급 결과로 숨기지 않으며 클라이언트와 저장소의 구체 구현은 호출자가 주입한다.

AST 호출 표기:

```text
client.create_decision
store.remember_decision
```

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import:

```text
from ..api.types import Decision
```

모듈 수준 호출 표기: 추출된 표기 없음.
