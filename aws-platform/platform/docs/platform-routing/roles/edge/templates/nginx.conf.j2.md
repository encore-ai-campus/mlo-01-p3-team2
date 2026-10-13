# roles/edge/templates/nginx.conf.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/nginx.conf.j2)

edge_http_redirect=true이면 HTTP80의 ACME 경로는 webroot로 제공하고 나머지 요청은 해당 서버 EIP의 HTTPS로 308 이동한다. 기본 false인 기존 호출은 404를 유지한다. 인증서가 준비되기 전에는 443과 인증서 경로를 렌더링하지 않는다.

각 Front는 자신의 EIP 인증서와 하나의 Backend 사설 IP:8000을 사용한다. 공개 Front의 CIDR은 0.0.0.0/0이다. edge_frontend_mode에서는 Host 원문을 전달하고 X-Forwarded-For는 실제 접속 IP로 덮어쓴다. /static/·/assets/를 따로 서빙하지 않고 Backend로 전달한다. IP 주소용 HSTS는 추가하지 않는다. 기존 빈 목록의 준비 화면은 legacy 호출에만 남아 있다.

HTTPS server 블록의 client_max_body_size는 edge_client_max_body_size를 사용한다. 광고 Front는 3m, 게임 Front는 기본 1m이다. 제한을 초과한 요청은 Nginx가 413으로 응답하며 Backend까지 전달되지 않는다.
