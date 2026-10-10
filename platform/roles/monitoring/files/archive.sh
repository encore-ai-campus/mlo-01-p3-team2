#!/bin/bash
# 일 단위 정리 (roles/monitoring). 하루 지난 파일은 압축 복사해 보관 폴더에 두고, 수집 폴더의 원본은 COLLECT_KEEP_DAYS일 뒤,
# 보관 폴더의 파일은 ARCHIVE_KEEP_DAYS일 뒤 지운다. 이동이 아니라 복사인 이유: 서버에 아직 남은 파일을 rsync가 다시 가져오기 때문이다.
set -u
. /etc/infra-monitor/monitor.conf   # DATA_DIR ARCHIVE_DIR COLLECT_KEEP_DAYS ARCHIVE_KEEP_DAYS
cd "$DATA_DIR" || exit 1

for area in metrics logs; do
  [ -d "$area" ] || continue
  find "$area" -type f -mmin +1440 ! -name '*.gz' -print0 | while IFS= read -r -d '' f; do
    rest=${f#*/}                      # <서버>/<경로>
    dest="$ARCHIVE_DIR/${rest%%/*}/$area/${rest#*/}.gz"
    # 아직 없거나, 압축한 뒤에 원본이 바뀐 경우만 다시 압축한다.
    if [ ! -e "$dest" ] || [ "$f" -nt "$dest" ]; then
      mkdir -p "$(dirname "$dest")"
      gzip -c "$f" > "$dest.tmp" && touch -r "$f" "$dest.tmp" && mv "$dest.tmp" "$dest"
    fi
  done
  find "$area" -type f -mmin +$((COLLECT_KEEP_DAYS * 1440)) -delete
done

[ -d "$ARCHIVE_DIR" ] && find "$ARCHIVE_DIR" -type f -mmin +$((ARCHIVE_KEEP_DAYS * 1440)) -delete
exit 0
