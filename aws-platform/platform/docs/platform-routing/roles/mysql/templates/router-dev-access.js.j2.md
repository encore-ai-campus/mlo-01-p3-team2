# Router 클라이언트 dev 계정 추가

[원본 파일](../../../../../roles/mysql/templates/router-dev-access.js.j2) · [계정 준비](../tasks/router-access.yml.md)

mysql_router_hosts의 출처 IP마다 dev 계정 존재 여부를 조회한다. 기존 계정은 비밀번호·권한을 바꾸지 않는다. 없는 계정에만 기존 mysql_dev_privileges와 시스템 스키마 부분 revoke 정책을 적용하고 INFRA_ROUTER_DEV_CREATED를 출력한다. root·failover·복제·monitor 계정을 생성하지 않는다.

router-access.yml의 입력 검사·단일 Primary 확인 후에만 실행한다. 앱의 DB 접속 URL과 연결 풀은 변경하지 않는다.
