# monitoring: SSH 수집·로그 회전·보관

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

monitoring 그룹이 있을 때 site.yml이 모든 서버에 실행한다. collector는 monitoring 노드에만 배포한다.

대상 권한은 target.yml, 수집기 배포는 collector.yml, 수집 루프는 files/collector.sh, 보관은 files/archive.sh에서 찾는다.

## 현재 작업 흐름

OS 변수·대상 계산 → target 설정 → monitoring 노드 collector → 수집·로그·정리 검증

## 구현 조건

archive.sh·collector.sh·resource.sh는 서버로 복사되는 셸 파일이므로 LF 줄바꿈을 유지한다. 저장소 [.gitattributes](../../../../../../.gitattributes)의 roles/monitoring/files/*.sh 규칙이 Windows 체크아웃에도 적용된다. 이번 변경은 줄바꿈 정규화이며 수집·보관 로직 변경은 없다. 기존 로컬 검사 기록은 [검증 기록](../../verification.md#2026-10-13-기본-인벤토리와-모니터링-셸-줄바꿈-수정)에서 확인한다.

기본 리소스·로그 수집 목표 주기는 10초, 서비스 상태는 3주기마다다. 작업 시간이 길어지면 실제 주기가 늘어난다. 수집기는 SSH 사용자명을 monitor로 고정 사용하므로 monitor_user만 바꿔서는 일치하지 않는다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/monitoring/defaults/main.yml | [main.yml](defaults/main.yml.md) | SSH 수집·로그 회전·보관의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/monitoring/files/archive.sh | [archive.sh](files/archive.sh.md) | 하루 지난 수집 파일을 gzip 복사하고 수집·보관 기한을 넘은 파일을 정리한다. 원본을 보관 폴더로 이동하는 방식은 아니다. |
| roles/monitoring/files/collector.sh | [collector.sh](files/collector.sh.md) | 모든 대상에서 SSH로 리소스·journal·서비스 상태를 가져오고 rsync로 로그를 수집하는 계속 실행되는 루프다. |
| roles/monitoring/files/resource.sh | [resource.sh](files/resource.sh.md) | /proc와 루트 파일시스템에서 CPU·부하·메모리·디스크·네트워크·uptime 누적 값을 키=값 한 줄로 출력한다. |
| roles/monitoring/handlers/main.yml | [main.yml](handlers/main.yml.md) | notify로 요청한 서비스 reload/restart를 처리한다. 호출 작업의 flush_handlers 위치도 함께 확인한다. |
| roles/monitoring/tasks/collector.yml | [collector.yml](tasks/collector.yml.md) | 수집기 사용자·디렉터리·스크립트·SSH 개인키·DB Secret과 수집 서비스·정리 타이머를 구성한다. |
| roles/monitoring/tasks/main.yml | [main.yml](tasks/main.yml.md) | OS별 unit·로그·그룹 목록과 monitoring IP를 계산한 뒤 target, collector, verify를 연결한다. |
| roles/monitoring/tasks/target.yml | [target.yml](tasks/target.yml.md) | 모든 대상에 monitor 사용자·출처 제한 키·읽기 권한·원격 스크립트·logrotate·journald를 구성한다. |
| roles/monitoring/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | 대상 로그 읽기와 수집 서버의 리소스·서비스·로그 수집을 확인하고 archive 서비스를 실행한다. |
| roles/monitoring/templates/hosts.conf.j2 | [hosts.conf.j2](templates/hosts.conf.j2.md) | 전체 인벤토리를 이름&#124;IP&#124;로그 경로&#124;DB Secret 종류 행으로 렌더링한다. |
| roles/monitoring/templates/infra-monitor-archive.service.j2 | [infra-monitor-archive.service.j2](templates/infra-monitor-archive.service.j2.md) | 전용 수집기 사용자로 archive.sh를 실행하는 oneshot unit이다. |
| roles/monitoring/templates/infra-monitor-archive.timer.j2 | [infra-monitor-archive.timer.j2](templates/infra-monitor-archive.timer.j2.md) | 매일 UTC 03:30(한국 시간 12:30)에 archive 서비스를 실행한다. Persistent=true다. |
| roles/monitoring/templates/infra-monitor.service.j2 | [infra-monitor.service.j2](templates/infra-monitor.service.j2.md) | 전용 수집기 사용자로 collector.sh를 실행하고 항상 재시작하는 systemd unit이다. |
| roles/monitoring/templates/logrotate.j2 | [logrotate.j2](templates/logrotate.j2.md) | 서비스 로그를 daily/dateext/copytruncate로 회전한다. 압축은 수집 서버의 archive가 담당한다. |
| roles/monitoring/templates/monitor.conf.j2 | [monitor.conf.j2](templates/monitor.conf.j2.md) | 수집·보관 경로, 키, 목표 주기, 장애 임계치와 보관 기간의 셸 설정을 렌더링한다. |
| roles/monitoring/templates/service.sh.j2 | [service.sh.j2](templates/service.sh.j2.md) | 역할에 맞는 systemd·MySQL·MongoDB·Kafka·ZooKeeper·Spark 상태를 출력한다. DB monitor 비밀번호는 표준입력 첫 줄로 받는다. |
| roles/monitoring/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 SSH 수집·로그 회전·보관의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/monitoring/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 SSH 수집·로그 회전·보관의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
