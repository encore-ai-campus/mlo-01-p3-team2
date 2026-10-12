import json
from pathlib import Path
from django.test import SimpleTestCase
from learning.bank_validation import validate_bank
class BankValidationTests(SimpleTestCase):
    def setUp(self):
        self.rows=json.loads((Path(__file__).parents[1]/'data/initial_subject_bank.json').read_text(encoding='utf-8'))
    def test_initial_structure_valid_but_full_target_fails(self):
        partial=validate_bank(self.rows,require_full=False)
        self.assertEqual(partial['errors'],[]);self.assertEqual(partial['total'],100)
        self.assertTrue(validate_bank(self.rows)['errors'])
        self.assertTrue(partial['warnings'])
    def test_duplicate_and_wrong_choices_fail(self):
        rows=[dict(self.rows[0]),dict(self.rows[0])]
        self.assertTrue(validate_bank(rows,False)['errors'])
        rows=[dict(self.rows[0],choices=['same']*4)]
        self.assertTrue(validate_bank(rows,False)['errors'])
