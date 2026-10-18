# roles/edge/tasks/domain-certificate.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/domain-certificate.yml)

edge_domain이 있을 때 main.yml에서 호출한다. Certbot webroot·-d 도메인·도메인과 같은 cert-name·keep-until-expiring을 구성한다. 최초 인증서가 없고 preflight가 켜져 있으면 dry-run을 먼저 실행하고 운영 발급·기존 인증서 유지를 수행한다. 발급 파일 존재를 확인한 뒤 edge_domain_tls_ready=true로 최종 Nginx 도메인 서버를 활성화한다. DNS A 레코드·HTTP ACME 경로·앱 배포는 사전 조건이다. IP 인증서는 main.yml에서 별도로 유지한다.
