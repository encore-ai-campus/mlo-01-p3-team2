# edge: Nginx와 공인 IP HTTPS

## 현재 Front 두 대의 독립 설치 — 2026-10-13

설치 코드 이름은 edge를 유지하지만 별도 edge EC2를 생성하지 않는다. site.yml·edge.yml은 game_frontend와 ad_frontend에도 이 역할을 각각 실행한다. 두 서버는 Nginx·Certbot·자기 EIP 인증서·갱신 타이머를 각각 갖는다.

deploy.ps1이 Front마다 edge_frontend_mode=true, edge_http_redirect=true, 공개 CIDR 0.0.0.0/0과 Backend 사설 IP:8000 하나를 전달한다. HTTP ACME 경로는 검증 파일을 제공하고 다른 요청은 HTTPS로 308 이동한다. HTTPS의 모든 앱 경로는 자기 Backend로 전달한다. HSTS는 설정하지 않는다. Backend 앱 설치·바인딩·정적 파일 제공은 이 역할 범위 밖이다.

아래의 404·빈 준비 화면·다중 Front 분산 설명은 기본값을 사용하는 기존 edge 호출에 해당한다. 현재 Front 모드에서는 목적지가 반드시 하나여야 한다. 로컬 YAML/Ansible 문법과 두 Front·방화벽 렌더링을 검증했으며 실제 인증서 발급 및 원격 nginx -t는 실행하지 않았다.

[역할 지도](../README.md) · [단독 playbook](../../edge.yml.md) · [통합 playbook](../../site.yml.md)

Ubuntu 24.04 진입 서버에 Nginx와 별도 Python 가상환경의 Certbot 5.8.0을 설치한다. 현재 두 Front의 Nginx·Certbot을 각각 설치하며 게임·광고 앱은 설치하지 않는다. site.yml --tags edge 또는 독립 edge.yml로 호출한다.

## 입력과 실행

| 변수 | 의미 |
| --- | --- |
| edge_public_ip | 인증서에 넣을 서버 EIP. 기본 public_ip를 사용하며 유효한 공인 IPv4여야 한다. |
| edge_https_allowed_cidrs | HTTPS에 접속할 사용자 IPv4 CIDR 목록. 빈 목록은 실패한다. |
| edge_frontend_upstreams | Front 모드에서 Backend 사설 IP:8000 한 개 필수. 기본 빈 목록은 이전 호출의 준비 화면용 |
| edge_frontend_mode | 기본 false. 현재 Front는 true: 단일 목적지 검사·Host 원문 전달 |
| edge_http_redirect | 기본 false. 현재 Front는 true: ACME 외 HTTP 요청을 자기 EIP의 HTTPS로 308 이동 |
| edge_acme_email | 선택 연락처. 빈 기본값이면 연락처 없이 ACME 계정을 등록한다. |
| edge_acme_preflight | 기본 true. 최초 발급 전에 인증서를 저장하지 않는 staging dry-run을 실행한다. |
| edge_certbot_version | 기본 5.8.0. IP webroot 지원을 위해 5.4.0 이상을 검사한다. |
| edge_acme_server | 기본 Let’s Encrypt 운영 ACME directory. 검증은 운영 신뢰 체인을 요구한다. |

```bash
# 저장소 inventory/group_vars 밖에 둔 실제 인벤토리와 실행 변수를 지정한다.
ansible-playbook -i /운영자경로/edge-hosts.yml edge.yml -e @/운영자경로/edge-vars.yml
# 사용자 접속 IP 변경은 nftables와 Nginx에 같이 적용한다.
ansible-playbook -i /운영자경로/edge-hosts.yml edge.yml --tags firewall,edge -e @/운영자경로/edge-vars.yml
```

