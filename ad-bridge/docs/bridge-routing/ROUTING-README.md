# ad-bridge 코드 탐색 목차

이 문서는 ad-bridge 안의 구현·설정 파일을 찾기 위한 진입점이다. 원본의 저장소 상대경로를 그대로 복제하고 파일명 뒤에 .md를 붙여 파일별 문서를 연결한다.

## 범위와 대응 규칙

- 대상: scripts/ad_bridge 아래 Python 30개·JavaScript 2개, Git 제외 설정 .gitignore, 총 **33개 현재 원본 파일**.
- 현재 원본 대응 문서는 **33개**다. 삭제된 requirements.txt의 이력 문서 1개와 이 목차를 포함한 전체 문서는 **35개**다. 이력 문서는 현재 원본과의 1:1 목록에서 제외한다.
- 패키지 초기화 파일과 마이그레이션, 아직 구현하지 않은 자리도 실제 원본이 있으므로 각각 문서화한다.
- 제외: scripts/test, integration_tests, requirements-test.txt, 가상환경, 캐시, Git 내부 파일, 작업 지침, 기존 설명 문서. 광고 서버와 게임 클라이언트 프로젝트는 조사·문서화 대상이 아니다.
- 파일별 문서에 원본 경로, 역할, 직접 선언한 클래스·함수·시그니처, 관련 의존 관계를 기록한다. 가져온 이름·상속받은 메서드는 직접 선언한 것으로 세지 않는다.

```text
원본: scripts/ad_bridge/api/client.py
문서: docs/bridge-routing/scripts/ad_bridge/api/client.py.md

원본: scripts/ad_bridge/static/ad_bridge/display.js
문서: docs/bridge-routing/scripts/ad_bridge/static/ad_bridge/display.js.md

원본: .gitignore
문서: docs/bridge-routing/.gitignore.md
```

## 목적별 시작 위치

| 확인할 내용 | 먼저 읽을 파일별 문서 |
|---|---|
| 가상환경·캐시의 Git 제외 규칙 | [Git 제외 설정](.gitignore.md) |
| 외부에서 사용하는 클래스·예외 | [공개 import](scripts/ad_bridge/__init__.py.md) |
| 광고 서버 주소·인증 키·타임아웃·가명 생성 비밀 | [API 설정](scripts/ad_bridge/api/config.py.md) |
| 광고 결정 POST·노출 PUT·판정 GET 형식 | [HTTP 클라이언트](scripts/ad_bridge/api/client.py.md) |
| 광고 요청 후 발급 소유권 저장 | [결정 서비스](scripts/ad_bridge/decisions/service.py.md) |
| 첫 노출·중복 알림 처리 | [노출 서비스](scripts/ad_bridge/impressions/service.py.md) |
| 시도 횟수·재전송 일정·전송 임대 | [노출 저장소](scripts/ad_bridge/impressions/store.py.md) |
| 최초 전송과 재전송의 공통 처리 | [전송 함수](scripts/ad_bridge/delivery/sender.py.md) |
| 재시도 대기 규칙과 처리 대상 선택 | [대기 정책](scripts/ad_bridge/delivery/policy.py.md), [작업자](scripts/ad_bridge/delivery/worker.py.md) |
| 로그인·CSRF·광고 전용 가명 생성·게임 HTTP 응답 | [게임 연결](scripts/ad_bridge/game/views.py.md) |
| 재전송 명령 실행 | [관리 명령](scripts/ad_bridge/management/commands/dispatch_ad_reactions.py.md) |
| DB 모델과 버전 변경 | [모델](scripts/ad_bridge/models.py.md), [최초 마이그레이션](scripts/ad_bridge/migrations/0001_initial.py.md), [재전송 마이그레이션](scripts/ad_bridge/migrations/0002_impression_retry.py.md) |
| 판정 조회·저장 | [결과 서비스](scripts/ad_bridge/results/service.py.md) |
| Canvas 광고 표시·최초 관측 | [광고 표시](scripts/ad_bridge/static/ad_bridge/display.js.md), [노출 감지](scripts/ad_bridge/static/ad_bridge/impression.js.md) |

