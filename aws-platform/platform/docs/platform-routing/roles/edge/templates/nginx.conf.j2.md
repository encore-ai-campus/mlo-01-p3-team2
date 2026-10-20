# roles/edge/templates/nginx.conf.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/nginx.conf.j2)

/etc/nginx/nginx.conf 전체를 렌더링한다. edge_domain이 비어 있으면 기존 IP 서버와 단일 upstream을 유지한다. edge_http_redirect 기본 false는 일반 HTTP 404, true는 ACME 경로 외 HTTPS 이동이다.

게임 도메인 모드는 HTTP를 도메인으로 이동하고, IP 인증서로 받는 HTTPS default server도 도메인으로 308 이동한다. 도메인 인증서가 준비돼야 도메인 HTTPS 서버를 생성한다. 최초 설치에서 없는 인증서 경로를 참조하지 않는다.

도메인 /는 로컬 Front 127.0.0.1:8004, /static/은 edge_static_root, /ws/campus/는 선택 Backend의 edge_game_backend_host:edge_game_backend_port다. /api/ads/는 503 ads_disabled를 유지한다. 도메인·광고 앱 서버에는 로컬 검증 IP와 edge_https_allowed_cidrs 뒤 deny all을 둔다. 현재 프로필은 7개 /32이며 0.0.0.0/0 임시 HTTPS 허용을 저장하지 않는다. 광고는 Backend:8000에 전달하고 3m 제한, 게임은 1m이다. HSTS는 추가하지 않는다.
