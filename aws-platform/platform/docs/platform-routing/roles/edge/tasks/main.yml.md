# roles/edge/tasks/main.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/main.yml)

입력 검증 → Ubuntu HTTPS 저장소·Nginx·Certbot 준비 → 기존 IP·도메인 인증서 조회 → 준비된 인증서만 사용하는 초기 nginx.conf → IP 인증서 dry-run·발급/유지 → 선택 [도메인 인증서 작업](domain-certificate.yml.md) → 최종 nginx.conf → 갱신 서비스·타이머 → verify 순서다.

Front 목적지는 하나이며 게임 도메인의 형식·동일 cert-name·Backend IP·포트·HTTP 이동을 검증한다. 도메인 모드도 IP 인증서를 유지해 경고 없는 IP→도메인 이동을 제공한다. nginx.conf 전체를 교체하므로 앱 경로를 템플릿에 반영해야 한다. 앱·정적 파일·DNS·환경 변수 배포는 수행하지 않는다. Deploy/Inventory만 실행해도 이 역할이 자동 적용되는 것은 아니다.