광고 결정은 게임 연결 → 결정 서비스 → API 요청·발급 저장의 순서로 처리한다. 첫 노출은 노출 서비스에서 기록을 예약하고 공통 전송 함수에 넘긴다. 재전송 작업자도 같은 전송 함수를 사용한다. DB 저장·임대·일정 갱신은 노출 저장소에서 처리한다. 이 설명은 현재 구현을 찾기 위한 안내이며, AST의 호출 이름만으로 실행 시의 모든 호출 관계를 확정하는 것은 아니다.

## 원본과 문서 1:1 목록

| 원본 파일 | 대응 문서 | 역할 |
|---|---|---|
| [.gitignore](../../.gitignore) | [파일 문서](.gitignore.md) | 로컬 가상환경·Python 캐시의 Git 제외 규칙 |
| [scripts/ad_bridge/__init__.py](../../scripts/ad_bridge/__init__.py) | [파일 문서](scripts/ad_bridge/__init__.py.md) | 게임 서버에서 사용하는 광고 서버 통신 모듈. |
| [scripts/ad_bridge/api/__init__.py](../../scripts/ad_bridge/api/__init__.py) | [파일 문서](scripts/ad_bridge/api/__init__.py.md) | 광고 서버의 HTTP 계약과 연결 설정. |
| [scripts/ad_bridge/api/client.py](../../scripts/ad_bridge/api/client.py) | [파일 문서](scripts/ad_bridge/api/client.py.md) | C1 v1.1 결정 요청과 노출 보고. 한 번만 전송하며 재전송·차감은 수행하지 않는다. |
| [scripts/ad_bridge/api/config.py](../../scripts/ad_bridge/api/config.py) | [파일 문서](scripts/ad_bridge/api/config.py.md) | 광고 API 주소·인증 키·타임아웃 설정과 입력 검증. |
| [scripts/ad_bridge/api/errors.py](../../scripts/ad_bridge/api/errors.py) | [파일 문서](scripts/ad_bridge/api/errors.py.md) | 호출자가 설정·HTTP·연결·응답 오류를 구분할 수 있는 예외. |
| [scripts/ad_bridge/api/types.py](../../scripts/ad_bridge/api/types.py) | [파일 문서](scripts/ad_bridge/api/types.py.md) | 게임 프레임워크에 의존하지 않는 광고 응답 값. |
| [scripts/ad_bridge/apps.py](../../scripts/ad_bridge/apps.py) | [파일 문서](scripts/ad_bridge/apps.py.md) | 게임 DB에 광고 발급·노출 기록을 보관하는 선택적 Django 앱. |
| [scripts/ad_bridge/decisions/__init__.py](../../scripts/ad_bridge/decisions/__init__.py) | [파일 문서](scripts/ad_bridge/decisions/__init__.py.md) | 광고 요청과 발급 소유권 기록. |
| [scripts/ad_bridge/decisions/service.py](../../scripts/ad_bridge/decisions/service.py) | [파일 문서](scripts/ad_bridge/decisions/service.py.md) | 광고 결정을 요청하고 소유권 저장이 끝난 결과만 호출자에게 반환한다. |
| [scripts/ad_bridge/decisions/store.py](../../scripts/ad_bridge/decisions/store.py) | [파일 문서](scripts/ad_bridge/decisions/store.py.md) | 개인 광고 결정의 소유자와 광고 유무를 저장한다. |
| [scripts/ad_bridge/delivery/__init__.py](../../scripts/ad_bridge/delivery/__init__.py) | [파일 문서](scripts/ad_bridge/delivery/__init__.py.md) | 저장된 노출의 전송과 재전송. |
| [scripts/ad_bridge/delivery/policy.py](../../scripts/ad_bridge/delivery/policy.py) | [파일 문서](scripts/ad_bridge/delivery/policy.py.md) | 노출 재전송의 대기 시간과 전송 임대 시간을 정한다. |
| [scripts/ad_bridge/delivery/sender.py](../../scripts/ad_bridge/delivery/sender.py) | [파일 문서](scripts/ad_bridge/delivery/sender.py.md) | 최초 전송과 재전송에 동일한 전송·결과 저장 규칙을 적용한다. |
| [scripts/ad_bridge/delivery/worker.py](../../scripts/ad_bridge/delivery/worker.py) | [파일 문서](scripts/ad_bridge/delivery/worker.py.md) | 기한이 된 노출 기록을 확보하고 공통 전송 함수를 호출한다. |
| [scripts/ad_bridge/django_urls.py](../../scripts/ad_bridge/django_urls.py) | [파일 문서](scripts/ad_bridge/django_urls.py.md) | 기존 게임의 include('ad_bridge.django_urls') 경로를 유지한다. |
| [scripts/ad_bridge/game/__init__.py](../../scripts/ad_bridge/game/__init__.py) | [파일 문서](scripts/ad_bridge/game/__init__.py.md) | 게임 서버의 Django 요청 연결. |
| [scripts/ad_bridge/game/urls.py](../../scripts/ad_bridge/game/urls.py) | [파일 문서](scripts/ad_bridge/game/urls.py.md) | 게임 서버에 제공하는 광고 요청·노출 알림 경로. |
| [scripts/ad_bridge/game/views.py](../../scripts/ad_bridge/game/views.py) | [파일 문서](scripts/ad_bridge/game/views.py.md) | feat;#17 게임의 로그인 프로필과 기존 광고 요청 모듈을 연결한다. |
| [scripts/ad_bridge/impressions/__init__.py](../../scripts/ad_bridge/impressions/__init__.py) | [파일 문서](scripts/ad_bridge/impressions/__init__.py.md) | 개인 슬롯의 노출 접수와 저장. |
| [scripts/ad_bridge/impressions/service.py](../../scripts/ad_bridge/impressions/service.py) | [파일 문서](scripts/ad_bridge/impressions/service.py.md) | 게임에서 받은 첫 노출 알림을 저장하고 전송한다. |
| [scripts/ad_bridge/impressions/store.py](../../scripts/ad_bridge/impressions/store.py) | [파일 문서](scripts/ad_bridge/impressions/store.py.md) | 노출 전송 전에 소유권·반응 ID·요청 시각을 영속 저장한다. |
| [scripts/ad_bridge/management/__init__.py](../../scripts/ad_bridge/management/__init__.py) | [파일 문서](scripts/ad_bridge/management/__init__.py.md) | 게임 서버에서 실행하는 광고 연동 관리 명령. |
| [scripts/ad_bridge/management/commands/__init__.py](../../scripts/ad_bridge/management/commands/__init__.py) | [파일 문서](scripts/ad_bridge/management/commands/__init__.py.md) | Django가 광고 관리 명령을 찾는 패키지. |
| [scripts/ad_bridge/management/commands/dispatch_ad_reactions.py](../../scripts/ad_bridge/management/commands/dispatch_ad_reactions.py) | [파일 문서](scripts/ad_bridge/management/commands/dispatch_ad_reactions.py.md) | 미접수 노출을 처리할 시각에 재전송하는 게임 서버 명령. |
| [scripts/ad_bridge/migrations/0001_initial.py](../../scripts/ad_bridge/migrations/0001_initial.py) | [파일 문서](scripts/ad_bridge/migrations/0001_initial.py.md) | 광고 발급·노출 기록의 최초 스키마 |
| [scripts/ad_bridge/migrations/0002_impression_retry.py](../../scripts/ad_bridge/migrations/0002_impression_retry.py) | [파일 문서](scripts/ad_bridge/migrations/0002_impression_retry.py.md) | 재전송 필드·인덱스 추가와 기존 미접수 기록 복구 |
| [scripts/ad_bridge/migrations/__init__.py](../../scripts/ad_bridge/migrations/__init__.py) | [파일 문서](scripts/ad_bridge/migrations/__init__.py.md) | 실제 게임에서 migrate로 적용하는 브리지 저장소 스키마. |
| [scripts/ad_bridge/models.py](../../scripts/ad_bridge/models.py) | [파일 문서](scripts/ad_bridge/models.py.md) | 개인 광고의 소유권과 최초 노출 요청을 게임 DB에 고정한다. |
| [scripts/ad_bridge/results/__init__.py](../../scripts/ad_bridge/results/__init__.py) | [파일 문서](scripts/ad_bridge/results/__init__.py.md) | 접수된 개인 노출의 판정 결과 조회. |
| [scripts/ad_bridge/results/service.py](../../scripts/ad_bridge/results/service.py) | [파일 문서](scripts/ad_bridge/results/service.py.md) | 광고 서버의 반응 GET 결과를 조회하고 판정·거절 사유를 갱신한다. |
| [scripts/ad_bridge/static/ad_bridge/display.js](../../scripts/ad_bridge/static/ad_bridge/display.js) | [파일 문서](scripts/ad_bridge/static/ad_bridge/display.js.md) | Canvas 광고 이미지·클릭 주소 적용 |
| [scripts/ad_bridge/static/ad_bridge/impression.js](../../scripts/ad_bridge/static/ad_bridge/impression.js) | [파일 문서](scripts/ad_bridge/static/ad_bridge/impression.js.md) | 게임의 노출 조건을 받아 결정별 최초 관측 |

