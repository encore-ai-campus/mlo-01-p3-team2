"""추첨 스케줄러는 1초마다 살피되 DB 연결은 이어 쓴다(계획 docs/metaverse-optimization-plan.md 4d)."""
import threading
import time

from django.db.backends.signals import connection_created
from django.test import TransactionTestCase, override_settings

from . import scheduler


class SchedulerConnectionTests(TransactionTestCase):
    def test_the_scheduler_keeps_one_connection_across_ticks(self):
        from .models import Control

        Control.objects.get_or_create(pk=1)
        created, stop = [], threading.Event()

        def count(sender, connection, **kwargs):
            created.append(threading.current_thread().name)

        connection_created.connect(count)
        try:
            with override_settings(CAMPUS_RAFFLE_POLL_SECONDS=0.01):
                worker = threading.Thread(target=scheduler.scheduler_loop, args=(stop,), name="raffle-test")
                worker.start()
                time.sleep(.3)  # 30번쯤 살핀다
                stop.set()
                worker.join(2)
        finally:
            connection_created.disconnect(count)
        self.assertLessEqual(created.count("raffle-test"), 1)  # 예전: 살필 때마다 새 연결(운영에서는 TLS 핸드셰이크)


class ChangeCoalescingTests(TransactionTestCase):
    """추첨 변경 알림은 첫 번째를 바로 보내고, 1초 안에 더 오면 끝에 한 번 더 보낸다(계획 4c)."""

    async def test_a_burst_of_changes_becomes_one_now_and_one_after(self):
        import asyncio
        from unittest.mock import patch

        from . import live

        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append(message["type"])

        with patch.object(live, "COALESCE_SECONDS", .2):
            live.bind_socket_loop(Layer())
            for _ in range(5):  # 다른 스레드(HTTP 요청·스케줄러)의 커밋처럼
                await asyncio.to_thread(live.publish_change)
            await asyncio.sleep(.05)
            self.assertEqual(sent, ["raffle.changed"])  # 첫 변경은 바로
            await asyncio.sleep(.3)
            self.assertEqual(sent, ["raffle.changed"] * 2)  # 나머지 넷은 묶어 한 번(최신 상태로)
            await asyncio.to_thread(live.publish_change)
            await asyncio.sleep(.05)
            self.assertEqual(len(sent), 3)  # 조용해진 뒤의 변경은 다시 바로
