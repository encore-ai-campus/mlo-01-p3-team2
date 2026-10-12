from django.core.management.base import BaseCommand

from billing.api import recompute_spend


class Command(BaseCommand):
    help = "원장에서 캠페인 일 소진액을 다시 계산한다(BUDGET_DAY_OFFSET_HOURS 를 바꾼 뒤 실행)."

    def handle(self, *args, **options):
        self.stdout.write(f"rows: {recompute_spend()}")
