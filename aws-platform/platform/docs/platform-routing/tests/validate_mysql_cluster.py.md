# tests/validate_mysql_cluster.py

[탐색 시작점](../../ROUTING-README.md) · [테스트 안내](README.md) · [원본 파일](../../../tests/validate_mysql_cluster.py)

정규 파일 참조: `aws-platform/platform/tests/validate_mysql_cluster.py`.

## 실행과 범위

Ansible·Jinja2·PyYAML과 Node.js가 있는 컨트롤 노드에서 다음 명령으로 실행한다.

```bash
python tests/validate_mysql_cluster.py
```

 MySQL/Router 템플릿을 가짜 비밀번호·IP로 렌더링하고 SQL·설정 조건을 확인한다. Node 모의 검증을 실행한 뒤 실제 Ansible의 입력 검사 작업만 ansible_connection=local로 실행한다. 3노드 정상·2노드 거부·중복 ID·0 ID·중복 IP·일부 limit 거부를 검사한다. 신규 설정·정상 재실행·중지된 기존 서버·가입된 설정 변경·설정 포함 경로 변경 보호까지 Ansible 검사 11개이며, hosts.example.yml로 site.yml 문법을 검사한다. 원격 서버에는 접속하지 않는다.

임시 디렉터리는 종료 시 삭제하며 Windows node.exe를 WSL에서 호출할 때 파일 경로를 wslpath로 변환한다. Python 선언 구조는 routing-doc-sync의 inventory로 확인한다. DB 복제와 실제 장애 전환은 이 모의 검증으로 증명되지 않는다.

[AdminAPI 시나리오](mysql_cluster.test.cjs.md) · [검증 기록](../verification.md)

## Python 선언 구조

routing-doc-sync inventory에서 parse_status=ok, symbols=[]로 확인했다. 함수·클래스 선언이 없는 최상위 실행 스크립트다. 모듈을 import해 구조를 추출하지 않았다.
