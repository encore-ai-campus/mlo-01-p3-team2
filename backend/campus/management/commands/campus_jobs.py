"""백그라운드 작업만 돌린다(계획 docs/metaverse-multiprocess-plan.md M4): 식단 사진 갱신·만료 세션 정리·Kafka outbox 전송.

소켓 프로세스(daphne)를 여러 개 띄울 때 이 작업들은 이 명령 하나에서만 돈다. 프로세스마다 돌면 N번 실행되고,
outbox 는 첫 행을 잠금 없이 집어 같은 이벤트가 여러 번 나간다. 한 프로세스로 띄울 때(run-campus.py)는 지금처럼 그 안에서 돈다.
"""
import signal
import threading

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "식단 사진 갱신·만료 세션 정리·Kafka outbox 전송을 한 프로세스에서 돌린다(여러 소켓 프로세스용)."

    def handle(self, *args, **options):
        from accounts.session_cleanup import start_session_cleanup
        from campus.menu_updater import start_menu_updater
        from eventing.publisher import start_outbox_publisher

        start_menu_updater()
        start_session_cleanup()
        start_outbox_publisher()
        stop = threading.Event()
        for name in (signal.SIGTERM, signal.SIGINT):
            signal.signal(name, lambda *_: stop.set())
        self.stdout.write("campus jobs running")
        stop.wait()
