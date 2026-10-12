"""Offline bank structure checks. Semantic review remains a separate responsibility."""
from collections import Counter
import re
from .models import Subject, Difficulty, QuestionType

def validate_bank(rows, require_full=True):
    errors=[]; warnings=['의미상 중복, 난이도 적합성, Python/SQL 예제의 정확성은 별도 검토가 필요합니다.']
    groups=Counter();codes=set();texts=set()
    if not isinstance(rows,list):return {'errors':['JSON 배열이 필요합니다.'],'warnings':warnings,'groups':{}}
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict):errors.append(f'{index}: 문항 객체가 필요합니다.');continue
        subject,level,kind=row.get('subject'),row.get('difficulty'),row.get('question_type')
        if subject not in Subject.values or level not in Difficulty.values or kind not in QuestionType.values:
            errors.append(f'{index}: 과목/난이도/유형이 유효하지 않습니다.');continue
        groups[(subject,level,kind)]+=1
        code=row.get('question_code','');key=(subject,code)
        if not re.fullmatch(r'[BIA]-(MC|FB)-[0-9]{3}',code):errors.append(f'{index}: 문항 코드 형식 오류')
        if code and (code[0]!=level[0].upper() or code.split('-')[1]!=('MC' if kind=='multiple_choice' else 'FB')):errors.append(f'{index}: 코드와 분류가 다릅니다.')
        if key in codes:errors.append(f'{index}: 문항 코드 중복')
        codes.add(key)
        text=' '.join(str(row.get('question_text','')).split())
        if not text or text in texts:errors.append(f'{index}: 문제 본문 누락/중복')
        texts.add(text)
        for field in ['correct_answer','explanation','category']:
            if not isinstance(row.get(field),str) or not row[field].strip():errors.append(f'{index}: {field} 누락')
        choices=row.get('choices',[])
        if kind=='multiple_choice':
            if not isinstance(choices,list) or len(choices)!=4 or not all(isinstance(c,str) and c.strip() for c in choices) or len(set(c.strip() for c in choices))!=4:
                errors.append(f'{index}: 서로 다른 보기 4개가 필요합니다.')
            elif sum(c.strip()==str(row.get('correct_answer','')).strip() for c in choices)!=1:errors.append(f'{index}: 정답과 보기 불일치')
        elif choices:errors.append(f'{index}: 빈칸 문제에 보기가 있습니다.')
    for subject in Subject.values:
        for level in Difficulty.values:
            for kind in QuestionType.values:
                count=groups[(subject,level,kind)]
                if require_full and count!=200:errors.append(f'{subject}/{level}/{kind}: {count}/200')
    return {'errors':errors,'warnings':warnings,'groups':{'/'.join(k):v for k,v in sorted(groups.items())},'total':len(rows),'target':2400,'shortfall':max(0,2400-len(rows))}
