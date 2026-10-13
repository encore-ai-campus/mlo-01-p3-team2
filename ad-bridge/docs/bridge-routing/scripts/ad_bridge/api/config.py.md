# ad-bridge/scripts/api/config.py

원본: `ad-bridge/scripts/api/config.py` · [원본 파일](../../../../../scripts/api/config.py)

[통합 목차](../../../ROUTING-README.md)

## 역할

광고 API 기본 주소, 서버 전용 매체 키, 초 단위 타임아웃과 광고 가명 생성 비밀을 검증하는 설정 모듈이다. 환경변수 ADS_API_BASE_URL·ADS_MEDIA_KEY·ADS_API_TIMEOUT·ADS_SUBJECT_SECRET은 모두 필수이며 기본 주소에는 /api/media/v1이 포함된다. 직접 설정 객체를 만들거나 별도 환경변수 매핑을 전달할 수 있다. .env 파일은 이 모듈에서 자동으로 읽지 않는다. 매체 키와 가명 생성 비밀은 설정 객체의 표현에 포함하지 않는다.

ADS_SUBJECT_SECRET은 비어 있지 않은 UTF-8 문자열이어야 하며 공백·제어 문자를 거부한다. 값을 자르거나 보정하지 않고 오류 메시지에도 비밀 원문을 넣지 않는다. 누락·잘못된 설정은 ValueError로 처리하며 원본 사용자 UUID로 대체하지 않는다.

역할 설명은 기존 연동 안내와 AST에서 추출한 문서 문자열·의존 및 호출 표기를 근거로 한다. 아래 선언은 AST가 직접 찾은 클래스·함수·메서드이며 dataclass 등이 실행 시 생성하는 메서드는 포함하지 않는다.

## 선언 목록

### AdsConfig

`ad-bridge/scripts/api/config.py::AdsConfig`

AST 추출 선언:

```text
class AdsConfig
```

광고 API 주소·매체 키·타임아웃·가명 생성 비밀을 묶는 불변 설정 객체다. 직접 생성과 환경변수 기반 생성을 지원한다. 직접 생성 시 subject_secret은 기본값이 없는 필수 키워드 인자이며 repr에서 제외한다. dataclass가 생성하는 생성자는 직접 선언한 심볼이 아니다.

AST 장식자:

```text
dataclass(frozen=True, slots=True)
```

AST 호출 표기:

```text
field
```

### AdsConfig.__post_init__

`ad-bridge/scripts/api/config.py::def AdsConfig.__post_init__(self) -> None`

생성된 설정의 주소·키·타임아웃·가명 생성 비밀을 검사한다. 주소와 타임아웃만 사용 형태로 정규화하며 잘못된 값은 ValueError로 알린다.

AST 호출 표기:

```text
ValueError
any
base_url.rstrip
bool
char.isspace
float
isinstance
math.isfinite
object.__setattr__
ord
self.base_url.strip
self.media_key.strip
self.subject_secret.encode
urlsplit
```

### AdsConfig.from_env

`ad-bridge/scripts/api/config.py::def AdsConfig.from_env(cls, environ: Mapping[str, str] | None=None) -> 'AdsConfig'`

호출 시점의 환경변수 또는 인자로 받은 매핑에서 필수 설정을 읽고 설정 객체를 반환하는 클래스 메서드다. 인자가 없으면 프로세스 환경을 사용한다.

AST 장식자:

```text
classmethod
```

AST 호출 표기:

```text
ValueError
cls
isinstance
value.strip
values.get
```

## 의존 및 호출 근거

아래 import와 각 선언의 호출 표기는 정적 AST 분석 결과다. 런타임의 실제 바인딩, 실행 여부, 실행 순서 또는 완전한 호출 그래프를 보장하지 않는다.

모듈 import:

```text
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit
import math
import os
```

모듈 수준 호출 표기: 추출된 표기 없음.
