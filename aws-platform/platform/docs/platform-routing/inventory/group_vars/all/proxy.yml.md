# inventory/group_vars/all/proxy.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../../README.md) · [원본 파일](../../../../../inventory/group_vars/all/proxy.yml)

## 역할

프록시 주소, 원격 다운로드 환경변수, 배스천 방화벽의 포트·VPC CIDR을 공유한다. proxy_enabled 자체는 정의하지 않으며 실제 인벤토리에서 활성화한다. 따라서 기존 인벤토리의 실행 방식은 기본적으로 유지된다.

| 변수 | 의미 |
| --- | --- |
| proxy_port | Squid TCP 포트. 기본 3128. |
| proxy_client_cidrs | 프로젝트 account1~5의 VPC CIDR. |
| proxy_bastion_host | bastion 그룹의 첫 호스트. 활성 구성은 준비 단계에서 정확히 1대인지 검사한다. |
| proxy_url | 배스천 ip와 포트에서 계산한다. 비활성 상태는 빈 문자열이다. |
| proxy_is_client | 활성 상태이면서 bastion 그룹이 아닌 호스트다. |
| proxy_no_proxy | localhost·메타데이터·인벤토리 호스트명·ip를 나열한다. CIDR 해석에 의존하지 않는다. |
| proxy_environment | 클라이언트에는 프록시를, 배스천에는 빈 프록시 환경변수를 전달한다. 비활성 상태는 빈 사전이다. |
| proxy_check_url / proxy_check_download_url | Ubuntu HTTPS 연결과 파일 다운로드 검사 주소다. |

## 선언된 기본값과 연결 조건

| 항목 | 현재 선언 |
| --- | --- |
| proxy_port | 3128 |
| proxy_client_cidrs | 10.10.0.0/16, 10.20.0.0/16, 10.30.0.0/16, 10.40.0.0/16, 10.50.0.0/16 |
| proxy_check_url | https://archive.ubuntu.com/ubuntu/ |
| proxy_check_download_url | https://archive.ubuntu.com/ubuntu/dists/noble/InRelease |
| proxy_url | 유효한 활성 구성에서 http://배스천사설IP:proxy_port 형태다. HTTPS 다운로드도 이 HTTP 프록시 주소를 사용한다. |
| proxy_environment | 활성 클라이언트: http_proxy·https_proxy=proxy_url, no_proxy=proxy_no_proxy. 활성 배스천: 두 프록시 값은 빈 문자열이고 no_proxy는 유지한다. 비활성: 빈 사전이다. |

no_proxy에는 localhost, 127.0.0.1, ::1, 169.254.169.254와 전체 인벤토리 호스트명·ip를 중복 제거해 쉼표로 연결한다. 이 계산은 전체 호스트의 ip 변수를 참조하므로 실행 --limit에 포함되지 않는 호스트도 ip가 정의되어 있어야 한다. 실제 IP 값은 이 문서에 수록하지 않는다.

proxy_enabled 미지정 시 기본 비활성 조건을 사용한다. proxy_bastion_host가 없으면 proxy_url은 빈 문자열이며, 활성 구성이면 prepare-proxy.yml의 입력 검사에서 배스천 1대 조건을 확인한다. 이 변수 파일 자체가 Squid나 방화벽을 설치하는 것은 아니다.

## 함께 볼 파일

- [prepare-proxy.yml](../../../prepare-proxy.yml.md)
- [site.yml](../../../site.yml.md)
- [방화벽 템플릿](../../../roles/firewall/templates/infra-fw.nft.j2.md)

Ansible YAML과 Jinja 변수는 Python AST 자동 심볼 검사 범위 밖이다. 실제 실행 결과는 검증 기록에 구분해서 기록한다.
