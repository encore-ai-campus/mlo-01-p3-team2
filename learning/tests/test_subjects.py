import json, uuid
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.core.exceptions import ValidationError
from learning import services
from learning.models import Question, QuestionChoice, LearningSession, SessionQuestion, UserAnswer
from learning.grading import answers_match
from learning.point_policy import points_for, eligibility

class GradingTests(SimpleTestCase):
    def test_sql_keyword_whitespace(self):
        for value in ['select * from users','SELECT  *  FROM users','SELECT\n*\tFROM users']:
            self.assertTrue(answers_match('sql','fill_blank',value,'SELECT * FROM users'))
    def test_literals_identifiers_operators_preserved(self):
        for value, correct in [("SELECT 'A  B'","SELECT 'A B'"),("SELECT 'A'","SELECT 'a'"),('SELECT "User"','SELECT "user"'),('SELECT userName','SELECT username'),('SELECT a < = b','SELECT a <= b'),('SELECT a--x','SELECT a - - x')]:
            self.assertFalse(answers_match('sql','fill_blank',value,correct))
        self.assertTrue(answers_match('sql','fill_blank',"select 'It''s  OK'", "SELECT 'It''s  OK'"))
    def test_sql_known_functions(self):
        self.assertTrue(answers_match('sql','fill_blank','dense_rank','DENSE_RANK'))
        self.assertTrue(answers_match('sql','fill_blank','row_number','ROW_NUMBER'))

    def test_python_case(self):
        self.assertTrue(answers_match('python','fill_blank',' append ','append'))
        self.assertFalse(answers_match('python','fill_blank','APPEND','append'))
    def test_policy_configuration(self):
        self.assertEqual([points_for(d) for d in ['beginner','intermediate','advanced']],[20,50,80])
        with override_settings(LEARNING_POINTS_BY_DIFFICULTY={'beginner':25}):self.assertEqual(points_for('beginner'),25)

class SubjectApiTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='subjects')
        self.client.force_login(self.user)
        for subject in ['python','sql']:
            for kind in ['multiple_choice','fill_blank']:
                for n in range(12):
                    q=Question.objects.create(subject=subject,question_type=kind,difficulty='beginner',category='concept',question_text=f'{subject} {kind} {n}',correct_answer='SELECT' if subject=='sql' else 'append',explanation='concept explanation')
                    if kind=='multiple_choice':
                        for number,text in enumerate([q.correct_answer,'wrong1','wrong2','wrong3'],1):QuestionChoice.objects.create(question=q,choice_no=number,choice_text=text)
    def post(self,url,data):return self.client.post(url,json.dumps(data),content_type='application/json')
    def start(self,subject='sql',kind='fill_blank'):
        response=self.post('/api/learning/sessions/',{'subject':subject,'question_type':kind,'difficulty':'beginner'})
        self.assertEqual(response.status_code,201)
        return response.json()['session_id']
    def test_subject_pool_and_stable_order(self):
        for subject in ['python','sql']:
            for kind in ['multiple_choice','fill_blank']:
                sid=self.start(subject,kind);session=LearningSession.objects.get(pk=sid)
                items=list(session.session_questions.select_related('question'))
                self.assertEqual(len(items),10);self.assertEqual(len({i.question_id for i in items}),10)
                self.assertTrue(all(i.question.subject==subject and i.question.question_type==kind for i in items))
                self.assertEqual(self.client.get(f'/api/learning/sessions/{sid}/').json()['questions'],self.client.get(f'/api/learning/sessions/{sid}/').json()['questions'])
    def test_under_ten_no_session_and_invalid_subject(self):
        Question.objects.filter(subject='sql',question_type='fill_blank').update(is_active=False)
        response=self.post('/api/learning/sessions/',{'subject':'sql','question_type':'fill_blank','difficulty':'beginner'})
        self.assertEqual(response.status_code,409);self.assertEqual(LearningSession.objects.count(),0)
        self.assertEqual(self.post('/api/learning/sessions/',{'subject':'bad','question_type':'fill_blank','difficulty':'beginner'}).status_code,400)
    def test_idempotency_snapshot_conflict_and_privacy(self):
        sid=self.start();base=f'/api/learning/sessions/{sid}/questions/1/'
        self.client.get(base);key=str(uuid.uuid4());data={'answer':'wrong','submission_request_uuid':key}
        first=self.post(base+'answers/',data).json()
        self.assertEqual(first,self.post(base+'answers/',data).json());self.assertEqual(UserAnswer.objects.count(),1)
        correct=self.post(base+'answers/',{'answer':'select','submission_request_uuid':str(uuid.uuid4())}).json()
        self.assertTrue(correct['is_correct']);self.assertEqual(correct['points']['status'],'not_connected');self.assertEqual(correct['points']['quoted_points'],20)
        self.assertEqual(first,self.post(base+'answers/',data).json());self.assertNotIn('correct_answer',first)
        self.assertEqual(self.post(base+'answers/',{'answer':'SELECT','submission_request_uuid':key}).status_code,409)
        self.assertEqual(UserAnswer.objects.count(),2)
        with override_settings(LEARNING_POINTS_BY_DIFFICULTY={'beginner':99}):
            replay=self.post(base+'answers/',{'answer':'select','submission_request_uuid':correct['submission_request_uuid']}).json()
            self.assertEqual(replay['points']['quoted_points'],20)
    def test_six_seven_ten_and_repeat_rewards(self):
        for correct_count in [6,7,10]:
            sid=self.start();base=f'/api/learning/sessions/{sid}/'
            for order in range(1,11):
                path=base+f'questions/{order}/';self.client.get(path)
                if order<=correct_count:
                    if order==1:self.post(path+'answers/',{'answer':'wrong'})
                    result=self.post(path+'answers/',{'answer':'select','submission_request_uuid':str(uuid.uuid4())}).json()
                    self.assertEqual(result['points']['quoted_points'],20)
                else:
                    for _ in range(3):self.post(path+'answers/',{'answer':'wrong'})
            result=self.post(base+'complete/',{}).json()
            self.assertEqual(result['correct_count'],correct_count);self.assertEqual(result['passed'],correct_count>=7)
            self.assertEqual(result['points_summary']['quoted_total'],correct_count*20)
            self.assertEqual(result['points_summary']['status'],'not_connected')
            self.assertIsNone(result['points_summary']['granted_total'])
            self.assertEqual(len(result['wrong_questions']),10-correct_count)
            self.assertEqual(self.client.get(base).json()['passed'],correct_count>=7)
        self.assertEqual(UserAnswer.objects.filter(is_correct=True).values('attempt_uuid').distinct().count(),23)
    def test_rewards_are_per_answer_not_pass_and_both_subjects_types_levels(self):
        for subject in ['python','sql']:
            for kind in ['multiple_choice','fill_blank']:
                for difficulty,amount in [('beginner',20),('intermediate',50),('advanced',80)]:
                    q=Question.objects.create(subject=subject,question_type=kind,difficulty=difficulty,category='policy',question_text=f'{subject}/{kind}/{difficulty}',correct_answer='answer',explanation='policy')
                    session=LearningSession.objects.create(user=self.user,subject=subject,question_type=kind,difficulty=difficulty,total_questions=1)
                    item=SessionQuestion.objects.create(session=session,question=q,question_order=1)
                    for attempt in [1,2,3]:
                        record=UserAnswer.objects.create(session_question=item,submitted_answer='answer',is_correct=True,attempt_no=attempt)
                        self.assertEqual(eligibility(record)['quoted_points'],amount)
                    wrong=UserAnswer.objects.create(session_question=item,submitted_answer='wrong',is_correct=False,attempt_no=4)
                    self.assertEqual(eligibility(wrong)['quoted_points'],0)

    def test_subject_relationship_validation(self):
        sid=self.start();q=Question.objects.filter(subject='python').first()
        with self.assertRaises(ValidationError):SessionQuestion.objects.create(session_id=sid,question=q,question_order=1)
