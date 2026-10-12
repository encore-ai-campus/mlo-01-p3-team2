# requirements.txt

원본: requirements.txt · [원본 파일](../../requirements.txt) · [통합 목차](ROUTING-README.md)

## 역할과 현재 상태

실행 환경과 의존성 관리 방침을 설명한다. 현재 모든 행이 주석이며 pip로 설치할 패키지 항목은 없다. Python 3.12를 실행 환경으로 설명하고, HTTP·JSON·환경변수·UUID·UTC 처리는 표준 라이브러리를 사용한다고 기록한다. Django는 이 브리지를 호출하는 게임 서버에서 관리하는 의존성이다.

이 파일에 설치 항목이 없다는 사실이 Django 연결부까지 외부 라이브러리 없이 실행된다는 뜻은 아니다. 새 실행 의존성이 생기면 이 파일과 [API 설정 문서](scripts/ad_bridge/api/config.py.md)의 환경 설명을 함께 검토한다.

## 선언과 검증 범위

Python 클래스·함수·시그니처가 있는 소스가 아니다. 텍스트 내용만 확인했으며 AST 검증 대상은 아니다. 테스트 의존성 파일은 이 문서화 범위에서 제외한다.
