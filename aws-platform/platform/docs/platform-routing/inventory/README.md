# 인벤토리와 접속·Secret 지도

## Front별 입력 — 2026-10-13

deploy.ps1이 account1의 두 Front에 EIP·공개 HTTPS CIDR·HTTP 리다이렉트·단일 Backend 주소를 기록한다. 네 서비스의 account1_service_restricted는 Bastion 전용 SSH 및 Backend별 8000 제한을 켠다. 기존 생성 인벤토리는 자동 변경되지 않으며 실제 배포 후 Inventory를 다시 실행해야 한다.

[탐색 시작점](../../ROUTING-README.md)

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| inventory/group_vars/all/main.yml | [main.yml](group_vars/all/main.yml.md) | 기본 사설 IP 접속과 첫 Bastion 공인 IP를 통한 ProxyCommand를 계산한다. Bastion 그룹이 없으면 직접 접속한다. |
| inventory/group_vars/all/mysql.yml | [mysql.yml](group_vars/all/mysql.yml.md) | Cluster 이름·MySQL 포트·로컬 Router 대상과 접속 포트를 공유한다. |
| inventory/group_vars/all/proxy.yml | [proxy.yml](group_vars/all/proxy.yml.md) | 배스천 주소에서 프록시 URL을 계산하고 원격 환경변수·VPC 허용 범위를 공유한다. |
| inventory/group_vars/all/vault.example.yml | [vault.example.yml](group_vars/all/vault.example.yml.md) | MySQL·MongoDB 비밀번호, MongoDB keyfile, 모니터링 SSH 키의 빈 형식과 작성 규칙을 안내한다. 실제 Secret이 아니다. |
| inventory/group_vars/bastion.yml | [bastion.yml](group_vars/bastion.yml.md) | Bastion 접속 주소를 public_ip로 덮어쓰고 경유 SSH 인자를 비운다. |
| inventory/hosts.example.yml | [hosts.example.yml](hosts.example.yml.md) | 실제 hosts.yml을 만들기 위한 그룹·IP·접속 계정·팀원 공개키 예시다. 전체 지원 구성의 완성된 인벤토리는 아니다. |

hosts.example.yml은 형식 예시이며 실제 hosts.yml과 vault.yml은 Git 제외 대상이다. 이 문서에는 운영자의 Secret 값이나 실제 서버 인벤토리를 수록하지 않는다. 일반 서버는 사설 IP, Bastion은 공인 IP로 접속하며 Bastion이 없으면 ProxyCommand를 생략한다.

프록시를 사용할 때는 인벤토리의 all.vars에서 proxy_enabled를 활성화한다. SSH 경유는 기존 main.yml·bastion.yml, 패키지·다운로드 프록시는 새 proxy.yml이 담당한다. no_proxy 계산에는 전체 호스트의 ip가 필요하며 프록시 활성 구성의 배스천은 정확히 1대여야 한다. 실제 접속 준비는 [prepare-proxy.yml](../prepare-proxy.yml.md)에서 확인한다.
