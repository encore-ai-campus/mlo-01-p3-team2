# ansible.cfg

[탐색 시작점](ROUTING-README.md) · [원본 파일](../../ansible.cfg)

## 역할

기본 인벤토리, 역할 경로, 대상 시스템 Python과 SSH 연결 재사용을 지정한다.

## 핵심 설정

기본 인벤토리는 inventory/hosts.yml, roles_path는 roles, interpreter_python은 /usr/bin/python3다. SSH pipelining과 ControlPersist=60s를 사용하고 새 host key는 accept-new로 처리한다. 명령은 platform 디렉터리에서 실행하는 구성을 전제로 한다.

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
