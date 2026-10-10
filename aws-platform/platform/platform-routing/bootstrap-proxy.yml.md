# bootstrap-proxy.yml

[탐색 시작점](ROUTING-README.md) · [원본](../bootstrap-proxy.yml) · [실행 스크립트](scripts/setup-proxy.sh.md)

## 역할

인벤토리의 bastion 그룹 한 대에 Squid를 준비한다. proxy_enabled, proxy_port, proxy_client_cidrs를 읽으며 IP나 계정 번호를 고정하지 않는다.

become=true, gather_facts=false, any_errors_fatal=true로 실행한다. [프록시 변수](inventory/group_vars/all/proxy.yml.md)의 proxy_enabled=true가 필수이며, 비활성 입력을 생략하지 않고 assert에서 실패 처리한다. 이 playbook은 site.yml에 import되지 않는다. [실행 스크립트](scripts/setup-proxy.sh.md)가 별도로 먼저 호출한다.

Squid 실행 파일 /usr/sbin/squid가 없으면 기존 [배스천 설치기](../scripts/install-squid.sh)를 Ansible script 모듈로 실행한다. 설치기는 Ubuntu 24.04 amd64와 공식 HTTPS 저장소를 대상으로 한다. 실행 파일이 이미 있으면 설치기와 그 안의 OS·설치 후보 검사를 생략하며 Squid 패키지를 자동 업그레이드하지 않는다.

## 설정 순서와 복구

현재 squid.conf를 메모리에 보관하고 주설정 파일에 http_access deny all 행이 정확히 하나인지 확인한다. 과거 수동으로 추가한 project_ec2 ACL·allow 행만 제거한 뒤 ANSIBLE PLATFORM PROXY 블록을 해당 거부 행 앞에 넣는다. 거부 행이 다른 모든 접근 규칙보다 뒤에 있는지까지 검사하지는 않는다. 다른 사용자 규칙을 일괄 삭제하지 않는다.

관리 블록의 platform_proxy_clients는 선택한 VPC CIDR을 허용한다. 수신 포트를 선택한 proxy_port로 맞추고 squid -k parse가 성공해야 서비스를 시작·재시작한다. 설정이 바뀐 경우만 재시작하며 부팅 시 자동 시작을 활성화한다.

설정 적용 블록이 실패하면 rescue에서 보관한 squid.conf 복원과 서비스 재시작을 시도하고, 두 작업이 끝나도 fail 작업으로 실행을 실패 처리한다. 설치·설정 보관·거부 규칙 검사는 이 블록 밖에 있어 해당 단계의 실패에는 이 rescue가 실행되지 않는다. 파일 편집 모듈의 backup도 사용한다. Squid 최초 설치 자체를 제거하거나 앞선 Terraform 변경을 되돌리는 복구는 아니다.

기존 include 파일의 별도 차단·허용 정책은 유지된다. 이 playbook의 문법 검사는 ACL의 의미까지 보장하지 않으므로 [클라이언트 HTTPS·다운로드 검사](prepare-proxy.yml.md)를 이어서 수행한다.

## 작업 탐색

아래 행은 현재 원본 bootstrap-proxy.yml 기준이다. CIDR 검사는 목록이 비어 있지 않은지까지만 확인하며 각 CIDR의 유효성을 별도로 파싱하지 않는다.

| 원본 행 | 작업 이름 | 모듈/제어와 책임 |
| --- | --- | --- |
| 9 | 프록시 입력 확인 | assert: proxy_enabled 활성화, bastion 1대, CIDR 목록 존재, 포트 1~65535를 검사한다. |
| 17 | Ubuntu 공식 HTTPS 저장소에서 Squid 최초 설치 | script: playbook_dir 기준 설치기를 호출하며 creates=/usr/sbin/squid이면 생략한다. |
| 22 | 변경 전 Squid 설정 보관 | slurp: /etc/squid/squid.conf를 proxy_squid_before에 보관한다. 최초 설치가 수행됐다면 설치 이후 내용이다. |
| 27 | 기본 접근 거부 규칙 확인 | assert: 보관한 주설정 파일에서 deny all 행이 정확히 하나인지 검사한다. |
| 33 | 프록시 설정 적용 | block/rescue: 아래 편집·문법 검사·서비스 작업에 대한 복구 범위를 정한다. |
| 36 | 기존 project_ec2 수동 규칙 정리 | replace: project_ec2의 src ACL·allow 행을 제거하고 변경 여부를 기록한다. |
| 44 | 프로젝트 VPC 접근을 최종 거부 규칙 앞에 배치 | blockinfile: ANSIBLE PLATFORM PROXY 관리 블록에 CIDR ACL과 allow를 작성한다. |
| 55 | 프록시 수신 포트 지정 | lineinfile: http_port 행을 proxy_port 값으로 설정하고 변경 여부를 기록한다. |
| 63 | 서비스에 적용하기 전 Squid 문법 검사 | command: /usr/sbin/squid -k parse, changed_when=false다. 실패하면 rescue로 진입한다. |
| 68 | Squid 실행과 부팅 시 시작 설정 | systemd_service: enabled=true. 수동 규칙·ACL·포트 중 변경이 있으면 restarted, 없으면 started다. |
| 74 | 실패한 설정을 변경 전 내용으로 복원 | rescue/copy: 보관한 내용을 root:root, 0644로 복원한다. |
| 82 | 복원한 설정으로 Squid 재시작 | rescue/systemd_service: 복원한 설정의 서비스 재시작을 시도한다. |
| 87 | 이후 배포 중단 | rescue/fail: 복구 후에도 실패를 알려 호출 스크립트의 다음 단계를 중단한다. |

이 playbook만 실행하면 APT 클라이언트 설정·배스천 방화벽·HTTPS 다운로드 검사는 실행하지 않는다. 이어지는 순서는 실행 스크립트의 [단계별 연결](scripts/setup-proxy.sh.md#코드-위치와-단계별-연결), 실제 검증 범위는 [검증 기록](verification.md)을 확인한다.
