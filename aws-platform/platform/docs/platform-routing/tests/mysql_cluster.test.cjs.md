# tests/mysql_cluster.test.cjs

[탐색 시작점](../../ROUTING-README.md) · [테스트 안내](README.md) · [원본 파일](../../../tests/mysql_cluster.test.cjs)

## 책임

validate_mysql_cluster.py가 만든 실제 렌더링 결과를 Node vm에서 실행한다. AdminAPI·SQL 세션만 모의 객체로 제공하여 신규 Cluster 생성·clone 가입, 정상 재실행, 실제 Primary 변경, 누락 멤버 추가·증분 재가입, 복구 중 대기, ReplicaSet/인증 오류/정족수 상실/다중 Primary/관리되지 않는 GR/예상 밖 멤버/ERROR 거부를 확인한다. clone 데이터 보호와 명시적 허용, 문자열 false의 보호 유지, 기존 메타데이터 보호도 검사한다. 인스턴스 사전 구성과 Router 계정의 출처·갱신을 포함해 27개 시나리오다.

사전 구성 모의 검사는 root 계정 접속을 거부하고 scheme=mysql·failover 계정·Vault의 가짜 관리 비밀번호·사설 IP·3306 포트·socket 미사용을 확인한다. 정상 설정이면 재구성을 생략하고, 설정이 부족하면 검사에 사용한 접속 정보를 configureInstance에 그대로 전달하며 restart=true를 지정하는지 확인한다. 기존 27개 시나리오 중 사전 구성 2개의 검사를 보강했다.

실행은 [Python 실행기](validate_mysql_cluster.py.md)를 사용한다. JavaScript는 routing-doc-sync의 Python AST 자동 검사 대상이 아니며 실제 MySQL Shell API 동작은 배포 환경에서 확인해야 한다.
