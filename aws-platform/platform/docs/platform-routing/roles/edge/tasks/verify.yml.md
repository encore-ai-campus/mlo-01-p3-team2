# roles/edge/tasks/verify.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/verify.yml)

nginx -t, openssl의 IP SAN 일치·잔여1시간 이상, 로컬443에 대한 시스템 CA·EIP 이름 검증 TLS 연결, HTTP 일반 경로는 edge_http_redirect=true이면 308(따라가지 않음), 그 외404, 갱신 timer active를 검사한다. Front 앱 동작이나 외부 사용자 접속 성공은 별도 검증이다.
