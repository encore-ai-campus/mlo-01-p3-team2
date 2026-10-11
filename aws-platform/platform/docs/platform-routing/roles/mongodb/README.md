# mongodb: MongoDB 설치·인증·Replica Set

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

mongodb 그룹. 첫 번째 노드에서 초기화와 계정 작업을 한다.

커널 처리, 저장소, keyfile, 계정, 복제 초기화 문제를 찾을 때 사용한다.

## 현재 작업 흐름

Secret·내부 값 → OS 변수·Ubuntu 커널 조건 → 저장소·설치 → keyfile·mongod 설정 → 초기화·계정 → 노드·복제 검증

## 구현 조건

문서상 지원은 1 또는 3대지만 코드 분기는 그룹 크기 > 1이다. 커널 변경·재부팅은 Ubuntu에서 현재 커널이 mongodb_kernel_blocked_from 이상일 때만 수행한다. 외부 호환성 주장 자체는 이번 작업에서 검증하지 않았다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/mongodb/defaults/main.yml | [main.yml](defaults/main.yml.md) | MongoDB 설치·인증·Replica Set의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/mongodb/handlers/main.yml | [main.yml](handlers/main.yml.md) | notify로 요청한 서비스 reload/restart를 처리한다. 호출 작업의 flush_handlers 위치도 함께 확인한다. |
| roles/mongodb/tasks/kernel-debian.yml | [kernel-debian.yml](tasks/kernel-debian.yml.md) | 현재 커널이 기본 기준 6.19 이상이면 GA 커널 패키지를 설치하고 기존 HWE 커널을 제거한 뒤 재부팅·재확인한다. |
| roles/mongodb/tasks/main.yml | [main.yml](tasks/main.yml.md) | Secret·RAM 캐시·URI를 계산하고 OS별 설치·인증·초기화·계정·검증을 연결한다. |
| roles/mongodb/tasks/repo-debian.yml | [repo-debian.yml](tasks/repo-debian.yml.md) | MongoDB APT 저장소·GPG 키로 pkg/apt_repo를 호출한다. |
| roles/mongodb/tasks/repo-redhat.yml | [repo-redhat.yml](tasks/repo-redhat.yml.md) | MongoDB RPM 키 등록 여부를 확인하고 Yum 저장소를 등록한다. |
| roles/mongodb/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | 모든 노드의 인증·계정 권한과 첫 노드의 Replica Set 멤버 상태·실제 복제를 확인한다. |
| roles/mongodb/templates/accounts.js.j2 | [accounts.js.j2](templates/accounts.js.j2.md) | root로 접속해 dev·monitor의 비밀번호·역할을 확인하고 없는 계정 또는 다른 상태만 변경한다. |
| roles/mongodb/templates/bootstrap.js.j2 | [bootstrap.js.j2](templates/bootstrap.js.j2.md) | localhost exception을 사용해 필요하면 Replica Set을 초기화하고 Primary 선출 후 root를 만든다. |
| roles/mongodb/templates/check-node.js.j2 | [check-node.js.j2](templates/check-node.js.j2.md) | 익명 조회 거부, monitor 조회·쓰기 거부, dev의 계정 정보 조회 거부를 검사한다. |
| roles/mongodb/templates/check-replset.js.j2 | [check-replset.js.j2](templates/check-replset.js.j2.md) | PRIMARY 하나와 나머지 SECONDARY를 확인하고 임시 문서의 모든 멤버 복제 후 삭제를 검사한다. |
| roles/mongodb/templates/mongod.conf.j2 | [mongod.conf.j2](templates/mongod.conf.j2.md) | 데이터·로그·캐시·포트·bind IP와 authorization을 설정한다. Replica Set이면 keyfile·replSetName을 추가한다. |
| roles/mongodb/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 MongoDB 설치·인증·Replica Set의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/mongodb/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 MongoDB 설치·인증·Replica Set의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
