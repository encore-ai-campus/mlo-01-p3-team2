# scripts/install-squid.sh

[탐색 시작점](../ROUTING-README.md) · [원본 스크립트](../../scripts/install-squid.sh) · [배스천 준비](../bootstrap-proxy.yml.md)

## 역할과 입력

Bastion EC2에서 수동 실행하는 Squid 패키지 설치 스크립트다. 인수 없이 sudo bash install-squid.sh로 실행한다. Bash의 set -euo pipefail로 오류 시 중단하며 root·Ubuntu 24.04·amd64·CA 인증서·Ubuntu archive 서명 키를 확인한다.

Terraform user_data나 bastion.ps1의 Create가 이 스크립트를 자동 실행하지 않는다.

## 주요 처리 위치

| 위치 | 처리 |
| --- | --- |
| fail | 한국어 오류를 stderr로 출력하고 종료 코드 1로 중단 |
| 실행 조건 검사 | 인수·root·OS 버전·CPU 아키텍처·인증서·서명 키 검사 |
| minimum_version | Squid 최소 버전 6.14-0ubuntu0.24.04.4를 코드 상수로 사용 |
| proxy_tmp / trap | /tmp에 임시 APT 저장소·목록·캐시를 만들고 종료 시 해당 임시 폴더 제거 |
| ubuntu.sources / apt_options | Ubuntu 공식 HTTPS 저장소의 noble·noble-updates·noble-security main 사용. 기존 /etc/apt와 기본 패키지 목록은 수정하지 않음 |
| candidate_version 검사 | 후보 존재·6 계열·최소 버전 이상인지 확인 |
| apt-get install | 후보 버전의 Squid와 필요한 의존성만 설치. 전체 패키지 업그레이드는 하지 않음 |
| dpkg-query | 설치된 Squid 패키지 버전 출력 |

공식 저장소의 HTTPS를 사용해 Bastion 외부 TCP 443 egress 범위에 맞춘다. minimum_version은 현재 코드의 설치 기준이며 최신 배포판 버전이나 보안 상태를 외부에서 조회해 검증한 값은 아니다.

## 변경하지 않는 범위

Squid 접근 ACL·인증·방화벽·클라이언트 환경변수·프록시 주소는 설정하지 않는다. 다른 EC2에서 TCP 3128로 사용할 수 있는지나 실제 인터넷 송신도 검사하지 않는다. 패키지 설치에 따른 기본 서비스 동작과 팀의 Proxy 정책 설정은 구분한다.

이 문서는 Bash 원본의 정적 대조 결과다. 이번 문서 작업에서 설치를 실행하거나 AWS 자원을 변경하지 않았다. Bastion을 삭제하면 설치된 OS도 사라지므로 재생성 후 다시 설치하고 ACL·클라이언트 주소를 준비해야 한다.
