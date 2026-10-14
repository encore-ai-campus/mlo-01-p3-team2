#!/usr/bin/env bash
# 보안·품질 점검 일괄 실행. 하나라도 실패하면 비정상 종료한다.
#
#   tests/tools/check.sh              전체 실행
#   OFFLINE_OK=1 tests/tools/check.sh pip-audit 이 네트워크 문제로 못 돌면 건너뛴다(기본은 실패로 취급)
#   PYTHON=/path/to/python        사용할 파이썬(기본: python)
#
# 단계: MySQL·MongoDB 접속(없으면 명확히 실패 — 시험을 건너뛰지 않는다) → check --deploy(prod 샘플 환경) → 마이그레이션 최신 여부 → 전체 테스트(경계 검사·보안 회귀 포함)
#       → 부하 시험(소규모: MySQL·실제 HTTP·별도 처리 프로세스, 불변식) → 프론트 check --deploy·시험(apps/ads_frontend) → pip-audit(의존성 취약점) → bandit(정적 보안 점검)
#       150 동시 전체 시험은 `python tests/tools/load_test.py`(약 40초, docs/ads-server/load-test.md)
set -uo pipefail
cd "$(dirname "$0")/../.."  # apps/ads_server
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
  eval "$("$PY" tests/tools/mysql_admin.py --print-env)"  # .env 의 DB_* (실제 환경변수가 우선)
  # MySQL 에서는 모델 검사가 서버 정보를 읽으려고 실제로 연결한다 → 시험 DB 접속 값(DB_*)을 그대로 넘긴다.
  env -i PATH="$PATH" DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY="$key" \
    ALLOWED_HOSTS=ads.example.com ADMIN_URL_PATH=ops-check/ \
    DB_NAME="${DB_NAME:-ads_server}" DB_USER="${DB_USER:-}" DB_PASSWORD="${DB_PASSWORD:-}" DB_HOST="${DB_HOST:-127.0.0.1}" DB_PORT="${DB_PORT:-3306}" \
    MEDIA_ROOT=/tmp/ads-check-media ASSET_PUBLIC_BASE_URL=https://ads.example.com TRUSTED_PROXY_COUNT=1 CSRF_TRUSTED_ORIGINS=https://ads.example.com \
    "$PY" -m django check --deploy --fail-level WARNING
}

# 프론트(apps/ads_frontend, 설계 §6.6 "6-15 분리") — 프론트는 DB 를 쓰지 않지만, DB 접속 단계가 실패하면 check.sh 는 그 자리에서 멈추므로 이 단계도 돌지 않는다. 의존성(Django·python-dotenv·whitenoise)은 백엔드 목록에 모두 있어 pip-audit 이 함께 본다
check_frontend_deploy() {
  local key; key="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(60))')"
  (cd ../ads_frontend && env -i PATH="$PATH" FRONTEND_SECRET_KEY="$key" FRONTEND_ALLOWED_HOSTS=ads.example.com ADMIN_URL_PATH=ops-check/ \
    BACKEND_URL=http://10.0.0.5:8000 "$PY" manage.py check --deploy --fail-level WARNING)
}

# 시험 수 관문(설계 §10 "시험 구성" ①, 6-18k): 서버마다 최대 500 · 권장 300. 시험 출력의 "Ran N tests" 를 변수에 남긴다(macOS bash 3.2 — 연관 배열 없음)
OPS_N=; DEV_N=; FRONT_N=
counted() {
  local var="$1" out rc; shift
  out="$("$@" 2>&1)"; rc=$?
  printf '%s\n' "$out"
  eval "$var=$(printf '%s\n' "$out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p' | tail -1)"
  return $rc
}
frontend_tests() { counted FRONT_N sh -c 'cd ../ads_frontend && exec "$@"' sh "$PY" manage.py test; }
count_gate() {
  if [ -z "$OPS_N" ] || [ -z "$DEV_N" ] || [ -z "$FRONT_N" ]; then echo "시험 수를 읽지 못했다"; return 1; fi
  printf '백엔드 운영용 %s · 개발용 %s(합 %s) · 프론트 %s\n' "$OPS_N" "$DEV_N" "$((OPS_N + DEV_N))" "$FRONT_N"
  [ "$OPS_N" -gt 300 ] && echo "경고: 백엔드 운영용이 권장 300 을 넘는다"
  [ "$FRONT_N" -gt 300 ] && echo "경고: 프론트가 권장 300 을 넘는다"
  [ "$((OPS_N + DEV_N))" -le 500 ] && [ "$FRONT_N" -le 500 ]
}

audit_dependencies() {
  local tmp out rc; tmp="$(mktemp)"
  "$PY" tests/tools/pinned_requirements.py > "$tmp" || { echo "의존성 목록을 만들지 못했다"; return 1; }
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

run "MySQL 접속 (시험 DB, 없으면 여기서 멈춘다)" "$PY" tests/tools/mysql_admin.py
run "MongoDB 접속 (이벤트 저장소 시험, 없으면 여기서 멈춘다)" "$PY" tests/tools/mongo_admin.py
if [ ${#failures[@]} -gt 0 ]; then printf '\n실패: %s\nDB 가 필요한 나머지 단계는 실행하지 않았습니다(README "MySQL 시험 환경"·"MongoDB 시험 환경").\n' "${failures[*]}"; exit 1; fi
run "check --deploy (prod 샘플 환경, 경고 0)" check_deploy
run "마이그레이션이 최신인가" "$PY" manage.py makemigrations --check --dry-run
run "운영용 시험 (tests/ops — 제품 동작)" counted OPS_N "$PY" manage.py test tests.ops
run "개발용 시험 (tests/dev — 문서·계약·코드 구조 대조, 시험 도구)" counted DEV_N "$PY" manage.py test tests.dev
run "부하 시험 (20 동시, 불변식)" "$PY" tests/tools/load_test.py --small
run "프론트 check --deploy (운영 샘플 환경, 경고 0)" check_frontend_deploy
run "프론트 시험 (전달·통과·그리기)" frontend_tests
run "시험 수 (서버당 최대 500 · 권장 300)" count_gate
run "pip-audit (의존성 취약점)" audit_dependencies
run "bandit (정적 보안 점검)" "$PY" -m bandit -q -r config foundation console assets masters engine campaigns billing events records serving_api ../ads_frontend/config ../ads_frontend/ui

printf '\n======== 요약 ========\n'
[ ${#skipped[@]} -gt 0 ] && printf '건너뜀: %s\n' "${skipped[*]}"
if [ ${#failures[@]} -gt 0 ]; then printf '실패: %s\n' "${failures[*]}"; exit 1; fi
echo "모든 점검 통과"
