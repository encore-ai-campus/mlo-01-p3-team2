#!/usr/bin/env bash
set -euo pipefail

# 개인키는 저장소 밖에 둔다. 인수는 키 파일의 전체 경로다.
if [[ $# -ne 1 ]]; then
  printf '사용법: bash prepare-key.sh "$HOME/.ssh/aws-infra-team"\n' >&2
  exit 1
fi
key_path="$1"
key_directory="$(dirname "$key_path")"
# 이미 있는 상위 폴더의 권한은 바꾸지 않는다.
if [[ ! -d "$key_directory" ]]; then
  mkdir -p "$key_directory"
  chmod 700 "$key_directory"
fi
if [[ -e "$key_path" ]]; then
  # 기존 개인키를 덮어쓰지 않는다. 암호가 있으면 ssh-keygen이 직접 묻는다.
  printf '기존 키 재사용: %s\n' "$key_path" >&2
else
  ssh-keygen -t rsa -b 4096 -C aws-infra-team -f "$key_path"
fi
chmod 600 "$key_path"
# 공개키가 없는 경우에만 복구한다. 개인키 내용은 출력하지 않는다.
if [[ ! -f "$key_path.pub" ]]; then
  ssh-keygen -y -f "$key_path" > "$key_path.pub"
fi
chmod 644 "$key_path.pub"
printf 'Terraform에 등록할 공개키 경로: %s.pub\n' "$key_path"
