from django.core.management.base import BaseCommand, CommandError

from events import ndjson


class Command(BaseCommand):
    help = "NDJSON manifest 가 가리키는 데이터 파일이 manifest 와 맞는지(SHA-256·행 수·줄 형식) 확인한다. 하나라도 어긋나면 비정상 종료한다."

    def add_arguments(self, parser):
        parser.add_argument("manifests", nargs="+", help="manifest 파일(<이름>.manifest.json)")

    def handle(self, *args, **options):
        bad = 0
        for path in options["manifests"]:
            try:
                problems = ndjson.verify(path)
            except ndjson.NdjsonError as error:
                problems = [str(error)]
            self.stdout.write(f"{'OK  ' if not problems else 'FAIL'} {path}")
            for problem in problems:
                self.stdout.write(f"     - {problem}")
            bad += bool(problems)
        if bad:
            raise CommandError(f"{bad}개 manifest 가 맞지 않습니다.")
