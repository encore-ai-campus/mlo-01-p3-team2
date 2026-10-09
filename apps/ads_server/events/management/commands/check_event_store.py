"""MongoDB 이벤트 저장소 상태 확인: 연결·버전·레플리카셋·쓰기 권한·컬렉션·색인. 하나라도 실패하면 비정상 종료한다."""
from django.core.management.base import BaseCommand, CommandError

from events import mongo, store


class Command(BaseCommand):
    help = "이벤트 저장소(MongoDB)의 연결·쓰기 권한·컬렉션·색인을 확인한다."

    def handle(self, *args, **options):
        try:
            results = store.check()
        finally:
            mongo.close()
        for r in results:
            self.stdout.write(f"{'OK  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
        if not all(r.ok for r in results):
            raise CommandError("이벤트 저장소 확인에 실패했습니다.")
