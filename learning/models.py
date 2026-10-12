import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.db.models.signals import pre_delete
from django.dispatch import receiver


class Subject(models.TextChoices):
    PYTHON = 'python', 'Python'
    SQL = 'sql', 'SQL'


class QuestionType(models.TextChoices):
    MULTIPLE_CHOICE = 'multiple_choice', '4지선다'
    FILL_BLANK = 'fill_blank', '코드 빈칸'


class Difficulty(models.TextChoices):
    BEGINNER = 'beginner', '초급'
    INTERMEDIATE = 'intermediate', '중급'
    ADVANCED = 'advanced', '고급'


def type_constraints(prefix):
    return [models.CheckConstraint(condition=Q(question_type__in=QuestionType.values), name=prefix + '_type_valid'),
            models.CheckConstraint(condition=Q(difficulty__in=Difficulty.values), name=prefix + '_difficulty_valid')]


class Question(models.Model):
    question_id = models.BigAutoField(primary_key=True)
    subject = models.CharField(max_length=10, choices=Subject.choices, default=Subject.PYTHON)
    question_code = models.CharField(max_length=32, null=True, blank=True)
    question_type = models.CharField(max_length=20, choices=QuestionType.choices)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices)
    category = models.CharField(max_length=40)
    question_text = models.TextField()
    code_snippet = models.TextField(null=True, blank=True)
    correct_answer = models.TextField()
    explanation = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = type_constraints('question') + [models.CheckConstraint(condition=Q(subject__in=Subject.values), name='question_subject_valid'), models.UniqueConstraint(fields=['subject','question_code'], name='subject_question_code_unique')]
        indexes = [models.Index(fields=['subject', 'difficulty', 'question_type', 'is_active'], name='question_subject_pool_idx')]

    def clean(self):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            fields = ('subject', 'question_type', 'difficulty', 'category', 'question_text', 'code_snippet', 'correct_answer', 'explanation')
            if old and old.question_code is not None and old.question_code != self.question_code:
                raise ValidationError('기존 문제 식별자는 변경할 수 없습니다.')
            if old and self.session_questions.exists() and any(getattr(old, f) != getattr(self, f) for f in fields):
                raise ValidationError('출제된 문제는 변경할 수 없습니다. 비활성화 후 새 문제를 만드세요.')
            if self.question_type == QuestionType.FILL_BLANK and self.choices.exists():
                raise ValidationError('빈칸 문제에는 보기가 없어야 합니다.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.pk}: {self.question_text[:50]}'


class QuestionChoice(models.Model):
    choice_id = models.BigAutoField(primary_key=True)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    choice_no = models.PositiveSmallIntegerField()
    choice_text = models.TextField()

    class Meta:
        ordering = ['choice_no']
        constraints = [models.UniqueConstraint(fields=['question', 'choice_no'], name='choice_question_no_unique'),
                       models.CheckConstraint(condition=Q(choice_no__gte=1, choice_no__lte=4), name='choice_no_range')]

    def clean(self):
        if self.question_id:
            if self.question.question_type != QuestionType.MULTIPLE_CHOICE:
                raise ValidationError('객관식 문제에만 보기를 추가할 수 있습니다.')
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            used = self.question.session_questions.exists() or (old and old.question.session_questions.exists())
            if used and (not old or any(getattr(old, f) != getattr(self, f) for f in ('question_id', 'choice_no', 'choice_text'))):
                raise ValidationError('출제된 문제의 보기는 변경할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LearningSession(models.Model):
    session_id = models.BigAutoField(primary_key=True)
    subject = models.CharField(max_length=10, choices=Subject.choices, default=Subject.PYTHON)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='learning_sessions')
    question_type = models.CharField(max_length=20, choices=QuestionType.choices)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_questions = models.PositiveSmallIntegerField(default=10)
    correct_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = type_constraints('session') + [
            models.CheckConstraint(condition=Q(subject__in=Subject.values), name='session_subject_valid'),
            models.CheckConstraint(condition=Q(total_questions__gte=1, total_questions__lte=10), name='session_total_range'),
            models.CheckConstraint(condition=Q(correct_count__gte=0, correct_count__lte=F('total_questions')), name='session_correct_range')]

    def clean(self):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and any(getattr(old, f) != getattr(self, f) for f in ('user_id', 'subject', 'question_type', 'difficulty', 'total_questions')):
            raise ValidationError('생성된 세션의 사용자, 유형, 난이도, 문제 수는 변경할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SessionQuestion(models.Model):
    session_question_id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(LearningSession, on_delete=models.PROTECT, related_name='session_questions')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='session_questions')
    question_order = models.PositiveSmallIntegerField()
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['question_order']
        constraints = [models.UniqueConstraint(fields=['session', 'question'], name='session_question_unique'),
                       models.UniqueConstraint(fields=['session', 'question_order'], name='session_order_unique'),
                       models.CheckConstraint(condition=Q(question_order__gte=1, question_order__lte=10), name='question_order_range')]

    def clean(self):
        if self.session_id and self.question_id:
            if (self.session.subject, self.session.question_type, self.session.difficulty) != (self.question.subject, self.question.question_type, self.question.difficulty):
                raise ValidationError('세션과 문제의 유형 및 난이도가 일치해야 합니다.')
            if self.question_order > self.session.total_questions:
                raise ValidationError('출제 순서가 세션 문제 수를 초과합니다.')
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and any(getattr(old, f) != getattr(self, f) for f in ('session_id', 'question_id', 'question_order')):
            raise ValidationError('출제 기록은 재배치할 수 없습니다.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class UserAnswer(models.Model):
    answer_id = models.BigAutoField(primary_key=True)
    attempt_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission_request_uuid = models.UUIDField(null=True, blank=True, unique=True)
    response_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    session_question = models.ForeignKey(SessionQuestion, on_delete=models.PROTECT, related_name='answers')
    submitted_answer = models.TextField()
    is_correct = models.BooleanField()
    attempt_no = models.PositiveIntegerField(default=1)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['attempt_no']
        constraints = [models.UniqueConstraint(fields=['session_question', 'attempt_no'], name='answer_attempt_unique'),
                       models.CheckConstraint(condition=Q(attempt_no__gte=1), name='answer_attempt_positive')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('제출 기록은 수정할 수 없습니다.')
        self.full_clean()
        return super().save(*args, **kwargs)


@receiver(pre_delete, sender=QuestionChoice)
def protect_used_choice(sender, instance, **kwargs):
    if instance.question.session_questions.exists():
        raise ValidationError('출제된 문제의 보기는 삭제할 수 없습니다.')


@receiver(pre_delete, sender=UserAnswer)
def protect_answer(sender, instance, **kwargs):
    raise ValidationError('제출 기록은 삭제할 수 없습니다.')