## 분석 근거와 한계

Python 파일·선언·시그니처는 routing-doc-sync 스킬의 AST 분석 결과로 추출했다. 역할 설명은 모듈·심볼 docstring, import·호출 구문과 기존 구현 안내를 근거로 작성했다. 자동 분석은 역할의 의미나 런타임 동작 전체를 증명하지 않는다. 동적으로 만들어진 이름, dataclass가 생성한 메서드와 상속받은 선언은 자동 분석 대상이 아니다.

JavaScript 두 파일은 광고 표시와 최초 노출 관측 클래스를 구현한다. .gitignore는 Git 제외 설정이다. JS·Git 설정은 Python AST 검증 대상이 아니며 JS는 Node와 실제 게임 화면으로 검증했다. requirements.txt는 현재 삭제되어 [이력 문서](requirements.txt.md)로만 남긴다. results/service.py는 접수 완료 노출의 1회 GET·판정 저장을 구현한다. 광고 표시·노출 감지와 판정 경로를 로컬 테스트 게임에서 연결했다.

2026-10-11 결과 조회 기능 반영: 원본 33개와 대응 문서 33개 구조를 유지한다. GET 클라이언트·결과 서비스·노출 저장소 문서를 새 AST 선언에 맞춰 갱신했다. 정적 참조 대조는 런타임 동작 전체를 증명하지 않는다.

