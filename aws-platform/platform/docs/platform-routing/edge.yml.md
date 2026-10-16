# edge.yml: Front별 HTTPS 설치

[탐색 시작점](../ROUTING-README.md) · [원본](../../edge.yml) · [edge 역할](roles/edge/README.md)

hosts: edge:game_frontend:ad_frontend, become=true, any_errors_fatal=true로 실행한다. 먼저 Ubuntu 24.04 공식 APT 저장소를 HTTPS로 정리하고 common → firewall → edge 역할 순서로 적용한다. Bastion이나 DB Vault를 별도로 읽지 않는다. 단, 인벤토리를 inventory/ 안에 두면 Ansible이 기존 group_vars/Vault를 자동으로 읽을 수 있으므로 단일 서버 인벤토리는 그 밖에 둔다.

필수 입력은 실제 서버 EIP인 edge_public_ip와 사용자 출발지 IPv4 CIDR 목록 edge_https_allowed_cidrs다. SSH 주소·키는 운영자 인벤토리에서 지정한다. 현재 두 Front는 0.0.0.0/0이며 인벤토리의 단일 Backend와 독립 EIP 인증서를 사용한다. 제한형 기존 edge 호출에서 사용자 IP를 바꿀 때는 AWS SG와 CIDR을 함께 바꾸고 --tags firewall,edge로 재적용한다. pre_tasks는 always 태그이며 저장소만 확인한다.

이 playbook은 EC2·EIP·SG를 생성하지 않고, Front·게임·광고 앱을 배포하지 않는다. 성공 여부는 실제 실행 결과로 판단한다.
