"""The four learning panels are catalogued separately from their random questions."""
from eventing.models import ContentItem

CONTENT_CODES = {(subject, kind): f'{subject}-{kind.replace("_", "-")}'
                 for subject in ('python', 'sql') for kind in ('multiple_choice', 'fill_blank')}


def get_learning_content(subject, question_type):
    code = CONTENT_CODES[(subject, question_type)]
    return ContentItem.objects.select_related('category', 'zone').get(
        code=code, status='ACTIVE', content_kind='QUIZ', category__domain='LEARNING', zone__isnull=False)
