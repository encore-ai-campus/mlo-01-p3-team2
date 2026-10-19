# roles/edge/tasks/verify.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/verify.yml)

nginx -t, IP 인증서 SAN·잔여 1시간 이상, 로컬 443의 신뢰 CA와 이름 검증을 실행한다. TLS server_hostname은 도메인이 있으면 도메인, 없으면 EIP다. 도메인 인증서도 잔여 수명을 확인한다. HTTP는 edge_http_redirect에 따라 308/404이며 도메인 모드의 Location을 검사한다. 갱신 timer active를 확인한다. 앱 로그인·WebSocket 연결·외부 사용자 접속 성공은 별도 검증이다.