Ubuntu 공식 archive/security 및 EC2 지역별 archive 주소를 HTTPS 공식 주소로 바꾼 뒤 패키지를 설치한다. 서버는 직접 HTTPS 외부 연결 또는 준비된 프록시가 필요하다. SSH 경로는 인벤토리를 따른다. 현재 생성 인벤토리는 Bastion 경유이며, 이전 독립 edge 인벤토리는 직접 접속할 수 있다.

## 인증서 수명과 서비스 경계

HTTP ACME 경로는 검증 파일을 제공한다. 현재 Front의 나머지 HTTP 요청은 HTTPS로 308 이동하며, edge_http_redirect=false인 이전 호출만 404다. 인증서가 없는 상태에서443을 먼저 활성화하지 않는다. 인증서가 있으면 재실행 시에도 HTTPS를 유지한다. 최초 staging dry-run 성공 후 certonly --webroot --ip-address --required-profile shortlived로 운영 인증서를 발급한다. 요청 시 ACME 이용약관에 동의하며 계정·키는 서버 /etc/letsencrypt에 저장한다. 재실행은 유효 인증서를 유지한다.

인증서가 준비되면 Nginx는 TLS 1.2/1.3과 사용자 CIDR 접근 제한을 적용한다. AWS SG도 동일 CIDR의443을 허용해야 한다. 현재 Front는 0.0.0.0/0으로 80·443을 전체 허용한다. 기존 edge 분기만 별도 CIDR 제한을 유지한다. 로컬 HTTPS 검증용127.0.0.1은 Nginx에서 허용한다.

현재 Front 모드는 목적지가 정확히 하나여야 한다. 이전 호출에서 Front 목록이 비어 있으면 정적 준비 화면을 제공하므로 애플리케이션 배포 완료를 의미하지 않는다. 목록을 지정하면 least_conn과 수동 장애 감지(max_fails=2, fail_timeout=10s)를 사용하고 HTTP/WebSocket 요청을 전달한다. CPU·메모리 사용량을 측정하는 분산 방식은 아니다. 진입 EC2 자체의 이중화는 제공하지 않는다.

매시간(최대15분 무작위 지연) systemd timer가 해당 인증서의 certbot renew를 실행한다. 유효한 인증서를 매시간 새로 발급하지 않는다. 갱신 성공 후 deploy hook은 nginx -t 성공 시에만 reload한다. IP 인증서의 약160시간 수명에 맞춘 자동 갱신이며, 실패는 journalctl -u edge-certbot-renew.service에서 확인한다. EIP가 유지되는 동안 사용자 출발지 CIDR 변경은 인증서 재발급 사유가 아니다.

## 소스 지도

| 소스 | 문서 |
| --- | --- |
| defaults/main.yml | [입력 기본값](defaults/main.yml.md) |
| tasks/prepare-os.yml | [Ubuntu 설치 준비](tasks/prepare-os.yml.md) |
| tasks/main.yml | [설치·발급·갱신 연결](tasks/main.yml.md) |
| tasks/verify.yml | [설치 검증](tasks/verify.yml.md) |
| handlers/main.yml | [Nginx·타이머 재적용](handlers/main.yml.md) |
| templates/nginx.conf.j2 | [HTTP 검증·HTTPS 전달](templates/nginx.conf.j2.md) |
| templates/reload-nginx.sh.j2 | [갱신 후 재적용](templates/reload-nginx.sh.j2.md) |
| templates/edge-certbot-renew.service.j2 | [갱신 서비스](templates/edge-certbot-renew.service.j2.md) |
| templates/edge-certbot-renew.timer.j2 | [갱신 타이머](templates/edge-certbot-renew.timer.j2.md) |

공식 근거: [IP 인증서와 Certbot webroot 지원](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/), [Certbot 설치 — pip는 가상환경에서 best-effort 지원](https://eff-certbot.readthedocs.io/en/stable/install.html#alternative-2-pip), [dry-run·프로필·갱신 옵션](https://eff-certbot.readthedocs.io/en/stable/using.html).
