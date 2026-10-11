# firewall: nftables 방화벽

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

모든 서버. Bastion에 먼저 적용한다.

역할 간 허용 관계는 vars/main.yml, SSH 전체 허용 기본값과 복구 시간은 defaults/main.yml, 실제 규칙은 templates/infra-fw.nft.j2에서 찾는다.

## 현재 작업 흐름

OS 변수·패키지 → 후보 규칙 → 기존 파일·테이블 비교 → 복구 타이머 → 적용·새 SSH 확인 → 정식 파일 → 부팅 설정·검증

## 구현 조건

from과 self는 SSH 22를 제외한 모든 포트를 허용한다. 서비스별 포트만 허용하는 정책이 아니다. 기본 복구 타이머는 120초다. game·ad 역할은 frontend·상대 앱·mysql·bastion 출처를 허용한다. MySQL에는 ad, MongoDB에는 ad·consumer, Kafka에는 game·ad·mysql·consumer를 포함해 인프라 연결과 맞춘다. 정확한 그룹 목록은 [역할 변수](vars/main.yml.md)를 따른다. Consumer·MySQL 전송 프로그램을 설치하는 기능은 아니다.

프록시를 활성화한 배스천은 이 역할 관계와 별도로 지정 VPC CIDR의 프록시 TCP 포트(기본 3128)를 허용한다. 일반 서버에는 이 추가 규칙을 생성하지 않는다. 적용 후 prepare-proxy.yml의 proxy_verify 태그로 클라이언트에서 새 프록시 요청이 통과하는지 확인한다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/firewall/defaults/main.yml | [main.yml](defaults/main.yml.md) | nftables 방화벽의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/firewall/tasks/main.yml | [main.yml](tasks/main.yml.md) | 후보 규칙을 문법 검사하고 복구 타이머를 예약한 뒤 새 SSH 접속 확인 후 정식 규칙으로 교체한다. |
| roles/firewall/tasks/os-debian.yml | [os-debian.yml](tasks/os-debian.yml.md) | Ubuntu의 nftables 자동 로드를 비활성화하고 ufw 비활성 상태를 확인한다. |
| roles/firewall/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | infra_fw의 drop 정책·SSH 규칙, 부팅 서비스 enabled, 복구 타이머 해제 상태를 확인한다. |
| roles/firewall/templates/infra-firewall.service.j2 | [infra-firewall.service.j2](templates/infra-firewall.service.j2.md) | 부팅 시 /etc/nftables/infra-fw.nft를 로드하는 oneshot unit이다. |
| roles/firewall/templates/infra-fw.nft.j2 | [infra-fw.nft.j2](templates/infra-fw.nft.j2.md) | 기존 역할 허용 규칙과, 프록시 활성 배스천의 VPC CIDR → proxy_port TCP 허용 규칙을 생성한다. |
| roles/firewall/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 nftables 방화벽의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/firewall/vars/main.yml | [main.yml](vars/main.yml.md) | SSH 출처 그룹과 역할별 from/self/전체 출처 TCP 포트 허용 관계의 기준 데이터다. |
| roles/firewall/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 nftables 방화벽의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

프록시 포트·허용 CIDR의 선언 위치는 [공통 프록시 변수](../../inventory/group_vars/all/proxy.yml.md)다. 방화벽 검증 작업 자체에 프록시 접속 검사가 추가된 것은 아니며, 클라이언트 HTTPS·다운로드 확인은 [프록시 준비의 proxy_verify](../../prepare-proxy.yml.md)에서 수행한다.

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.

2026-10-11 로컬에서 역할별 템플릿 9종과 통신 출처 67건을 검사했다. 기존 established,related 응답 허용을 유지한다. 원격 방화벽 적용·EC2 통신은 실행하지 않았다. [검증 기록](../../verification.md#2026-10-11-애플리케이션-통신-방화벽)을 참고한다.

## Edge HTTPS 추가

edge 그룹은 HTTP80을 모든 출처에 허용한다. HTTPS443은 edge_https_allowed_cidrs가 있을 때 해당 IPv4 CIDR만 허용한다. 목록이 없으면443을 열지 않는다. Nginx도 같은 CIDR을 검사하고 HTTP80의 ACME 경로 외 요청을404로 차단한다. 사용자 공인 IP 변경 시 AWS SG·nftables·Nginx를 함께 갱신한다. 기존 다른 역할 규칙은 보존한다.
