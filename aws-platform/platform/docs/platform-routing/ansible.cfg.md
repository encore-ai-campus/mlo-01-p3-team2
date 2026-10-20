# ansible.cfg

[탐색 시작점](../ROUTING-README.md) · [원본 파일](../../ansible.cfg)

## 역할

기본 인벤토리, 역할 경로, 대상 시스템 Python과 SSH 연결 재사용을 지정한다.

## 핵심 설정

기본 인벤토리는 inventory/hosts.current.yml, roles_path는 roles, interpreter_python은 /usr/bin/python3다. 현재 프로필의 생성 인벤토리를 사용하며 다른 프로필·팀 접속용·수동 인벤토리는 -i로 지정한다. 파일이 없는 새 체크아웃에서는 먼저 Inventory를 생성해야 한다. SSH pipelining과 ControlPersist=60s를 사용하고 새 host key는 accept-new로 처리한다. 명령은 platform 디렉터리에서 실행하는 구성을 전제로 한다.

## 검증 범위

2026-10-13 WSL에서 이 설정을 `ANSIBLE_CONFIG`로 지정하고 -i 없는 대상 목록 조회와 네 진입 playbook의 문법 검사를 통과했다. MySQL 3대와 Front 2대가 선택됨을 확인했으며 실제 원격 서버에는 적용하지 않았다. 자세한 범위는 [검증 기록](verification.md)을 따른다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
