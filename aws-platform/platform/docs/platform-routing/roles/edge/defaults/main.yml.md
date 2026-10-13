# roles/edge/defaults/main.yml

edge_http_redirect와 edge_frontend_mode 기본값은 false로 기존 호출을 보존한다. 새 Front 인벤토리는 둘 다 true로 지정하며 각 호스트의 EIP·단일 Backend를 사용한다.

[역할 개요](../README.md) · [원본](../../../../../roles/edge/defaults/main.yml)

실제 EIP, HTTPS 사용자 IPv4 CIDR, Front 목적지 목록, Certbot 5.8.0·가상환경·ACME 연락처·운영 endpoint·인증서 경로를 선언한다.

edge_client_max_body_size 기본값은 1m이다. 광고 Front 인벤토리에서만 3m으로 덮어쓰고 게임 Front는 기본값을 사용한다.
