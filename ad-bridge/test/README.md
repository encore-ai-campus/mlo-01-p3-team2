# 광고 연결 기능별 테스트

대상은 scripts/ad_bridge의 게임 서버용 코드다. HTTP·사용자·저장소를 대체하는 단위 검사와
임시 SQLite를 사용하는 저장소 검사를 분리한다. 실제 광고 서버·게임 DB·매체 키는 사용하지 않는다.
설치와 전체 기능 설명은 [프로젝트 README](../../README.md)를 참고한다.

## 환경 준비

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "Django>=5.2.8,<5.3"
```

아래 python은 이 가상환경의 Python을 사용한다. 실행기는 scripts를 import 경로에 넣으므로
PYTHONPATH를 설정할 필요가 없다. requirements 파일은 현재 저장소에 포함하지 않는다.

## 실행 방법

```powershell
python -B scripts/test/run.py --list
python -B scripts/test/run.py all
python -B scripts/test/run.py results
python -B scripts/test/run.py results accepted
python -B scripts/test/run.py results lookup_error
python -B scripts/test/run.py retry due
```

그룹 이름만 지정하면 해당 기능 전체, 뒤에 사례 이름을 붙이면 한 사례만 실행한다.
--list가 실제 실행 가능한 그룹과 사례 이름을 출력한다.

## 단위 테스트: all에 포함

| 그룹 | 개수 | 내용 |
|---|---:|---|
| config | 8 | 설정과 인증 키·URL·타임아웃 검증 |
| request | 10 | 광고 결정 POST·광고 없음·응답 검증 |
| decisions | 3 | 결정 저장 순서·실패·광고 없음 |
| game | 11 | 게임 요청·로그인·CSRF·가명 UUID·오류 |
| impression | 18 | 노출 PUT 계약·멱등 값·접수 확인 |
| impression_service | 12 | 첫 예약·중복·전송·저장 실패 |
| game_impression | 17 | 게임 노출 경로·소유권·접수·오류 |
| retry | 19 | 재시도 일정·임대·동일 내용·오래된 응답 |
| retry_command | 12 | 관리 명령·반복·중단·DB 오류 |
| result_client | 8 | 반응 GET·응답 형식·HTTP·연결 오류 |
| results | 8 | 처리 중·인정·거절·소유권·조회 및 저장 실패 |
| 합계 | 126 | 실제 DB를 생성하지 않는 단위 검사 |

결과 조회 GET과 판정 저장은 구현되어 있다. 접수 확인은 최종 인정·과금과 구분한다.

## 별도 저장소 검사

```powershell
python -B scripts/test/run.py storage
python -B scripts/test/run.py retry_storage
python -B scripts/test/run.py result_storage
python -B scripts/test/run.py result_storage race
```

| 그룹 | 개수 | 내용 |
|---|---:|---|
| storage | 15 | 소유권·최초 기록·고유 제약·트랜잭션 |
| retry_storage | 17 | 일정·작업 임대·경합·복구·마이그레이션 |
| result_storage | 6 | 판정 저장·기존 전송 정보 보존·확정 판정 보호 |

이 그룹은 all에 포함하지 않는다. 테스트 전용 메모리 SQLite를 만들고 폐기하며
환경에 실제 게임·광고 DB 설정이 있어도 사용하지 않는다. 실제 MySQL 동시 처리 검증과는 구분한다.

## 파일 위치

api·decisions·impressions·delivery·results·game 폴더는 해당 기능의 단위 검사,
storage는 임시 DB 검사다. 시계·가짜 응답·메모리 저장소·Django 설정은 support에 둔다.
테스트 파일끼리 도구를 가져오지 않고 공통 fixture를 support에서 사용한다.
integration_tests는 광고 서버의 별도 계약 검사이고 이 실행기의 all에 포함하지 않는다.

2026-10-12: all 126개, storage 15개, retry_storage 17개, result_storage 6개를 다시 실행하여
총 164개 통과했다. 이 결과만으로 실제 서버 연결·광고 표시·포인트 차감 성공까지 의미하지 않는다.
