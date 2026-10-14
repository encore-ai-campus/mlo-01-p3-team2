"""프론트 배포 후 점검(설계 §10 "시험 구성" ⑤, 계획서 §8.4.20): 배포된 프론트에서 돌린다. 하나라도 실패하면 종료 코드 1.

    python manage.py ops_check

백엔드의 `ops_check` 와 같은 모양이다 — 점검마다 `OK`/`FAIL` 한 줄, 하나가 실패해도 나머지를 모두 본다. 아무것도 바꾸지 않는다
(화면 한 장은 로그인 화면을 읽기만 한다). 백 서버의 상태(DB·MongoDB·처리 프로세스)는 백 서버의 `ops_check` 가 본다.
"""
import io
import json
import re
import urllib.request
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.finders import get_finders
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

IGNORED = ["CVS", ".*", "*~"]  # collectstatic 의 기본 무시 목록과 같다


def _deploy():
    out = io.StringIO()
    try:
        call_command("check", deploy=True, fail_level="WARNING", stdout=out, stderr=out)
    except CommandError as exc:  # 시스템 점검 항목(… (security.W018) …)을 이유로
        fails = [line.strip()[:160] for line in f"{out.getvalue()}\n{exc}".splitlines() if re.search(r"\(\w+\.[EW]\d+\)", line)]
        raise CommandError("; ".join(fails[:3]) or str(exc)) from exc
    return out.getvalue().strip() or "이상 없음"


def _static():
    """`collectstatic` 이 모을 파일이 `STATIC_ROOT` 에 모두 있는가 — WhiteNoise 는 시작할 때 그 폴더만 읽는다."""
    root = Path(settings.STATIC_ROOT)
    expected = set()
    for finder in get_finders():
        for path, storage in finder.list(IGNORED):
            prefix = getattr(storage, "prefix", None)
            expected.add(str(Path(prefix) / path) if prefix else path)
    missing = sorted(p for p in expected if not (root / p).is_file())
    if missing:
        raise CommandError(f"{len(missing)}개가 {root} 에 없다 — collectstatic --noinput 을 돌린 뒤 프론트를 다시 시작한다(예: {missing[0]})")
    return f"{len(expected)}개"


def _backend():
    url = f"{settings.BACKEND_URL}/api/media/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=settings.BACKEND_TIMEOUT) as r:  # nosec B310 — BACKEND_URL 은 설정이 http(s) 서버 주소만 받는다
            status, body = r.status, json.loads(r.read() or b"{}")
    except (OSError, ValueError) as exc:
        raise CommandError(f"{url}: {type(exc).__name__}: {exc}") from exc
    if status != 200 or body.get("status") != "ok":
        raise CommandError(f"{url}: {status} {body}")
    return url


def _screen():
    """로그인 화면 한 장: 프론트 → 백엔드(화면 데이터) → 프론트 그리기. 브라우저처럼 허용된 호스트 이름으로 요청한다."""
    host = next((h for h in settings.ALLOWED_HOSTS if h != "*" and not h.startswith(".")), "localhost")
    try:
        response = Client(HTTP_HOST=host).get("/accounts/login/")
    except Exception as exc:
        raise CommandError(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200 or b'name="username"' not in response.content:
        raise CommandError(f"/accounts/login/ 가 {response.status_code} 이고 로그인 폼이 없다")
    return f"/accounts/login/ (Host: {host})"


CHECKS = (
    ("배포 설정", _deploy),
    ("정적 파일", _static),
    ("백엔드", _backend),
    ("화면 한 장", _screen),
)


class Command(BaseCommand):
    help = "프론트 배포 후 점검: 배포 설정·정적 파일·백엔드 닿음·화면 한 장(프론트 → 백엔드 → 그리기). 하나라도 실패하면 종료 코드 1."

    def handle(self, *args, **options):
        failed = []
        for name, check in CHECKS:
            try:
                detail = check()
            except Exception as exc:  # 점검 하나의 실패가 나머지를 가리지 않게 — 모두 본 뒤 실패를 모은다
                failed.append(name)
                self.stdout.write(f"FAIL {name}: {(str(exc).strip() or type(exc).__name__).splitlines()[0]}")
            else:
                self.stdout.write(f"OK   {name}: {detail}")
        if failed:
            raise CommandError(f"점검 실패: {', '.join(failed)}")
