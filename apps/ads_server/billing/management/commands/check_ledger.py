from django.core.management.base import BaseCommand, CommandError

from billing.api import check_ledger


class Command(BaseCommand):
    help = "정합성 점검: 지갑 잔액 == 원장 합계. 어긋나면 비정상 종료한다."

    def handle(self, *args, **options):
        problems = check_ledger()
        for p in problems:
            self.stderr.write(p)
        if problems:
            raise CommandError(f"{len(problems)}건의 불일치")
        self.stdout.write("ok")
