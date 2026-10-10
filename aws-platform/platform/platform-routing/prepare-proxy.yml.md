# prepare-proxy.yml

[탐색 시작점](ROUTING-README.md) · [실행 안내](../README.md) · [원본 파일](../prepare-proxy.yml)

## 역할

proxy_enabled를 켠 인벤토리에서 첫 패키지 설치 전에 Ubuntu 저장소와 APT 프록시를 준비한다. 모든 대상의 root 권한으로 실행하며 서비스 설치 역할은 호출하지 않는다. 비활성 인벤토리는 작업 블록을 생략한다.

## 실행 흐름

배스천 1대·포트·CIDR 검사 → OS 정보 수집 → Ubuntu 24.04 amd64와 기본 ubuntu.sources 확인 → 공식 URI만 HTTPS로 전환·백업 → 남은 HTTP URI 검사 → APT 프록시 파일 → HTTPS HEAD·임시 파일 다운로드 → APT 목록 갱신.

ubuntu.sources의 Components, Suites, Signed-By와 다른 저장소 파일은 보존한다. /etc/apt/apt.conf.d/90-project-proxy는 배스천에 DIRECT, 나머지 대상에 계산된 프록시 주소를 지정한다. 알 수 없는 HTTP URI는 자동 전환하지 않고 오류로 알린다. check 모드에서는 실제 변경 후 검사와 외부 다운로드를 생략한다.

Squid 설치·설정은 이 playbook에 없다. 배스천의 프록시가 준비된 상태를 전제로 클라이언트의 저장소와 접속을 구성한다. gather_facts=false로 시작하고 활성 블록에서만 최소 OS 정보를 수집한다. any_errors_fatal=true이므로 한 대상의 실패도 이후 진행에 영향을 준다.

## 작업 위치와 조건

아래 행은 현재 prepare-proxy.yml 기준이다. 모든 하위 작업에는 proxy_enabled 활성 조건이 적용된다.

| 원본 행 | 작업 | 책임과 직접 조건 |
| --- | --- | --- |
| 14 | 배스천과 프록시 입력 확인 | 배스천 1대, 포트 1~65535, 비어 있지 않은 CIDR 목록과 배스천 ip 정의를 검사한다. proxy_verify에도 포함한다. |
| 24 | OS 정보 수집 | setup의 gather_subset=min으로 OS 사실을 수집한다. |
| 28 | 지원하는 기본 Ubuntu 이미지 확인 | Ubuntu 24.04, x86_64인지 확인한다. |
| 36, 41 | 기본 저장소 파일 확인·검사 | /etc/apt/sources.list.d/ubuntu.sources가 일반 파일인지 확인한다. |
| 47 | Ubuntu 공식 저장소를 HTTPS로 전환 | archive.ubuntu.com 계열의 단일 URI 행을 https://archive.ubuntu.com/ubuntu/로 정규화하고 security.ubuntu.com의 HTTP URI를 HTTPS로 바꾼다. 변경 시 backup=true다. |
| 61, 66 | 저장소 읽기·남은 HTTP 검사 | URI 행 존재와 HTTP 주소 부재를 검사한다. 적용 후 검사는 check 모드에서 생략한다. |
| 75 | APT 전용 프록시 설정 | root:root, 0644로 90-project-proxy를 작성한다. |
| 86, 90 | HTTPS 연결 검사 | check 모드에서 생략한다. HEAD 응답 200, timeout=20, use_proxy=proxy_is_client를 사용한다. |
| 98, 105 | 임시 파일·서명 목록 다운로드 | root로 강제 다운로드한다. timeout=20, 파일 mode=0600이며 changed_when=false다. |
| 115 | 임시 파일 정리 | always 블록에서 파일 경로가 정의되어 있으면 삭제한다. |
| 122 | APT 목록 갱신 | update_cache=true, lock_timeout=300, update_cache_retries=2다. |

저장소 전환 정규식은 한 행에 공식 URI 하나가 있는 형태를 대상으로 한다. URI 목록이나 사용자 정의 주소를 모두 HTTPS로 바꾸는 구현은 아니다. CIDR 입력 검사도 목록의 존재 여부까지만 확인하며 각 CIDR의 유효성을 별도로 파싱하지 않는다.

## 입력과 태그

| 항목 | 책임 |
| --- | --- |
| proxy_enabled | 인벤토리에서 명시적으로 활성화한다. 미지정 시 false다. |
| proxy_environment | 원격 작업의 HTTP/HTTPS 환경변수다. |
| proxy_bastion_host / proxy_url / proxy_is_client | 배스천과 직접·프록시 연결 대상을 결정한다. |
| proxy_check_url / proxy_check_download_url | HTTPS HEAD와 파일 다운로드 검사 주소다. |
| proxy | 준비 플레이의 전체 작업 태그다. |
| proxy_verify | 구성 입력과 HTTPS·다운로드 검사만 실행한다. APT 설정과 목록은 변경하지 않는다. |

proxy_verify만 선택하면 OS 정보 수집·지원 OS 확인·저장소 전환·APT 설정·APT 목록 갱신은 실행 대상에서 제외된다. 프록시 준비 후 연결을 다시 검사하는 용도로 사용한다. check 모드에서는 이 태그의 외부 연결·다운로드 블록도 생략하므로 실제 접속 성공을 확인한 것으로 해석하지 않는다.

## 연결과 검증

- [프록시 변수](inventory/group_vars/all/proxy.yml.md)
- [최상위 실행](site.yml.md)
- [배스천 프록시 허용 규칙](roles/firewall/templates/infra-fw.nft.j2.md)

원격 파일 다운로드는 become 환경에서 수행하며 임시 파일은 always 블록으로 정리한다. 실제 문법 검사와 EC2 적용 결과는 [검증 기록](verification.md)의 이번 변경 상태를 확인한다.
