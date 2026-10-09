from django.core.management.base import BaseCommand, CommandError

from billing.api import check_ledger


class Command(BaseCommand):
    help = "정합성 점검: 지갑 잔액 == 원장 합계, 원장 순번·누적, 일 소진액 == 원장 합계. 어긋나면 비정상 종료한다(한 읽기 스냅샷 안에서 본다)."

    def add_arguments(self, parser):
        parser.add_argument("--quiescent", action="store_true", help="이미 열린 트랜잭션 안에서 부를 때만(단위 시험): 동시에 쓰는 연결이 없다는 호출자의 보장")

    def handle(self, *args, **options):
        problems = check_ledger(quiescent=options["quiescent"])
        for p in problems:
            self.stderr.write(p)
        if problems:
            raise CommandError(f"{len(problems)}건의 불일치")
        self.stdout.write("ok")
