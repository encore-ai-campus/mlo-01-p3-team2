#!/usr/bin/env bash
set -euo pipefail
# Terraform이 출력한 EBS ID와 일치하는 NVMe 장치만 사용한다. 기존 데이터는 덮어쓰지 않는다.
volume=${1:?volume id}
target=${2:?mount path}
[[ "$volume" =~ ^vol-[0-9a-f]+$ ]] || exit 2
case "$target" in /var/lib/mysql|/var/lib/mongodb|/var/lib/kafka/data|/var/lib/spark) ;; *) exit 2;; esac
serial=${volume//-/}
mapfile -t devices < <(lsblk -dn -o PATH,SERIAL | awk -v wanted="$serial" '$2==wanted { print $1 }')
[[ ${#devices[@]} == 1 ]] || { echo 'EBS 장치를 하나로 확정할 수 없습니다' >&2; exit 1; }
device=${devices[0]}
if mountpoint -q "$target"; then
  [[ $(findmnt -n -o MAJ:MIN --target "$target") == "$(lsblk -dn -o MAJ:MIN "$device")" ]] || exit 1
  exit 0
fi
[[ $(lsblk -nr -o NAME "$device" | wc -l) == 1 ]] || { echo '파티션이 있는 장치는 자동 포맷하지 않습니다' >&2; exit 1; }
[[ -z $(lsblk -dn -o MOUNTPOINTS "$device") ]] || exit 1
mkdir -p "$target"
[[ -z $(find "$target" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo '기존 데이터 경로는 자동 마운트하지 않습니다' >&2; exit 1; }
fstype=$(lsblk -dn -o FSTYPE "$device")
if [[ -z "$fstype" ]]; then
  [[ -z $(wipefs -n --noheadings -o TYPE "$device") ]] || exit 1
  mkfs.ext4 -m 0 "$device"
elif [[ "$fstype" != ext4 ]]; then
  echo 'ext4가 아닌 기존 장치는 변경하지 않습니다' >&2; exit 1
fi
uuid=$(blkid -s UUID -o value "$device")
[[ -n "$uuid" ]] || exit 1
if ! grep -q "^UUID=$uuid " /etc/fstab; then
  # UUID·경로 중복은 기존 마운트와 충돌하므로 중단한다.
  ! awk -v dest="$target" '$2==dest { found=1 } END { exit !found }' /etc/fstab || exit 1
  printf 'UUID=%s %s ext4 defaults 0 2\n' "$uuid" "$target" >> /etc/fstab
fi
mount "$target"
# ext4 생성 시 생긴 빈 lost+found가 MySQL의 빈 datadir 검사를 방해하지 않게 한다.
if [[ -d "$target/lost+found" ]]; then rmdir "$target/lost+found"; fi
