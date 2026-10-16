"""Append a validated bank without updating existing questions or history."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

from django.apps import apps
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from learning.bank_validation import validate_bank
from learning.models import Question, QuestionChoice

FIELDS=('subject','difficulty','question_type','question_code','category','question_text','code_snippet','correct_answer','explanation')
GROUP=('subject','difficulty','question_type')
TARGET={ (s,d,t):200 for s in ('python','sql') for d in ('beginner','intermediate','advanced') for t in ('multiple_choice','fill_blank') }

def snapshot_existing():
    questions=list(Question.objects.order_by('pk').values())
    choices=list(QuestionChoice.objects.order_by('pk').values())
    return questions,choices

def digest_snapshot(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,default=str,ensure_ascii=True).encode()).hexdigest()

def plan(rows):
    report=validate_bank(rows,require_full=False)
    if report['errors']:raise CommandError('; '.join(report['errors']))
    existing={(q.subject,q.question_code):q for q in Question.objects.prefetch_related('choices') if q.question_code}
    counts=Counter()
    for q in Question.objects.filter(is_active=True).values(*GROUP):counts[tuple(q[k] for k in GROUP)]+=1
    pending=[]
    for row in rows:
        q=existing.get((row['subject'],row['question_code']))
        if q:
            expected={k:row.get(k) for k in FIELDS}
            actual={k:getattr(q,k) for k in FIELDS}
            # Export omits optional code_snippet; normalize omission to None only.
            if actual!=expected or [c.choice_text for c in q.choices.all()]!=row.get('choices',[]) or not q.is_active:
                raise CommandError('기존 문항 코드의 내용 또는 활성 상태가 다릅니다: '+row['subject']+'/'+row['question_code'])
        else:
            pending.append(row);counts[tuple(row[k] for k in GROUP)]+=1
    if counts!=Counter(TARGET):
        raise CommandError('반영 후 활성 문제 수가 분류별 200개가 아닙니다: '+str(dict(counts)))
    return pending

def backup(destination):
    folder=Path(destination)/('learning-bank-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    target=folder/'learning-before.json'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as out:
        objects=(obj for model in apps.get_app_config('learning').get_models() for obj in model.objects.order_by('pk').iterator())
        serializers.serialize('json',objects,stream=out,ensure_ascii=False)
    return folder

def apply_rows(rows):
    # Full preflight and insertion share one transaction. No UPDATE/DELETE is used.
    with transaction.atomic():
        if connection.vendor=='sqlite':
            with connection.cursor() as cur:
                cur.execute('UPDATE '+connection.ops.quote_name(Question._meta.db_table)+' SET is_active=is_active WHERE 0')
        pending=plan(rows)
        before=snapshot_existing()
        Question.objects.bulk_create([Question(**{k:r.get(k) for k in FIELDS}) for r in pending],batch_size=100)
        codes={(r['subject'],r['question_code']) for r in pending}
        ids={(q.subject,q.question_code):q.pk for q in Question.objects.filter(question_code__in={r['question_code'] for r in pending}) if (q.subject,q.question_code) in codes}
        QuestionChoice.objects.bulk_create([QuestionChoice(question_id=ids[(r['subject'],r['question_code'])],choice_no=n,choice_text=text)
            for r in pending for n,text in enumerate(r.get('choices',[]),1)],batch_size=200)
        old_q,old_c=before
        after=(list(Question.objects.filter(pk__in=[r['question_id'] for r in old_q]).order_by('pk').values()),
               list(QuestionChoice.objects.filter(pk__in=[r['choice_id'] for r in old_c]).order_by('pk').values()))
        if digest_snapshot(before)!=digest_snapshot(after):raise CommandError('기존 문항 보존 검사 실패: 전체 트랜잭션 취소')
        if plan(rows):raise CommandError('반영 후 멱등성 검사 실패')
        return len(pending),digest_snapshot(before)

class Command(BaseCommand):
    help='기존 문항과 학습 기록을 보존하고 분류별 200개가 되도록 문제은행을 추가합니다. 기본은 dry-run입니다.'
    def add_arguments(self,parser):
        parser.add_argument('--file',type=Path,required=True)
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--backup-dir',type=Path)
    def handle(self,*args,**options):
        try:rows=json.loads(options['file'].read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as error:raise CommandError(str(error))
        acquired=False
        try:
            if connection.vendor=='mysql':
                with connection.cursor() as cur:
                    cur.execute("SELECT GET_LOCK('learning_bank_import_v1',0)")
                    acquired=cur.fetchone()[0]==1
                    if not acquired:raise CommandError('다른 문제은행 반영 작업이 진행 중입니다.')
            pending=plan(rows)
            result={'mode':'dry-run','new_questions':len(pending),'skipped':len(rows)-len(pending),'target_active':2400}
            if options['apply']:
                if not options['backup_dir']:raise CommandError('--apply에는 --backup-dir이 필요합니다.')
                folder=backup(options['backup_dir'])
                count,digest=apply_rows(rows)
                result.update(mode='applied',new_questions=count,backup=str(folder),preserved_questions_sha256=digest)
            self.stdout.write(json.dumps(result,ensure_ascii=True))
        finally:
            if acquired:
                with connection.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('learning_bank_import_v1')")
