# roles/firewall/templates/infra-firewall.service.j2

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/firewall/templates/infra-firewall.service.j2)

## 역할

부팅 시 /etc/nftables/infra-fw.nft를 로드하는 oneshot unit이다.

## systemd 선언

| 원본 행 | 설정 |
| --- | --- |
| 3 | Description=Infra firewall (nftables table infra_fw) |
| 4 | After=network.target |
| 7 | Type=oneshot |
| 8 | RemainAfterExit=yes |
| 9 | ExecStart=/usr/sbin/nft -f /etc/nftables/infra-fw.nft |
| 12 | WantedBy=multi-user.target |

## 함께 볼 파일

- [roles/firewall/tasks/main.yml](../tasks/main.yml.md)

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
