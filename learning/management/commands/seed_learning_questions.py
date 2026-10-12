import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from learning.models import Question, QuestionChoice
from learning.services import validate_question
from learning.bank_validation import validate_bank


class Command(BaseCommand):
    help = 'JSON 문제은행을 검증하고 중복 없이 추가합니다. 기존 문제는 수정하지 않습니다.'

    def add_arguments(self, parser):
        default = Path(__file__).resolve().parents[2] / 'sample_questions.json'
        parser.add_argument('--file', type=Path, default=default)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            rows = json.loads(options['file'].read_text(encoding='utf-8'))
            if not isinstance(rows, list):
                raise ValueError('JSON 배열이 필요합니다.')
            if rows and all('subject' in row and 'question_code' in row for row in rows):
                report=validate_bank(rows,require_full=False)
                if report['errors']:raise ValueError('; '.join(report['errors']))
            created = 0
            for row in rows:
                fields = {k: row[k] for k in ['question_type', 'difficulty', 'category', 'question_text', 'correct_answer']}
                fields.update(subject=row.get('subject', 'python'), question_code=row.get('question_code'), code_snippet=row.get('code_snippet'), explanation=row.get('explanation', ''))
                code = fields.pop('question_code')
                matches = Question.objects.filter(**fields)
                expected = [(i, text) for i, text in enumerate(row.get('choices', []), 1)]
                question = next((q for q in matches if list(q.choices.values_list('choice_no', 'choice_text')) == expected), None)
                if question is not None and code and question.question_code not in (None, code):
                    raise ValueError('기존 문항 코드와 충돌합니다.')
                if question is not None and code and question.question_code is None:
                    question.question_code = code
                    question.save(update_fields=['question_code'])
                if question is None:
                    question = Question.objects.create(question_code=code, **fields)
                    for number, text in expected:
                        QuestionChoice.objects.create(question=question, choice_no=number, choice_text=text)
                    created += 1
                validate_question(question)
        except (OSError, ValueError, KeyError, TypeError, ValidationError) as error:
            raise CommandError(f'Seed 실패: {error}')
        self.stdout.write(self.style.SUCCESS(f'문제 {created}개 추가, {len(rows) - created}개 기존 데이터 유지'))
