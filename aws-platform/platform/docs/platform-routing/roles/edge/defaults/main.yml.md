# roles/edge/defaults/main.yml

edge_http_redirect와 edge_frontend_mode 기본값은 false로 기존 호출을 보존한다. 새 Front 인벤토리는 둘 다 true로 지정하며 각 호스트의 EIP·단일 Backend를 사용한다.

[역할 개요](../README.md) · [원본](../../../../../roles/edge/defaults/main.yml)

실제 EIP, HTTPS 사용자 IPv4 CIDR, Front 목적지 목록, Certbot 5.8.0·가상환경·ACME 연락처·운영 endpoint·인증서 경로를 선언한다.
