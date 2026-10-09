# zookeeper: Spark 복구용 ZooKeeper ensemble

[탐색 시작점](../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

기본 zookeeper_group=spark. site.yml이 Spark 역할보다 먼저 실행한다.

ensemble 멤버·포트·4글자 명령·Spark 복구 저장소를 수정할 때 찾는다.

## 현재 작업 흐름

myid·사용자 → sha512 배포 → myid·zoo.cfg·logback·unit → 시작 → ruok·Mode·ensemble 검증

## 구현 조건

Kafka용 ZooKeeper가 아니다. 서버 이름 끝 숫자를 myid로 사용한다. 내장 관리 서버는 Spark Master UI 8080과 겹치므로 끈다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/zookeeper/defaults/main.yml | [main.yml](defaults/main.yml.md) | Spark 복구용 ZooKeeper ensemble의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/zookeeper/meta/main.yml | [main.yml](meta/main.yml.md) | Ansible 역할 의존성으로 Java 역할을 선언한다. |
| roles/zookeeper/tasks/main.yml | [main.yml](tasks/main.yml.md) | 호스트명 기반 myid, 다운로드·데이터·설정·logback·unit과 시작·검증을 연결한다. |
| roles/zookeeper/tasks/verify.yml | [verify.yml](tasks/verify.yml.md) | ruok=imok, 각 노드 Mode, ensemble leader 하나와 나머지 follower를 확인한다. |
| roles/zookeeper/templates/logback.xml.j2 | [logback.xml.j2](templates/logback.xml.j2.md) | ZooKeeper INFO 로그를 zookeeper.log 하나에 기록한다. monitoring이 회전을 담당한다. |
| roles/zookeeper/templates/zoo.cfg.j2 | [zoo.cfg.j2](templates/zoo.cfg.j2.md) | 클라이언트·멤버 포트, 4글자 명령 허용과 스냅샷 정리를 설정하고 내장 관리 서버를 끈다. |
| roles/zookeeper/templates/zookeeper.service.j2 | [zookeeper.service.j2](templates/zookeeper.service.j2.md) | Java·ZOOCFGDIR·heap 환경으로 ZooKeeper를 foreground 실행한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
