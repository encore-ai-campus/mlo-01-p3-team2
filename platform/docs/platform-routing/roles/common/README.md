# common: 공통 보안과 시간 동기화

[탐색 시작점](../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

모든 서버. Bastion을 먼저 구성한다.

팀원 users, sshd drop-in, OS별 서비스 이름, Amazon Time Sync 시간원을 수정할 때 찾는다.

## 현재 작업 흐름

OS 변수 → 패키지 → 팀원 계정·키·sudo → sshd → UTC·chrony → 검증

## 구현 조건

sshd 문법 실패 시 drop-in을 제거한다. sudo 목록에서 제외한 사용자의 sudo 권한은 제거하지만 사용자 계정을 삭제하는 작업은 없다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/common/handlers/main.yml | [main.yml](handlers/main.yml.md) | notify로 요청한 서비스 reload/restart를 처리한다. 호출 작업의 flush_handlers 위치도 함께 확인한다. |
| roles/common/tasks/main.yml | [main.yml](tasks/main.yml.md) | OS별 변수와 패키지를 준비하고 팀원 계정·SSH·sudo·UTC·chrony를 설정한 뒤 검증을 연결한다. |
| roles/common/tasks/os-debian.yml | [os-debian.yml](tasks/os-debian.yml.md) | Ubuntu의 needrestart를 목록 알림 모드로 설정하고 chrony에 Amazon Time Sync 시간원을 추가한다. |
| roles/common/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | sshd 유효 설정, UTC, NTP 동기화, chrony 선택 시간원과 Leap status를 확인한다. |
| roles/common/templates/sshd-hardening.conf.j2 | [sshd-hardening.conf.j2](templates/sshd-hardening.conf.j2.md) | 비밀번호·root 로그인을 끄고 공개키 로그인을 허용한다. Bastion이면 TCP forwarding도 허용한다. |
| roles/common/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 공통 보안과 시간 동기화의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/common/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 공통 보안과 시간 동기화의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
