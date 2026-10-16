# roles/firewall/vars/main.yml

[탐색 시작점](../../../../ROUTING-README.md) · [영역 안내](../README.md) · [원본 파일](../../../../../roles/firewall/vars/main.yml)

## 역할

SSH 출처와 그룹 간 허용 관계를 정의한다. 키는 연결을 받는 그룹이며, from/self는 SSH 22를 제외한 포트를 허용한다. AWS SG가 서비스별 단일 포트와 출발지·목적지를 제한한다. frontend의 OS 허용만으로 AWS의 외부 443 접속이 열리는 것은 아니다.

| 수신 그룹 | 허용하는 from 그룹 | 같은 그룹 허용 |
| --- | --- | --- |
| frontend | 모든 출처 TCP 80·443 | 없음 |
| backend | frontend, spark, bastion | 없음 |
| game | frontend, ad, bastion | 없음 |
| ad | frontend, game, bastion | 없음 |
| mysql | game, ad, backend, spark, bastion | 있음 |
| mongodb | ad, consumer, backend, spark, bastion | 있음 |
| kafka | game, ad, mysql, backend, spark, bastion, consumer | 있음 |
| spark | backend, bastion | 있음 |

SSH 출처는 기존 bastion·monitoring 그룹이다. from 목록에 bastion이 있어도 SSH 허용은 별도 SSH 규칙과 기본값을 따른다. Kafka의 데이터를 Spark·Consumer가 읽을 때는 클라이언트가 만든 연결과 established 응답 규칙을 사용하므로 Spark에 kafka 출처를 추가하지 않는다.

## 변경과 검증

2026-10-11 game·ad 수신 역할과 DB·Kafka 허용 출처를 인프라의 애플리케이션 연결에 맞췄다. YAML 로딩, 역할별 Jinja 템플릿 9종 렌더링, 소스 IP 허용 67건, established 응답 유지 검사를 통과했다. 원격 Ansible·EC2 서비스 통신은 실행하지 않았다.

YAML·Jinja는 routing-doc-sync의 Python AST 자동 심볼 검사 범위 밖이다. 원본 변수·렌더링 결과를 직접 대조했다. [검증 기록](../../../verification.md#2026-10-11-애플리케이션-통신-방화벽)을 따른다.

## Edge HTTPS 추가

edge 그룹은 HTTP80을 모든 출처에 허용한다. HTTPS443은 edge_https_allowed_cidrs가 있을 때 해당 IPv4 CIDR만 허용한다. 목록이 없으면443을 열지 않는다. Nginx도 같은 CIDR을 검사하고 HTTP80의 ACME 경로 외 요청을404로 차단한다. 사용자 공인 IP 변경 시 AWS SG·nftables·Nginx를 함께 갱신한다. 기존 다른 역할 규칙은 보존한다.
