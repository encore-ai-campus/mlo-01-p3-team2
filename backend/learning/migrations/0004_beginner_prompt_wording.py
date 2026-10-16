"""Clarify intended operations without changing question identities or grading."""
from django.db import migrations


CORRECTIONS = (
    ('list', 'numbers.____(4)', 'append', '리스트 numbers의 맨 끝에 숫자 4를 추가하려고 합니다. 빈칸에 들어갈 메서드 이름을 괄호 없이 쓰세요.'),
    ('variable', '____(42)', 'type', '정수 42의 자료형을 확인하려고 합니다. 빈칸에 들어갈 파이썬 내장 함수 이름을 괄호 없이 쓰세요.'),
    ('string', '____("Python")', 'len', '문자열 "Python"의 글자 수를 구하려고 합니다. 빈칸에 들어갈 파이썬 내장 함수 이름을 괄호 없이 쓰세요.'),
    ('operator', '7 ____ 3', '%', '7을 3으로 나눈 나머지를 구하려고 합니다. 빈칸에 들어갈 연산자를 쓰세요.'),
    ('condition', '____ score >= 60:\n    print("pass")', 'if', 'score가 60 이상일 때만 "pass"를 한 번 출력하려고 합니다. 빈칸에 들어갈 조건문 키워드를 쓰세요.'),
    ('loop', '____ item in [1, 2]:\n    print(item)', 'for', '리스트 [1, 2]의 요소를 순서대로 item에 넣어 출력하려고 합니다. 빈칸에 들어갈 반복문 키워드를 쓰세요.'),
    ('function', '____ greet():\n    return "hello"', 'def', '"hello"를 반환하는 일반 함수 greet를 정의하려고 합니다. 빈칸에 들어갈 키워드를 쓰세요.'),
    ('dictionary', 'person.____("name", "unknown")', 'get', '딕셔너리 person을 변경하지 않고 "name" 키의 값을 조회하려고 합니다. 키가 없으면 "unknown"을 반환하는 메서드 이름을 괄호 없이 쓰세요.'),
    ('set', 'values.____(3)', 'add', '집합(set) values에 숫자 3을 원소로 추가하려고 합니다. 빈칸에 들어갈 메서드 이름을 괄호 없이 쓰세요.'),
    ('exception', 'try:\n    int("x")\n____ ValueError:\n    print("invalid")', 'except', 'try 블록에서 발생한 ValueError를 처리해 "invalid"를 출력하려고 합니다. 빈칸에 들어갈 예외 처리 키워드를 쓰세요.'),
)


def update_wording(apps, schema_editor, reverse=False):
    Question = apps.get_model("learning", "Question")
    questions = Question.objects.using(schema_editor.connection.alias)
    for category, snippet, answer, prompt in CORRECTIONS:
        old, new = "코드의 빈칸을 채우세요.", prompt
        if reverse:
            old, new = new, old
        # Editorial correction only. Keep existing sessions and answer UUIDs attached
        # to the same question; no cloning, grading changes, points or raw events.
        questions.filter(subject="python", difficulty="beginner", question_type="fill_blank",
                         category=category, code_snippet=snippet, correct_answer=answer,
                         question_text=old).update(question_text=new)


def forward(apps, schema_editor):
    update_wording(apps, schema_editor)


def backward(apps, schema_editor):
    update_wording(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [("learning", "0003_learning_events_points")]
    operations = [migrations.RunPython(forward, backward)]
