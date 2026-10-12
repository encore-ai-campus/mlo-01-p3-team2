import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from learning.bank_validation import validate_bank
class Command(BaseCommand):
    help='Read-only problem-bank validation; never writes to DB.'
    def add_arguments(self,parser):
        parser.add_argument('--file',type=Path,required=True)
        parser.add_argument('--allow-partial',action='store_true')
    def handle(self,*args,**options):
        try:rows=json.loads(options['file'].read_text(encoding='utf-8'))
        except (OSError,ValueError) as error:raise CommandError(str(error))
        result=validate_bank(rows,require_full=not options['allow_partial'])
        self.stdout.write(json.dumps(result,ensure_ascii=False,indent=2))
        if result['errors']:raise CommandError('Problem bank validation failed; not complete.')
