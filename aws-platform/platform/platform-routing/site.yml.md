# site.yml

[탐색 시작점](ROUTING-README.md) · [원본 파일](../site.yml)

## 역할

프록시 준비 playbook을 먼저 import한 뒤 Bastion 우선 공통 보안·방화벽, 서비스 역할, 마지막 모니터링 순서로 실행하는 최상위 playbook이다. 각 서비스·공통 play는 proxy_environment를 원격 작업 환경으로 선언한다. 개별 작업의 environment 선언과 실제 상속·병합 결과는 이번 문서 작업에서 실행 검증하지 않았다.

3행의 import_playbook 자체에는 when 조건이 없다. prepare-proxy.yml을 정적으로 포함하고, 포함된 작업 블록이 proxy_enabled 조건으로 실행 여부를 결정한다. 비활성 인벤토리에서는 준비 블록을 생략하고 proxy_environment는 빈 사전이다.

## 작업 탐색

행 번호와 이름은 원본 작업 순서다. 조건 열은 해당 작업에 직접 선언된 when의 단서이며 상위 block, play, include_role 조건은 별도로 적용된다. 목록·여러 줄 조건과 명령 인자는 원본에서 확인한다.

| 원본 행 | 작업 이름 | 모듈/제어 | 명시된 값 | 조건 단서 |
| --- | --- | --- | --- | --- |
| 3 | 프록시 준비 import | ansible.builtin.import_playbook | prepare-proxy.yml | import는 무조건 포함; 준비 블록 내부의 proxy_enabled 조건 |
| 6 | 공통 보안 (Bastion) | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 14 | 공통 보안 (나머지 서버) | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 22 | 방화벽 (Bastion) | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 30 | 방화벽 (나머지 서버) | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 37 | MySQL | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 44 | MongoDB | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 51 | Kafka | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 59 | ZooKeeper와 Spark | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 68 | Backend | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |
| 76 | Monitoring | play | 아래 작업·인자 참조 | 상위 block/play 조건도 확인 |

## play 연결

| 대상 | 역할 순서 |
| --- | --- |
| all (proxy_enabled) | prepare-proxy → HTTPS 저장소·APT 프록시·연결 검사 |
| bastion / all:!bastion | common → firewall (각 단계에서 Bastion 먼저) |
| mysql | mysql |
| mongodb | mongodb |
| kafka | java 의존성 → kafka |
| spark | zookeeper → spark (각 역할의 java 의존성 선행) |
| backend | backend |
| all (monitoring 그룹 존재 시) | monitoring |

Bastion의 common/firewall play에는 any_errors_fatal=true가 있다. Frontend는 별도 설치 play가 없으며 공통 보안·방화벽·모니터링 대상에 포함된다.

ZooKeeper와 Spark는 같은 play에 있지만 역할 태그는 각각 zookeeper와 spark다. zookeeper 태그만 선택한 실행은 Spark 역할의 설치·unit 배포·시작을 포함하지 않는다. common 또는 프록시 준비만 실행한 경우에도 DB·Kafka·Spark 역할 설치 완료를 뜻하지 않는다. Spark 설치 연결은 [tasks/main.yml](roles/spark/tasks/main.yml.md), 설치 후 검사는 [tasks/verify.yml](roles/spark/tasks/verify.yml.md)에서 확인한다.

## 프록시 연결 문서

- [첫 설치 전 준비 작업](prepare-proxy.yml.md)
- [proxy_environment와 공통 변수](inventory/group_vars/all/proxy.yml.md)
- [배스천 방화벽의 프록시 허용](roles/firewall/templates/infra-fw.nft.j2.md)

firewall 등의 역할 태그만 선택하면 앞선 프록시 준비 작업이 선택되지 않을 수 있으므로 해당 서버에서 준비 절차를 먼저 수행한다. 원격 environment는 패키지 설치와 파일 다운로드를 수행하는 대상 서버 작업의 선언이며 실행 PC의 프록시 설정을 바꾸는 작업은 아니다.

## 검증 범위

이 문서는 현재 작업 파일의 선언·작업 이름·조건·참조를 대조했다. Ansible 실행, 템플릿 렌더링, 원격 서버 동작은 이번 문서 작업에서 검증하지 않았다. Python AST 스킬의 자동 심볼 검사는 이 파일 형식에 적용되지 않는다.