## 갱신 절차

1. 구현 파일을 추가·이동·삭제하면 같은 상대경로의 파일별 문서와 위 목록을 함께 갱신한다.
2. Python 선언·시그니처는 routing-doc-sync 분석기로 다시 추출한다. 소스 파일의 이름만 맞춰 놓고 함수까지 검증했다고 판단하지 않는다.
3. 문서 편집이 끝난 뒤 라우팅 목차와 모든 파일별 문서를 분석기에 전달해 재검사한다. mismatch·ambiguous·unverifiable·diagnostics를 따로 확인한다.
4. 현재 원본 33개와 대응 문서 33개의 대응(이력 문서 제외), 문서 내부 상대 링크, 테스트 문서의 유입 여부를 별도로 확인한다. 원본 파일이 늘거나 줄면 이 숫자도 갱신한다.
5. 분석기의 needs_review·not_verified는 역할·지원 밖 표기에 대한 검토 상태다. 참조 일치만으로 전체 실행 동작을 검증했다고 해석하지 않는다.

설치·실행·계약 요약은 [기존 구현 안내](../../README.md)에서 확인한다. 이 라우팅 문서는 테스트 코드를 다루지 않는다.

2026-10-12: game/views.py·game/urls.py와 두 공용 JS 문서를 실제 구현에 맞춰 갱신했다. 테스트 게임에서 이미지 표시·노출 보고·ACCEPTED 판정·포인트 원장을 확인했다. GitHub 게임 배포는 수행하지 않았다.

2026-10-12 이슈 #34 부분 반영: API 설정의 ADS_SUBJECT_SECRET 필수 검증과 게임 연결의 HMAC-SHA256 광고 가명 생성만 구현했다. 관련 config.py·views.py 문서를 AST 결과에 맞춰 갱신했다. 두 파일의 원본 참조는 현재 Git 저장소 기준 ad-bridge/scripts 경로로 표기한다. 401 수동 복구와 판정 응답 비공개 처리는 이번 변경에 포함하지 않는다.
