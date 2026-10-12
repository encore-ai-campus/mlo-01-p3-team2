# scripts/ad_bridge/api/errors.py

원본: `scripts/ad_bridge/api/errors.py` · [원본 파일](../../../../../scripts/ad_bridge/api/errors.py)

[통합 목차](../../../ROUTING-README.md)

## 역할

광고 서버의 HTTP 실패, 연결 실패, 성공 응답의 형식 오류를 호출자가 구분할 수 있는 예외 계층이다. HTTP 상태·요청 ID·재시도 대기와 같은 진단 정보를 전달하며 원본 요청·인증 키를 예외에 보관하지 않는 구조다. 노출 PUT의 2xx 수신 후 본문 해석 실패는 접수 여부를 보존해야 한다. 2xx 접수는 최종 인정이나 차감 금액을 뜻하지 않는다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

### AdsError

`scripts/ad_bridge/api/errors.py::AdsError`

AST 추출 선언:

```text
class AdsError(Exception)
```

광고 통신 실패의 공통 부모 예외다. 원본 요청과 인증 키는 보관하지 않는다.

### AdsHTTPError

`scripts/ad_bridge/api/errors.py::AdsHTTPError`

AST 추출 선언:

```text
class AdsHTTPError(AdsError)
```

광고 서버에서 HTTP 실패 응답을 받았을 때 사용하는 예외다. 상태·오류 코드·요청 ID·재시도 대기 초를 전달한다.

### AdsHTTPError.__init__

`scripts/ad_bridge/api/errors.py::def AdsHTTPError.__init__(self, status: int, *, code: str | None=None, request_id: str | None=None, retry_after: int | None=None) -> None`

필수 HTTP 상태와 선택적인 오류 코드·요청 ID·Retry-After 대기 초를 받아 HTTP 예외를 구성한다.

AST 호출 표기:

```text
super
super().__init__
```

### AdsTransportError

`scripts/ad_bridge/api/errors.py::AdsTransportError`

AST 추출 선언:

```text
class AdsTransportError(AdsError)
```

타임아웃·연결 실패·응답 수신 중단을 구분하는 예외다. 이 예외만으로 광고 서버가 요청을 처리하지 않았다고 단정할 수 없다.

### AdsResponseError

`scripts/ad_bridge/api/errors.py::AdsResponseError`

AST 추출 선언:

```text
class AdsResponseError(AdsError)
```

예상 밖 성공 상태나 잘못된 JSON·필수 응답 필드 등 응답 검증 오류를 구분한다. 반응 PUT은 2xx를 받았는지 함께 보존할 수 있다.

### AdsResponseError.__init__

`scripts/ad_bridge/api/errors.py::def AdsResponseError.__init__(self, message: str, *, request_id: str | None=None, acknowledged: bool=False) -> None`

오류 메시지, 선택적 요청 ID와 접수 확인 여부로 응답 예외를 구성한다. acknowledged의 기본값은 False이며 True이면 본문 오류만으로 미접수 재전송을 결정하면 안 된다.

AST 호출 표기:

```text
super
super().__init__
```

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import: 추출된 표기 없음.

모듈 수준 호출 표기: 추출된 표기 없음.
