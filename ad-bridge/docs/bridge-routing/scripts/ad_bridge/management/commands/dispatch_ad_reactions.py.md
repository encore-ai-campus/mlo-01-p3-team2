# ad-bridge/scripts/management/commands/dispatch_ad_reactions.py

원본: `ad-bridge/scripts/management/commands/dispatch_ad_reactions.py` · [소스 파일](../../../../../../scripts/management/commands/dispatch_ad_reactions.py)

[통합 목차](../../../../ROUTING-README.md)

## 역할

저장된 미접수 노출의 자동 재전송과 지정한 401 차단 노출의 수동 복구를 제공하는 Django 관리 명령이다. API 설정을 먼저 검증하고 클라이언트·재시도 정책을 준비한다. 기본 모드는 delivery.worker에 위임하고, --recover-401 모드는 저장소의 복구 임대 확보 함수와 기존 send_once를 호출한다. 기록을 직접 ORM으로 조회하거나 새 반응을 만드는 모듈은 아니다.

기존 연동 안내 기준 기본 반복은 배치 최대 100건, 배치 사이 1초 대기다. `--once`는 지금 처리할 한 배치만 실행하며 미래 재시도 시각까지 기다리지 않는다. 재시도 간격·불변 반응 ID·멱등성·임대 규칙은 정책·전송·저장소의 책임이다. 이 명령은 결과 GET이나 실제 차감 조회를 수행하지 않는다.

--recover-401 REACTION_UUID는 지정한 기록만 한 번 처리하고 종료한다. --once가 없어도 반복하지 않는다. 접수 확인인 ACKNOWLEDGED는 최종 인정·과금 판정과 별개로 성공 종료한다. 대상 제외·접수 미확인·복구 DB 작업 또는 입력 검증 오류는 CommandError로 실패 종료한다. 일반 브라우저에서 실행할 경로는 추가하지 않는다.

## 직접 선언

### 관리 명령 클래스

`ad-bridge/scripts/management/commands/dispatch_ad_reactions.py::Command`

```text
class Command(BaseCommand)
```

Django의 BaseCommand를 상속한다. 아래에 열거한 메서드와 중첩 함수가 AST에 직접 선언돼 있다. BaseCommand의 상속 메서드는 이 파일의 직접 선언으로 추가하지 않는다.

### 실행 인자

`ad-bridge/scripts/management/commands/dispatch_ad_reactions.py::def Command.add_arguments(self, parser)`

`--once`, `--batch-size`, `--poll-interval`, `--recover-401 REACTION_UUID` 실행 옵션을 등록한다. 복구 옵션은 한 반응 ID만 받으며 배치 크기·대기 간격으로 반복하지 않는다. 기존 배치·대기 옵션의 입력 검증은 유지한다. 다음은 AST 호출 구문이며 외부 런타임의 함수 선언·시그니처를 검증한 결과가 아니다.

```text
parser.add_argument
```

### 실행 흐름

`ad-bridge/scripts/management/commands/dispatch_ad_reactions.py::def Command.handle(self, *args, **options)`

복구 UUID를 원문 없는 오류로 검증하고 기존 옵션·광고 설정을 검증한 다음 클라이언트·정책을 한 번 준비한다. 복구 옵션이 있으면 종료 요청 여부를 확인해 _recover_401을 실행하고 반환한다. 기본 모드는 각 반복에서 DB 연결을 정리하고 dispatch_due_impressions에 저장소·배치 크기·종료 확인 함수를 전달한다. 처리 요약을 출력하고 필요하면 Event로 대기한다.

반복 모드의 DB 장애는 원문 접속 정보 없이 알린 뒤 다음 주기에 다시 시도한다. `--once`의 DB 작업 실패는 CommandError로 실패 종료한다. 예상하지 못한 오류와 KeyboardInterrupt를 일반 DB 장애로 바꾸지 않는다. 종료 시 이전 SIGINT 처리기를 복원하고 DB 연결을 정리한다.

