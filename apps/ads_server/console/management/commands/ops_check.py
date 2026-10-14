"""배포 후 점검 = 운영 서버의 운영 환경 시험(설계 §10 "시험 구성" ⑤, 계획서 §8.4.19·§8.4.20): 배포된 백엔드에서 돌린다. 운영 데이터는 바꾸지 않고,
하나라도 실패하면 종료 코드 1.

    python manage.py ops_check

**다섯 가지**(6-19d — 서버마다 5개 이하): 설정·파일 저장소 · 의존성 · MySQL · MongoDB · 상시 처리. 점검마다 한 줄(`OK`/`FAIL`)을 쓰고,
하나가 실패해도 나머지를 모두 본다(한 항목 안의 여러 점검도 모두 보고 이유를 모은다). 기존 점검 명령과 각 모듈의 `api` 를 부를 뿐 판정 규칙을 새로 두지 않는다 —
기다림의 상한(`OPS_CHECK_MAX_WAIT_SECONDS`)과 설치된 패키지 버전만 여기서 본다. MongoDB 점검은 점검용 컬렉션에 문서 하나를 쓰고 지운다(`check_event_store`).
"""
import io
import os
import re
from importlib import metadata
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from events import api as events
from records import api as records


def _command(name, **options):
    out = io.StringIO()
    try:
        call_command(name, stdout=out, stderr=out, **options)
    except SystemExit as exc:  # migrate --check 는 적용 안 된 마이그레이션이 있으면 sys.exit(1)
        if exc.code:
            raise CommandError("적용 안 된 마이그레이션이 있다") from exc
    except CommandError as exc:  # 명령이 찍은 실패 줄(FAIL …)이나 시스템 점검 항목(… (security.W004) …)을 이유로
        text = f"{out.getvalue()}\n{exc}"
        fails = [line.strip() for line in text.splitlines() if line.startswith("FAIL") or re.search(r"\(\w+\.[EW]\d+\)", line)]
        raise CommandError("; ".join(f[:160] for f in fails[:3]) or str(exc)) from exc
    lines = out.getvalue().strip().splitlines()
    return lines[0] if len(lines) == 1 else f"{len(lines)}개 항목 확인" if lines else "이상 없음"


def _waited(status, what):
    age, limit = status["oldest_age_seconds"] or 0, settings.OPS_CHECK_MAX_WAIT_SECONDS
    if age > limit:
        raise CommandError(f"가장 오래된 {what}이(가) {age:.0f}초째 기다린다(상한 {limit}초) — 처리 프로세스가 멈췄을 수 있다")
    return f"가장 오래 기다린 것 {age:.0f}초"


def _reactions():
    s = records.inbox_status()
    if s["stuck"]:
        raise CommandError(f"stuck {s['stuck']}건 — 원인을 본 뒤 process_reactions --retry-stuck")
    return f"{_waited(s, '반응')} · 대기 {s['received']} · 보류 {s['held']}"


def _outbox():
    s = events.outbox_status()
    return f"{_waited(s, '미전송 이벤트')} · 미전송 {s['pending']}"


def _media():
    root = settings.MEDIA_ROOT
    if not (os.path.isdir(root) and os.access(root, os.W_OK | os.X_OK)):
        raise CommandError(f"{root} 가 없거나 쓸 수 없다")
    return root


_installed = metadata.version  # 설치된 배포판의 버전(시험이 바꿔 끼운다)


def _compatible(have, spec):
    """`~=X.Y.Z`: X.Y 가 같고 X.Y.Z 이상(PEP 440 의 호환 릴리스). 운영 묶음에는 packaging 이 없어 숫자만 비교한다."""
    want = [int(p) for p in spec.split(".")]
    got = [int(p) for p in re.findall(r"\d+", have)[:len(want)]]
    return got[:-1] == want[:-1] and got >= want


def _dependencies():
    """설치된 패키지가 requirements.txt 의 운영 묶음(개발·시험 묶음 머리 앞까지 — 서버 묶음에는 운영 묶음만 있다)과 맞는가."""
    text = (Path(settings.BASE_DIR) / "requirements.txt").read_text(encoding="utf-8").partition("# ---- 개발·시험 ----")[0]
    wrong, count = [], 0
    for line in (raw.split("#")[0].strip() for raw in text.splitlines()):
        if not line:
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*~=\s*(\d+(?:\.\d+)+)", line)
        if not m:
            wrong.append(f"읽을 수 없는 줄 '{line}'")
            continue
        name, spec = m.groups()
        count += 1
        try:
            have = _installed(name)
        except metadata.PackageNotFoundError:
            wrong.append(f"{name} 가 없다")
            continue
        if not _compatible(have, spec):
            wrong.append(f"{name} {have}(요구 ~={spec})")
    if wrong:
        raise CommandError("; ".join(wrong))
    return f"{count}개가 requirements 와 맞다"


def _all(*parts):
    """여러 점검을 한 항목으로: 모두 돌고, 실패한 것의 이유를 모은다."""
    details, fails = [], []
    for label, part in parts:
        try:
            details.append(f"{label} {part()}")
        except Exception as exc:
            fails.append(f"{label}: {(str(exc).strip() or type(exc).__name__).splitlines()[0]}")
    if fails:
        raise CommandError(" · ".join(fails))
    return " · ".join(details)


CHECKS = (  # 서버마다 5개 이하(사용자 2026-10-14)
    ("설정·파일 저장소", lambda: _all(("배포 점검", lambda: _command("check", deploy=True, fail_level="WARNING")), ("MEDIA_ROOT", _media))),
    ("의존성", _dependencies),
    ("MySQL", lambda: _all(("마이그레이션", lambda: _command("migrate", check_unapplied=True)), ("원장 대조", lambda: _command("check_ledger")))),
    ("MongoDB", lambda: _command("check_event_store")),
    ("상시 처리", lambda: _all(("반응 처리", _reactions), ("outbox", _outbox))),
)


class Command(BaseCommand):
    help = "운영 환경 점검(배포 후): 설정·파일 저장소·의존성·MySQL(마이그레이션·원장)·MongoDB·상시 처리(반응·outbox). 운영 데이터는 바꾸지 않는다. 하나라도 실패하면 종료 코드 1."

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
