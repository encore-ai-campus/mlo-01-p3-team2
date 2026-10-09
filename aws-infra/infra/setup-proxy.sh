#!/usr/bin/env bash
set -euo pipefail

# 배스천 EC2에서 실행한다: sudo bash setup-proxy.sh
# Ubuntu 24.04 amd64에 Squid 패키지만 설치한다. 프록시 허용 규칙과 방화벽은 설정하지 않는다.
fail() {
  printf '오류: %s\n' "$1" >&2
  exit 1
}

[[ $# -eq 0 ]] || fail '인수 없이 sudo bash setup-proxy.sh로 실행하세요.'
[[ $EUID -eq 0 ]] || fail 'sudo bash setup-proxy.sh로 실행하세요.'
[[ -r /etc/os-release ]] || fail 'EC2의 Ubuntu 24.04에서 실행하세요.'
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || fail 'Ubuntu 24.04만 지원합니다.'
[[ $(dpkg --print-architecture) == amd64 ]] || fail 'amd64(x86_64) EC2에서 실행하세요.'
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || fail 'HTTPS 저장소에 필요한 CA 인증서가 없습니다.'
[[ -s /usr/share/keyrings/ubuntu-archive-keyring.gpg ]] || fail 'Ubuntu 공식 저장소 서명 키가 없습니다.'

export LC_ALL=C
minimum_version='6.14-0ubuntu0.24.04.4'

# 배스천의 외부 443 허용에 맞춰 HTTPS 저장소를 이번 실행에서만 사용한다.
# 기존 /etc/apt의 저장소 설정과 기본 패키지 목록은 수정하지 않는다.
proxy_tmp=$(mktemp -d /tmp/setup-proxy.XXXXXX)
trap 'rm -rf -- "$proxy_tmp"' EXIT
mkdir -p "$proxy_tmp/sources.list.d" "$proxy_tmp/lists/partial"
chmod 755 "$proxy_tmp" "$proxy_tmp/sources.list.d" "$proxy_tmp/lists"
cat > "$proxy_tmp/ubuntu.sources" <<'SOURCES'
Types: deb
URIs: https://archive.ubuntu.com/ubuntu/
Suites: noble noble-updates
Components: main
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: https://security.ubuntu.com/ubuntu/
Suites: noble-security
Components: main
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SOURCES

# 동일한 임시 저장소와 캐시를 조회·설치에 사용해 기존 저장소의 후보와 섞이지 않게 한다.
apt_options=(
  -o "Dir::Etc::sourcelist=$proxy_tmp/ubuntu.sources"
  -o "Dir::Etc::sourceparts=$proxy_tmp/sources.list.d"
  -o "Dir::State::lists=$proxy_tmp/lists"
  -o "Dir::Cache::pkgcache=$proxy_tmp/pkgcache.bin"
  -o "Dir::Cache::srcpkgcache=$proxy_tmp/srcpkgcache.bin"
  -o 'DPkg::Lock::Timeout=300'
)

printf 'Ubuntu 공식 HTTPS 저장소에서 Squid 설치 정보를 확인합니다.\n'
apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
candidate_version=$(apt-cache "${apt_options[@]}" policy squid | awk '/^[[:space:]]*Candidate:/ { print $2 }')
[[ -n $candidate_version && $candidate_version != '(none)' ]] || fail 'Squid 설치 후보가 없습니다.'
[[ $candidate_version == 6.* ]] || fail "예상한 Squid 6 계열이 아닙니다: $candidate_version"
dpkg --compare-versions "$candidate_version" ge "$minimum_version" || fail "설치 후보가 최소 버전보다 낮습니다: $candidate_version"

# Squid와 필요한 의존성만 설치한다. 다른 패키지 전체를 업그레이드하지 않는다.
printf 'Squid 설치 버전: %s\n' "$candidate_version"
DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l \
  apt-get "${apt_options[@]}" install -y --no-install-recommends "squid=$candidate_version"

printf '\n설치된 Squid 패키지 버전: '
dpkg-query -W -f='${Version}\n' squid
printf '설치 완료. 다른 EC2에서 사용하려면 Squid 접근 허용과 TCP 3128 연결 설정이 필요합니다.\n'
