# Router 통합 로컬 회귀 검사

[원본 파일](../../../tests/validate_router_scope.py) · [검사 지도](README.md)

WSL의 기존 Ansible·Jinja·YAML·Node 환경에서 실행한다.

```bash
python tests/validate_router_scope.py
```

 실제 EC2·Vault·MySQL 서버를 사용하지 않는다. 임시 인벤토리, 가짜 mysql/mysqlsh와 역할 사본을 사용하며 사본의 해시 파일 소유권만 현재 사용자로 바꿔 sudo 없이 검사한다.

검사 범위는 Router 그룹 일치·중복 제거, 현재 Primary 선택, 계정 해시 재사용, Primary 없음·다중 Primary·OFFLINE·부분 MySQL 제한 거부, 광고만 선택 시 설치 전 중단, 기존 dev 보존·신규 생성, mysql_router 태그의 저장소·패키지 하위 작업 실행이다.

## AST로 확인한 선언

- `aws-platform/platform/tests/validate_router_scope.py::def execute(roles, limit=None, success=True)`

Python 구조는 routing-doc-sync 결과를 사용한다. 원격 설치·실제 장애 전환을 검증하는 테스트는 아니다.
