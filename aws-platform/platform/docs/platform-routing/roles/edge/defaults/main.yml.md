# roles/edge/defaults/main.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/defaults/main.yml)

edge_domain 기본 빈 값은 IP 방식을 유지한다. edge_domain_cert_name은 도메인과 같으며, IP용 edge_cert_name은 edge-ip-{EIP}다. edge_http_redirect·edge_frontend_mode 기본 false이며 인벤토리는 Front 모드를 켜고 게임 도메인에만 HTTP 이동을 켠다.

edge_game_backend_host와 기본 포트 8000은 게임 WebSocket 목적지다. edge_static_root 기본 /var/www/playdata-campus/static/, 게임 앱 upstream은 인벤토리에서 127.0.0.1:8004로 지정한다. 허용 CIDR은 빈 기본값을 그대로 사용할 수 없으며 프로필에서 전달한다. 광고 본문 3m, 게임 기본 1m이다. Certbot 5.8.0, ACME endpoint·webroot·가상환경·연락처 기본값도 이 파일에서 관리한다.
