# roles/edge/tasks/main.yml

Front 모드(edge_frontend_mode=true)에서는 전달 대상이 정확히 하나인지 설치 전에 검사한다. 발급·갱신은 각 호스트의 edge_public_ip·edge_cert_name을 사용하므로 두 Front가 인증서를 공유하지 않는다.

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/main.yml)

입력 검증 → 공식 HTTPS APT 준비 → Nginx·venv·python3-packaging 설치 → Certbot 고정 버전 설치 → HTTP 검증 경로 시작 → 최초 staging dry-run → 운영 IP 인증서 발급 또는 유지 → HTTPS 설정 → 갱신 서비스·타이머 → verify 순서다. 인증서가 이미 있으면 초기 설정에서도 HTTPS를 유지한다. 전체 nginx.conf를 관리하므로 진입 전용 서버에 실행한다.
