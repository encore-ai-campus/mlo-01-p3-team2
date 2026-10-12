"""미접수 노출을 처리할 시각에 재전송하는 게임 서버 명령."""

import math
import signal
from threading import Event, current_thread, main_thread

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from ad_bridge import AdsClient, AdsConfig
from ad_bridge.impressions import store as impression_store
from ad_bridge.delivery.worker import dispatch_due_impressions
from ad_bridge.delivery.policy import RetryPolicy


class Command(BaseCommand):
    help = "저장된 미접수 노출을 재전송합니다. --once는 현재 처리할 한 배치만 실행합니다."
    # 게임 전체 점검 대신 설정을 먼저 검증하고 저장소 오류는 아래에서 안전하게 처리한다.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="처리할 한 배치만 실행한 뒤 종료")
        parser.add_argument("--batch-size", type=int, default=100, help="한 배치의 최대 처리 건수 (기본 100)")
        parser.add_argument("--poll-interval", type=float, default=1.0, help="배치 사이 대기 초 (기본 1)")

    def handle(self, *args, **options):
        limit = options["batch_size"]
        interval = options["poll_interval"]
        if type(limit) is not int or limit <= 0:
            raise CommandError("--batch-size는 양의 정수여야 합니다.")
        if (isinstance(interval, bool) or not isinstance(interval, (int, float))
                or not math.isfinite(interval) or interval <= 0):
            raise CommandError("--poll-interval은 유한한 양수여야 합니다.")

        try:
            # 설정이 잘못된 프로세스가 먼저 기록을 예약하지 않도록 통신 설정부터 검증한다.
            client = AdsClient(AdsConfig.from_env())
            policy = RetryPolicy()
        except ValueError:
            raise CommandError("광고 API 주소·매체 키·타임아웃 설정을 확인해 주세요.") from None

        stop = Event()
        old_handler = None
        manages_signal = current_thread() is main_thread()

        def request_stop(signum, frame):
            # 첫 Ctrl+C에는 진행 중인 요청의 결과를 저장하고 다음 요청 전에 종료한다.
            if stop.is_set():
                raise KeyboardInterrupt
            stop.set()

        if manages_signal:
            old_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, request_stop)

        try:
            while not stop.is_set():
                try:
                    # 장시간 실행 중 DB 연결이 끊겼으면 다음 작업에서 다시 연결하도록 정리한다.
                    close_old_connections()
                    counts = dispatch_due_impressions(
                        client=client, store=impression_store, limit=limit,
                        policy=policy, should_stop=stop.is_set,
                    )
                except DatabaseError:
                    if options["once"]:
                        raise CommandError("광고 재전송 DB 작업에 실패했습니다.") from None
                    # DB 오류 원문에는 접속 정보가 들어갈 수 있으므로 출력하지 않는다.
                    self.stderr.write("광고 재전송 DB 작업에 실패했습니다. 다음 확인 주기에 다시 시도합니다.")
                else:
                    if counts["attempted"] or options["once"]:
                        self.stdout.write(
                            f"시도 {counts['attempted']}건 / 접수 {counts['acknowledged']}건 / "
                            f"미확정 {counts['unconfirmed']}건 / 확인 필요 {counts['blocked']}건"
                        )
                if options["once"] or stop.is_set():
                    break
                # Event 대기는 Ctrl+C 종료 플래그가 설정되면 즉시 끝난다.
                stop.wait(interval)
        finally:
            if manages_signal:
                signal.signal(signal.SIGINT, old_handler)
            try:
                close_old_connections()
            except DatabaseError:
                self.stderr.write("광고 재전송 종료 중 DB 연결 정리에 실패했습니다.")