작업자 연결: `ad-bridge/scripts/delivery/worker.py::dispatch_due_impressions`.

다음은 AST 호출 구문 보조 근거다. 외부 런타임의 정의·시그니처는 이 문서의 분석 대상이 아니다. 표준 출력·오류 출력 메서드도 AST 호출 목록에 있다.

```text
AdsClient
AdsConfig.from_env
CommandError
Event
RetryPolicy
UUID
close_old_connections
current_thread
dispatch_due_impressions
isinstance
main_thread
math.isfinite
self._recover_401
self.stderr.write
self.stdout.write
signal.getsignal
signal.signal
stop.is_set
stop.wait
str
type
```

### 중첩 종료 함수

`ad-bridge/scripts/management/commands/dispatch_ad_reactions.py::def Command.handle.request_stop(signum, frame)`

handle 안에 직접 선언된 종료 신호 함수다. 첫 Ctrl+C는 종료 플래그를 설정해 진행 중인 요청의 결과 저장 후 다음 요청을 멈추게 한다. 두 번째 Ctrl+C는 KeyboardInterrupt를 발생시킨다. 첫·두 번째 신호의 의미는 기존 연동 안내와 함께 설명한다.

다음은 AST 호출 구문이며 Event 객체의 메서드를 이 파일에서 직접 정의했다는 뜻이 아니다.

```text
stop.is_set
stop.set
```

### 401 수동 복구

참조: `ad-bridge/scripts/management/commands/dispatch_ad_reactions.py::def Command._recover_401(self, *, client, policy, reaction_id)`

정규화한 반응 UUID로 실행 요청을 출력하고 DB 연결을 정리한다. claim_blocked_401_impression에 현재 UTC 시각과 정책의 임대 시간을 전달한다. 대상이 없거나 조건에 맞지 않으면 제외 결과를 출력하고 실패 종료하며 HTTP를 전송하지 않는다. 성공한 임대만 저장된 ID·가명·발생 시각 그대로 send_once에 전달한다.

출력은 반응 ID·전송 상태·시도 횟수·마지막 HTTP 오류로 한정한다. 원본 사용자 UUID·광고 가명·설정 비밀·판정 사유·외부 오류 원문은 출력하지 않는다. 복구 DB 또는 저장 기록 검증 오류는 원문 없이 CommandError로 알린다. 접수가 확인되지 않아도 저장된 결과를 출력한 뒤 실패 종료한다. 재차 401이면 BLOCKED로 남으며 이 명령은 일반 작업자나 대기 루프를 실행하지 않는다. 마지막 HTTP 오류가 없으면 성공 HTTP 코드를 추정하지 않고 없음으로 표시한다.

handle의 공통 종료 처리로 SIGINT 처리기 복원과 DB 연결 정리를 수행한다. 선언·호출 표기는 routing-doc-sync AST 결과를 사용한다. 명령 옵션·복구 함수 연결·단일 실행·실패 종료·안전한 출력·종료 정리는 HTTP·DB 경계를 대체한 명령 테스트로 확인했다. 실제 운영 DB에는 복구를 실행하지 않았다.

## 의존성과 탐색

| 연결 모듈 | AST import가 보여주는 연결 |
|---|---|
| [공개 API](../../__init__.py.md) | AdsClient·AdsConfig |
| [재전송 정책](../../delivery/policy.py.md) | RetryPolicy |
| [재전송 작업자](../../delivery/worker.py.md) | dispatch_due_impressions |
| [공통 전송](../../delivery/sender.py.md) | send_once |
| [노출 저장소](../../impressions/store.py.md) | store as impression_store |

외부 의존성은 Django BaseCommand·CommandError·DatabaseError·close_old_connections와 표준 라이브러리 threading·math·signal·uuid다. 호출 구문 목록은 실행 흐름 탐색을 돕는 정적 근거이며 실제 네트워크·DB 실행 성공을 뜻하지 않는다.
