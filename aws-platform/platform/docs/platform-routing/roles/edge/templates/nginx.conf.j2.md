# roles/edge/templates/nginx.conf.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/nginx.conf.j2)

HTTP80에서는 ACME 경로 외404를 반환한다. 인증서 준비 시에만 HTTPS443을 렌더링하며 CIDR allow/deny를 적용한다. 빈 Front 목록은 정적 준비 화면, 지정된 목록은 least_conn과 WebSocket 전달 설정이다. X-Forwarded-For는 신뢰하지 않은 입력 대신 실제 연결 IP로 새로 만든다.
