#!/usr/bin/env bash
set -euo pipefail

# WSL의 Ansible 가상환경에서 실행한다. 계정·IP·SSH 키는 인벤토리에서 읽는다.
inventory=''
limit='all'
venv=''
while (( $# > 0 )); do
  case "$1" in
    --inventory|--limit|--venv)
      if (( $# < 2 )) || [[ -z "$2" ]]; then
        printf '오류: %s 뒤에 값을 지정하세요.\n' "$1" >&2
        exit 2
      fi
      case "$1" in
        --inventory) inventory="$2" ;;
        --limit) limit="$2" ;;
        --venv) venv="$2" ;;
      esac
      shift 2
      ;;
    -h|--help)
      printf '사용법: bash setup-proxy.sh --inventory <파일> [--limit <호스트 또는 그룹>] [--venv <가상환경>]\n'
      printf '기본 대상: all. 배스천 설치·설정·방화벽은 --limit과 관계없이 먼저 준비합니다.\n'
      exit 0
      ;;
    *) printf '알 수 없는 옵션: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ "$limit" == -* ]]; then
  printf '오류: --limit에는 옵션이 아닌 호스트 또는 그룹 패턴을 지정하세요.\n' >&2
  exit 2
fi
if [[ -n "$venv" ]]; then
  if [[ "$venv" == "~/"* ]]; then venv="$HOME/${venv:2}"; fi
  if [[ ! -f "$venv/bin/activate" ]]; then
    printf '오류: Ansible 가상환경이 없습니다: %s\n' "$venv" >&2
    exit 1
  fi
  source "$venv/bin/activate"
fi
if [[ -z "$inventory" || ! -f "$inventory" ]]; then
  printf '오류: --inventory로 존재하는 인벤토리 파일을 지정하세요.\n' >&2
  exit 2
fi
for executable in ansible ansible-playbook; do
  if ! command -v "$executable" >/dev/null 2>&1; then
    printf '오류: %s가 없습니다. 설치한 Ansible 가상환경을 활성화하세요.\n' "$executable" >&2
    exit 1
  fi
done

# 실행 위치와 무관하게 프로젝트 설정을 읽는다. WSL의 Windows 마운트에서도 명시적으로 선택한다.
inventory="$(cd -- "$(dirname -- "$inventory")" && pwd)/$(basename -- "$inventory")"
platform_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd -- "$platform_dir"
export ANSIBLE_CONFIG="$platform_dir/ansible.cfg"
step='입력 확인'
trap 'status=$?; printf "\n실패: %s (종료 코드 %s). 이후 단계는 실행하지 않았습니다.\n" "$step" "$status" >&2; exit "$status"' ERR

# 오타로 대상이 0대인 경우를 성공으로 보고하지 않는다.
for pattern in bastion "$limit"; do
  listing="$(ANSIBLE_HOST_PATTERN_MISMATCH=error ansible -i "$inventory" "$pattern" --list-hosts)"
  printf '%s\n' "$listing"
  if grep -Eq '^[[:space:]]*hosts \(0\):' <<< "$listing"; then
    printf '오류: 대상이 없습니다: %s\n' "$pattern" >&2
    exit 1
  fi
done

step='1/6 문법 검사'
printf '\n%s\n' "$step"
for playbook in bootstrap-proxy.yml prepare-proxy.yml site.yml; do
  ansible-playbook -i "$inventory" "$platform_dir/$playbook" --syntax-check
done

step='2/6 SSH와 원격 Python 확인'
printf '\n%s\n' "$step"
ansible -i "$inventory" bastion -m ansible.builtin.wait_for_connection -a 'timeout=300'
ansible -i "$inventory" "$limit" -m ansible.builtin.wait_for_connection -a 'timeout=300'
ansible -i "$inventory" "$limit" -m ansible.builtin.ping

step='3/6 배스천 Squid와 APT 준비'
printf '\n%s\n' "$step"
ansible-playbook -i "$inventory" "$platform_dir/bootstrap-proxy.yml"
ansible-playbook -i "$inventory" "$platform_dir/prepare-proxy.yml" --limit bastion

step='4/6 배스천 방화벽 적용'
printf '\n%s\n' "$step"
ansible-playbook -i "$inventory" "$platform_dir/site.yml" --tags firewall --limit bastion

step='5/6 선택한 서버의 APT와 프록시 준비'
printf '\n%s\n' "$step"
ansible-playbook -i "$inventory" "$platform_dir/prepare-proxy.yml" --limit "$limit"

step='6/6 방화벽 적용 후 HTTPS와 다운로드 재확인'
printf '\n%s\n' "$step"
ansible-playbook -i "$inventory" "$platform_dir/prepare-proxy.yml" --tags proxy_verify --limit "$limit"
printf '\n프록시 준비 완료. 인벤토리: %s / 대상: %s\n' "$inventory" "$limit"
