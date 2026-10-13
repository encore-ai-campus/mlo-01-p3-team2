#!/usr/bin/env bash
# 보안·품질 점검 일괄 실행. 하나라도 실패하면 비정상 종료한다.
#
#   scripts/check.sh              전체 실행
#   OFFLINE_OK=1 scripts/check.sh pip-audit 이 네트워크 문제로 못 돌면 건너뛴다(기본은 실패로 취급)
#   PYTHON=/path/to/python        사용할 파이썬(기본: python)
#
# 단계: MySQL·MongoDB 접속(없으면 명확히 실패 — 시험을 건너뛰지 않는다) → check --deploy(prod 샘플 환경) → 마이그레이션 최신 여부 → 전체 테스트(경계 검사·보안 회귀 포함)
#       → 부하 시험(소규모: MySQL·실제 HTTP·별도 처리 프로세스, 불변식) → pip-audit(의존성 취약점) → bandit(정적 보안 점검)
#       150 동시 전체 시험은 `python scripts/load_test.py`(약 40초, docs/ads-server/load-test.md)
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
failures=()
skipped=()

run() {
  local name="$1"; shift
  printf '\n==== %s ====\n' "$name"
  if "$@"; then printf 'OK   %s\n' "$name"; else printf 'FAIL %s\n' "$name"; failures+=("$name"); fi
}

check_deploy() {
  local key; key="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(60))')"
  eval "$("$PY" scripts/mysql_admin.py --print-env)"  # .env 의 DB_* (실제 환경변수가 우선)
  # MySQL 에서는 모델 검사가 서버 정보를 읽으려고 실제로 연결한다 → 시험 DB 접속 값(DB_*)을 그대로 넘긴다.
  env -i PATH="$PATH" DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY="$key" \
    ALLOWED_HOSTS=ads.example.com ADMIN_URL_PATH=ops-check/ \
    DB_NAME="${DB_NAME:-ads_server}" DB_USER="${DB_USER:-}" DB_PASSWORD="${DB_PASSWORD:-}" DB_HOST="${DB_HOST:-127.0.0.1}" DB_PORT="${DB_PORT:-3306}" \
    MEDIA_ROOT=/tmp/ads-check-media ASSET_PUBLIC_BASE_URL=https://ads.example.com TRUSTED_PROXY_COUNT=1 CSRF_TRUSTED_ORIGINS=https://ads.example.com \
    "$PY" -m django check --deploy --fail-level WARNING
}

audit_dependencies() {
  local tmp out rc; tmp="$(mktemp)"
  "$PY" scripts/pinned_requirements.py > "$tmp" || { echo "의존성 목록을 만들지 못했다"; return 1; }
  out="$("$PY" -m pip_audit --no-deps --disable-pip -r "$tmp" 2>&1)"; rc=$?
  rm -f "$tmp"; printf '%s\n' "$out"
  if [ $rc -eq 0 ]; then return 0; fi
  if printf '%s' "$out" | grep -qiE 'connection|max retries|temporary failure|name or service|timed out|resolve'; then
    if [ "${OFFLINE_OK:-0}" = "1" ]; then echo "SKIPPED: 네트워크 문제로 pip-audit 을 건너뜀(OFFLINE_OK=1)"; skipped+=("pip-audit"); return 0; fi
    echo "네트워크 문제로 pip-audit 을 실행하지 못했다(취약점 발견이 아님). 오프라인이면 OFFLINE_OK=1"
    return 2
  fi
  echo "취약점이 발견되었다"
  return 1
}

run "MySQL 접속 (시험 DB, 없으면 여기서 멈춘다)" "$PY" scripts/mysql_admin.py
run "MongoDB 접속 (이벤트 저장소 시험, 없으면 여기서 멈춘다)" "$PY" scripts/mongo_admin.py
if [ ${#failures[@]} -gt 0 ]; then printf '\n실패: %s\nDB 가 필요한 나머지 단계는 실행하지 않았습니다(README "MySQL 시험 환경"·"MongoDB 시험 환경").\n' "${failures[*]}"; exit 1; fi
run "check --deploy (prod 샘플 환경, 경고 0)" check_deploy
run "마이그레이션이 최신인가" "$PY" manage.py makemigrations --check --dry-run
run "전체 테스트 (경계 검사·보안 회귀 포함)" "$PY" manage.py test
run "부하 시험 (20 동시, 불변식)" "$PY" scripts/load_test.py --small
run "pip-audit (의존성 취약점)" audit_dependencies
run "bandit (정적 보안 점검)" "$PY" -m bandit -q -r config foundation console assets masters engine campaigns billing events records serving_api

printf '\n======== 요약 ========\n'
[ ${#skipped[@]} -gt 0 ] && printf '건너뜀: %s\n' "${skipped[*]}"
if [ ${#failures[@]} -gt 0 ]; then printf '실패: %s\n' "${failures[*]}"; exit 1; fi
echo "모든 점검 통과"
