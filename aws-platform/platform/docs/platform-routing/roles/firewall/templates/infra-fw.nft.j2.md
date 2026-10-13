# roles/firewall/templates/infra-fw.nft.j2

account1_service_restricted 호스트는 SSH의 Bastion 전용 분기와 Front 80/443·Backend별 8000 분기를 사용하며 일반 firewall_rules를 중복 적용하지 않는다. 다른 계정의 렌더링은 기존 규칙과 동일하다.

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/firewall/templates/infra-fw.nft.j2)

## 역할

인벤토리 그룹 IP와 firewall_rules에서 inet infra_fw input 체인을 생성한다. 기존·관련 연결, loopback, DHCP·IPv6 이웃 탐색도 허용한다. proxy_enabled가 켜진 배스천에는 proxy_client_cidrs에서 proxy_port로 들어오는 TCP 연결만 추가 허용한다. 프록시 비활성 호스트와 일반 서버에는 이 규칙을 넣지 않는다.

29~33행의 추가 규칙 조건은 proxy_enabled의 bool 변환과 bastion 그룹 소속이다. 선언된 CIDR을 쉼표로 연결해 source 집합을 만들며 기본 포트는 3128이다. 이 설정은 배스천의 nftables 입력 규칙을 생성하며 Squid ACL 또는 AWS 보안그룹을 변경하지 않는다.

## 템플릿 입력

출력식의 정적 표기다. 로컬 루프 변수·macro 인자가 포함될 수 있으므로 모두 외부 필수 변수라는 뜻은 아니다.

| 출력식 |
| --- |
| ssh_ips &#124; unique &#124; join(', ') |
| proxy_client_cidrs &#124; join(', ') |
| proxy_port |
| g |
| ips &#124; unique &#124; join(', ') |
| rule.tcp_ports_from_anywhere &#124; join(', ') |

## 함께 볼 파일

- [roles/firewall/tasks/main.yml](../tasks/main.yml.md)
- [프록시 포트·VPC CIDR 선언](../../../inventory/group_vars/all/proxy.yml.md)
- [프록시 준비·접속 검사](../../../prepare-proxy.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.

## Edge HTTPS 추가

edge 그룹은 HTTP80을 모든 출처에 허용한다. HTTPS443은 edge_https_allowed_cidrs가 있을 때 해당 IPv4 CIDR만 허용한다. 목록이 없으면443을 열지 않는다. Nginx도 같은 CIDR을 검사하고 HTTP80의 ACME 경로 외 요청을404로 차단한다. 사용자 공인 IP 변경 시 AWS SG·nftables·Nginx를 함께 갱신한다. 기존 다른 역할 규칙은 보존한다.
