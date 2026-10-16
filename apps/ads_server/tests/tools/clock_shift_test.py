#!/usr/bin/env python
"""시계를 N일 앞당겨 백엔드 시험을 돈다 — 실제 시계에 기대는 시험(날짜가 지나면 깨지는 시험)을 미리 찾는다(계획서 §8.4.17, 6-16b).

    DB_NAME=ads_impl python tests/tools/clock_shift_test.py --days 4            # 전체 시험
    DB_NAME=ads_impl python tests/tools/clock_shift_test.py --days 2300 tests.ops.test_ad_create

`django.utils.timezone.now`(앱 코드의 시계)만 앞당긴다. 시험 데이터는 고정 시각(`tests.support.factories.NOW`)을 쓰므로, 여기서만 실패하는 시험은
그 날짜가 오면 `check.sh` 에서도 실패한다. 파이썬 `datetime.now`·`time.time` 은 그대로라, 그것을 앱 시계와 비교하는 시험은 여기서만 어긋난다
(그런 시험은 앱 시계로 비교하게 고친다). `check.sh` 에는 넣지 않는다(시간이 두 배) — 측정 단계에서 +4일·+40일·+6년으로 돌린다.
"""
import argparse
import datetime
import os
import runpy
import sys
from pathlib import Path

import django.utils.timezone

BACKEND = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=float, required=True, help="앞당길 날 수")
    parser.add_argument("labels", nargs="*", help="시험 라벨(없으면 전체)")
    options = parser.parse_args()
    shift = datetime.timedelta(days=options.days)
    real = django.utils.timezone.now
    django.utils.timezone.now = lambda: real() + shift  # 프로젝트 코드를 불러오기 전에 바꾼다 — `from django.utils.timezone import now` 도 이것을 받는다
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    sys.argv = ["manage.py", "test", "--noinput", *options.labels]
    runpy.run_path("manage.py", run_name="__main__")


if __name__ == "__main__":
    main()
