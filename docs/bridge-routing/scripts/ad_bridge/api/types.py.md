# scripts/ad_bridge/api/types.py

원본: `scripts/ad_bridge/api/types.py` · [원본 파일](../../../../../scripts/ad_bridge/api/types.py)

[통합 목차](../../../ROUTING-README.md)

## 역할

광고 소재, 광고 결정, 반응 접수 결과를 전달하는 프레임워크 독립 응답 타입을 선언한다. 세 클래스에는 frozen=True, slots=True인 dataclass 장식자가 적용된다. 반응 상태가 ACCEPTED여도 차감 금액이나 광고주 잔액을 나타내는 타입은 아니다. 이 파일에는 HTTP 호출·DB 저장·결과 GET 구현이 없다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

### Ad

`scripts/ad_bridge/api/types.py::Ad`

AST 추출 선언:

```text
class Ad
```

광고 소재 ID·제목·이미지 주소·연결 주소·클릭 주소를 전달하는 응답 값이다.

AST 장식자:

```text
dataclass(frozen=True, slots=True)
```

### Decision

`scripts/ad_bridge/api/types.py::Decision`

AST 추출 선언:

```text
class Decision
```

발급된 결정 정보, 광고 또는 광고 없음, 요청 ID를 전달하는 응답 값이다.

AST 장식자:

```text
dataclass(frozen=True, slots=True)
```

### Reaction

`scripts/ad_bridge/api/types.py::Reaction`

AST 추출 선언:

```text
class Reaction
```

반응 접수·판정 상태와 사유, 요청 ID를 전달하는 응답 값이다. 최종 차감 금액이나 잔액을 포함하는 정산 결과로 해석하지 않는다.

AST 장식자:

```text
dataclass(frozen=True, slots=True)
```

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import:

```text
from dataclasses import dataclass
```

모듈 수준 호출 표기: 추출된 표기 없음.
