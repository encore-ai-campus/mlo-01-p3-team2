# 플랫폼 스크립트 지도

[탐색 시작점](../../ROUTING-README.md) · [원본 폴더](../../../scripts)

로컬 접속 준비와 프록시 준비의 시작 파일을 선택하는 문서다. DB·Kafka·Spark 서비스 설치는 [site.yml](../site.yml.md)의 역할별 실행으로 이어진다.

| 파일 | 실행 위치 | 역할과 다음 문서 |
| --- | --- | --- |
| [setup-team-access.sh](setup-team-access.sh.md) | 운영 PC의 WSL 또는 Linux Ansible 환경 | 준비된 Endpoint·AWS 프로필과 원본 인벤토리로 프로젝트 SSH 설정·접속용 인벤토리를 생성하고 배스천 SSH·프라이빗 서버 ping을 확인한다. 도구 설치와 AWS 자원 생성은 실행하지 않는다. |
| [setup-proxy.sh](setup-proxy.sh.md) | 운영 PC의 WSL 또는 Ansible 컨트롤 노드 | 인벤토리·limit·선택적 가상환경을 받아 문법·SSH 확인 → 배스천 Squid → 배스천 APT·방화벽 → 클라이언트 APT·접속 검사 순서로 실행한다. |
| [install-squid.sh](install-squid.sh.md) | Ubuntu 배스천 EC2, root 권한 | Squid 패키지만 설치한다. 프로젝트 ACL·수신 포트 관리는 [bootstrap-proxy.yml](../bootstrap-proxy.yml.md)이 맡는다. |

Windows의 [구성별 배포 실행기](../../../../../aws-infra/docs/infra-routing/scripts/deploy.ps1.md)는 Proxy 동작에서 WSL의 setup-proxy.sh를 호출한다. EC2 생성은 인프라 단계, 프록시 준비는 위 스크립트, 서비스 설치는 site.yml로 나뉜다. 환경변수만 지정했다고 설치 역할이 실행되지는 않는다.

스크립트를 수정하면 옵션·대상·중단 조건은 파일별 문서에 반영하고, 관련 playbook 또는 역할 문서도 함께 확인한다. 이 지도는 정적 코드 탐색 안내이며 실제 원격 실행 성공을 뜻하지 않는다.
