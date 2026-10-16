from django.core.management.base import BaseCommand

from campaigns.api import end_expired_campaigns


class Command(BaseCommand):
    help = "기간이 지난 캠페인을 ENDED 로 바꾼다(멱등). 주기 실행 방식은 인프라와 정한다(설계 §7-9)."

    def handle(self, *args, **options):
        self.stdout.write(f"ended: {end_expired_campaigns()}")
