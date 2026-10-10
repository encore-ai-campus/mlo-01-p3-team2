import math
import signal
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import InterfaceError, OperationalError, close_old_connections, connection
from pymongo.errors import PyMongoError

from events import mongo
from events.relay import BATCH, EventConflict, outbox_status, relay_batch


class Command(BaseCommand):
    help = (
        "outbox 의 미전송 이벤트를 MongoDB ad_events 로 옮긴다(멱등 저장: 같은 내용이면 통과, 다른 내용이면 멈추고 경보). 기본은 계속 돈다. "
        "--once 는 밀린 것을 비우고 끝난다. 여러 개를 동시에 돌려도 안전하다. --status 는 미전송 현황만 본다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="한 번 비우고 종료")
        parser.add_argument("--status", action="store_true", help="미전송 건수와 가장 오래된 것의 나이만 출력")
        parser.add_argument("--interval", type=float, default=1.0, help="더 보낼 것이 없을 때의 주기(초). 기본 1")
        parser.add_argument("--batch", type=int, default=BATCH, help=f"한 번에 옮길 최대 건수. 기본 {BATCH}")

    def drain(self, batch, should_stop):
        total = {"sent": 0, "duplicate": 0}
        while not should_stop():
            result = relay_batch(limit=batch)
            total["sent"] += result.sent
            total["duplicate"] += result.duplicate
            if result.sent + result.duplicate < batch:
                break
        return total

    def handle(self, *args, **options):
        batch, interval = options["batch"], options["interval"]
        if batch < 1:
            raise CommandError("--batch 는 1 이상의 정수여야 합니다.")
        if not (math.isfinite(interval) and interval > 0):
            raise CommandError("--interval 은 유한한 양수(초)여야 합니다.")
        if options["status"]:
            self.stdout.write(str(outbox_status()))
            return
        stop = []
        previous = signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        self.stdout.write(f"started {'once' if options['once'] else f'interval={interval}'} batch={batch}")
        self.stdout.flush()
        failures = 0
        try:
            while True:
                try:
                    total = self.drain(batch, lambda: bool(stop))
                    failures = 0
                    if any(total.values()) or options["once"]:
                        self.stdout.write(f"{total} {outbox_status()}")
                except EventConflict as error:
                    # 이벤트 ID 가 결정적이라 일어나선 안 되는 일이다 — 덮어쓰지도 건너뛰지도 않고 멈춘다. 충돌하지 않은 이벤트는 이미 표시돼 있다
                    raise CommandError(f"충돌로 중계를 멈춥니다: {error}")
                except (PyMongoError, mongo.NotConfigured, OperationalError, InterfaceError) as error:
                    if options["once"]:
                        raise CommandError(f"중계 실패: {type(error).__name__}: {str(error)[:200]}")
                    # 상시 중계는 MongoDB 나 DB 가 잠시 죽어도 죽지 않는다: 행은 미전송으로 남아 있고, 점점 길게 쉬며 다시 시도한다
                    failures += 1
                    wait = min(30.0, interval * 2 ** min(failures, 5))
                    self.stderr.write(f"이번 주기를 건너뛴다({failures}번째, {wait:.0f}초 뒤 다시): {type(error).__name__}: {str(error)[:200]}")
                    mongo.close()
                    if not connection.in_atomic_block:
                        close_old_connections()
                    time.sleep(wait)
                    if stop:
                        return
                    continue
                if options["once"] or stop:
                    return
                try:
                    time.sleep(interval)
                except KeyboardInterrupt:
                    return
        finally:
            signal.signal(signal.SIGTERM, previous)
            mongo.close()
