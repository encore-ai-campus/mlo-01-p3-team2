import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command,CommandError
from django.test import TestCase
from django.contrib.auth import get_user_model
from learning import services
from learning.tests.legacy_fixtures import prepare_event_context
from learning.models import Question,QuestionChoice,LearningSession,UserAnswer
from learning.bank_validation import validate_bank
from learning.grading import answers_match
from learning.management.commands.import_learning_bank import apply_rows,plan,snapshot_existing,digest_snapshot

DATA=Path(__file__).resolve().parents[1]/'data'/'expanded_questions_20261016.json'

class FullBankTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base=Path(__file__).resolve().parents[1]
        call_command('seed_learning_questions',file=base/'sample_questions.json',stdout=StringIO())
        call_command('seed_learning_questions',file=base/'data/initial_subject_bank.json',stdout=StringIO())
        cls.rows=json.loads(DATA.read_text(encoding='utf-8'))

    def test_new_bank_structure_and_blank_markers(self):
        self.assertEqual(validate_bank(self.rows,require_full=False)['errors'],[])
        self.assertEqual(len(self.rows),2280)
        for row in self.rows:
            if row['question_type']=='fill_blank':self.assertEqual(row['code_snippet'].count('____'),1)

    def test_append_2400_and_idempotency_preserves_old_rows(self):
        before=digest_snapshot(snapshot_existing())
        count,digest=apply_rows(self.rows)
        self.assertEqual(count,2280);self.assertEqual(before,digest)
        self.assertEqual(Question.objects.count(),2400)
        self.assertEqual(apply_rows(self.rows)[0],0)
        self.assertEqual(QuestionChoice.objects.count(),4800)
        self.assertEqual(LearningSession.objects.count(),0)
        self.assertEqual(UserAnswer.objects.count(),0)

    def test_code_conflict_stops_without_modification(self):
        apply_rows(self.rows)
        altered=[{**r,'explanation':'변경된 해설'} if i==0 else r for i,r in enumerate(self.rows)]
        before=digest_snapshot(snapshot_existing())
        with self.assertRaises(CommandError):apply_rows(altered)
        self.assertEqual(before,digest_snapshot(snapshot_existing()))

    def test_failure_rolls_back_all_inserted_questions(self):
        before=digest_snapshot(snapshot_existing())
        with patch.object(QuestionChoice.objects,'bulk_create',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):apply_rows(self.rows)
        self.assertEqual(before,digest_snapshot(snapshot_existing()))

    def test_dry_run_changes_no_data_and_apply_requires_backup(self):
        before=digest_snapshot(snapshot_existing())
        out=StringIO();call_command('import_learning_bank',file=DATA,stdout=out)
        self.assertEqual(json.loads(out.getvalue())['new_questions'],2280)
        with self.assertRaises(CommandError):call_command('import_learning_bank',file=DATA,apply=True,stdout=StringIO())
        self.assertEqual(before,digest_snapshot(snapshot_existing()))

    def test_new_sql_answers_accept_keyword_case_with_existing_grader(self):
        for row in self.rows:
            if row['subject']=='sql' and row['question_type']=='fill_blank':
                self.assertTrue(answers_match('sql','fill_blank',row['correct_answer'].lower(),row['correct_answer']),row['correct_answer'])
        self.assertFalse(answers_match('python','fill_blank','true','True'))
        self.assertFalse(answers_match('sql','fill_blank','CustomerName','customername'))

    def test_existing_answers_and_sessions_survive_import(self):
        user=get_user_model().objects.create_user(username='bank-history')
        prepare_event_context(user)
        session=services.start_learning_session(user,'fill_blank','beginner','python')
        item=services.get_current_question(user,session.pk,1)
        services.submit_answer(user,session.pk,1,item.question.correct_answer,submission_request_uuid=uuid.uuid4())
        sessions=list(LearningSession.objects.values());answers=list(UserAnswer.objects.values())
        apply_rows(self.rows)
        self.assertEqual(list(LearningSession.objects.values()),sessions)
        self.assertEqual(list(UserAnswer.objects.values()),answers)

    def test_all_12_pools_select_10_unique_matching_questions(self):
        apply_rows(self.rows)
        user=get_user_model().objects.create_user(username='bank-pools')
        prepare_event_context(user)
        for subject in ['python','sql']:
            for level in ['beginner','intermediate','advanced']:
                for kind in ['multiple_choice','fill_blank']:
                    session=services.start_learning_session(user,kind,level,subject)
                    items=list(session.session_questions.select_related('question'))
                    self.assertEqual(len(items),10)
                    self.assertEqual(len({i.question_id for i in items}),10)
                    self.assertTrue(all((i.question.subject,i.question.difficulty,i.question.question_type)==(subject,level,kind) for i in items))
