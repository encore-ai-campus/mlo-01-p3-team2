# java: Java 17 설치

[탐색 시작점](../../../ROUTING-README.md) · [역할 목록](../README.md) · [최상위 playbook](../../site.yml.md)

## 진입점과 대상

Kafka·ZooKeeper·Spark의 meta/main.yml이 의존한다.

Corretto 패키지명·JAVA_HOME·저장소를 수정할 때 찾는다.

## 현재 작업 흐름

OS 변수 → Ubuntu Corretto 저장소 → pkg/install → Java 버전 확인

## 구현 조건

Java 버전 문자열에 17.이 있는지 검사한다. Java 관련 설정을 바꾸면 의존하는 세 역할도 대조한다.

## 경로별 문서

| 소스 경로 | 대응 문서 | 책임 |
| --- | --- | --- |
| roles/java/defaults/main.yml | [main.yml](defaults/main.yml.md) | Java 17 설치의 기본 변수다. 인벤토리 또는 실행 변수에서 조정할 값을 찾는다. |
| roles/java/tasks/main.yml | [main.yml](tasks/main.yml.md) | OS별 Corretto 패키지를 설치하고 java -version의 17. 문자열을 확인한다. |
| roles/java/vars/amazon.yml | [amazon.yml](vars/amazon.yml.md) | Amazon Linux에서 사용할 Java 17 설치의 패키지·서비스·경로 등 역할 변수를 지정한다. |
| roles/java/vars/ubuntu.yml | [ubuntu.yml](vars/ubuntu.yml.md) | Ubuntu에서 사용할 Java 17 설치의 패키지·서비스·경로 등 역할 변수를 지정한다. |

## 검증과 갱신

현재 선언과 참조를 정적으로 대조했다. verify 작업 문서는 구현된 검사 내용을 설명하며 이번 작업에서 서버 검사를 실행했다는 뜻은 아니다. 파일 추가·이동·삭제 시 이 목록과 같은 상대경로의 파일별 문서를 함께 갱신한다.
