#!/usr/bin/env bash
set -euo pipefail
# 이 스크립트의 인벤토리만 사용하고 기존 hosts.yml에는 쓰지 않는다.
mode=${1:?front 또는 install}
platform=${2:?platform 경로}
inventory=${3:?테스트 인벤토리}
venv=${4:?Ansible 가상환경}
input=${5:-}
root=$(cd -- "$(dirname -- "$0")" && pwd)
[[ "$venv" != '~/'* ]] || venv="$HOME/${venv:2}"
source "$venv/bin/activate"
export ANSIBLE_CONFIG="$platform/ansible.cfg"
export ANSIBLE_ROLES_PATH="$platform/roles"
unset ANSIBLE_INVENTORY ANSIBLE_VAULT_PASSWORD_FILE
cd "$root"
# 기존 환경 인벤토리 오지정을 로컬에서 차단한다.
python - "$inventory" <<'PY'
import json,sys
inv=json.load(open(sys.argv[1]))
assert inv['all']['vars']['test_project']=='aws-infra-test', '테스트 인벤토리가 아닙니다'
assert len(inv['all']['children']['frontend']['hosts'])==1
PY
if [[ "$mode" == front ]]; then
  extra=()
  if [[ -n "$input" ]]; then
    [[ -d "$input" ]] || { echo '정적 파일 폴더가 없습니다' >&2; exit 2; }
    # 경로의 공백과 따옴표를 JSON 인자로 안전하게 전달한다.
    extra=(-e "$(python -c 'import json,sys; print(json.dumps({"test_static_source":sys.argv[1]}))' "$input")")
  fi
  ansible-playbook -i "$inventory" front.yml "${extra[@]}"
elif [[ "$mode" == install ]]; then
  [[ -f "$input" ]] || { echo '테스트 Vault 파일이 필요합니다' >&2; exit 2; }
  vault_args=(-e "@$input")
  if head -n 1 "$input" | grep -q '^\$ANSIBLE_VAULT;'; then vault_args+=(--ask-vault-pass); fi
  # 한 프로세스에서 설치하므로 암호화된 Vault 비밀번호도 한 번만 묻는다.
  ansible-playbook -i "$inventory" clusters.yml -e @vars/small.yml "${vault_args[@]}"
else
  echo '지원하지 않는 동작입니다' >&2; exit 2
fi
