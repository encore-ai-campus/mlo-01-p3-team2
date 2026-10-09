"""MongoDB `ad_events` 컬렉션(봉투 검증)과 색인을 만든다. 여러 번 실행해도 같다(DB-2). 배포 때 한 번 실행한다."""
from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import PyMongoError

from events import mongo, store


class Command(BaseCommand):
    help = "ad_events 컬렉션과 색인을 만든다(멱등). 확인은 check_event_store."

    def handle(self, *args, **options):
        try:
            done = store.ensure()
        except (mongo.NotConfigured, PyMongoError, RuntimeError) as exc:
            raise CommandError(f"{type(exc).__name__}: {str(exc)[:300]}")
        finally:
            mongo.close()
        for line in done:
            self.stdout.write(line)
        self.stdout.write("변경 없음" if not done else "완료")
