import math
import signal
import time

from django.core.management.base import BaseCommand, CommandError

from records.api import process_pending, reset_stuck, stuck_count


class Command(BaseCommand):
    help = (
        "수신함의 RECEIVED 반응을 처리한다(규칙 체인 → 과금 → ACCEPTED/REJECTED). 기본은 단일 관리 프로세스로 1초 주기·배치 100 으로 계속 돈다. "
        "--once 는 밀린 것을 비우고 끝난다. 여러 개를 동시에 돌려도 안전하다(이중 과금 없음)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="한 번 비우고 종료")
        parser.add_argument("--interval", type=float, default=1.0, help="주기(초). 기본 1")
        parser.add_argument("--batch", type=int, default=100, help="한 번에 처리할 최대 건수. 기본 100")
        parser.add_argument("--retry-stuck", action="store_true", help="실패가 반복돼 빠진 반응의 실패 횟수를 0 으로 되돌려 다시 처리 대상으로")

    def drain(self, batch, should_stop):
        total = {"accepted": 0, "rejected": 0, "skipped": 0, "failed": 0}
        while not should_stop():
            counts = process_pending(limit=batch, should_stop=should_stop)
            for key, value in counts.items():
                total[key] += value
            if sum(counts.values()) < batch:  # 더 없다(또는 멈추라는 신호로 중간에 끊었다)
                break
        return total

    def handle(self, *args, **options):
        batch, interval = options["batch"], options["interval"]
        if batch < 1:  # 0 은 아무것도 처리하지 않으면서 끝나지도 않는다
            raise CommandError("--batch 는 1 이상의 정수여야 합니다.")
        if not (math.isfinite(interval) and interval > 0):
            raise CommandError("--interval 은 유한한 양수(초)여야 합니다.")
        # 옵션 검증이 모두 끝난 뒤에야 상태를 바꾼다
        if options["retry_stuck"]:
            self.stdout.write(f"retried-stuck: {reset_stuck()}")
        stop = []
        previous = signal.signal(signal.SIGTERM, lambda *_: stop.append(1))  # 배포·재시작 때 처리 중인 한 건은 끝내고 멈춘다
        try:
            while True:
                total = self.drain(batch, lambda: bool(stop))
                if any(total.values()) or options["once"]:
                    self.stdout.write(f"{total} stuck={stuck_count()}")
                if options["once"] or stop:
                    return
                try:
                    time.sleep(interval)
                except KeyboardInterrupt:
                    return
        finally:
            signal.signal(signal.SIGTERM, previous)
