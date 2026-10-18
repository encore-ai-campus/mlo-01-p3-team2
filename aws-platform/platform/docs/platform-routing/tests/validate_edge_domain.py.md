# validate_edge_domain.py

[원본](../../../tests/validate_edge_domain.py) · [edge 역할](../roles/edge/README.md)

로컬 Jinja2·PyYAML 환경에서 게임 도메인 경로·허용 CIDR, 최초 인증서 없음, 기존 IP 인증서만 있는 전환, 광고 IP 동작, 두 인증서 갱신, 역할 YAML 파싱의 6개 검사를 실행한다. 원격 Nginx·인증서 발급·DNS·로그인 검증은 하지 않는다.

실행: 플랫폼 디렉터리에서 `python tests/validate_edge_domain.py`. PowerShell 인벤토리 분기는 `aws-infra/infra/tests/test_front_domain.ps1`로 별도 검사한다.
