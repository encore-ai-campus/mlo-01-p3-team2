from functools import wraps
from datetime import timedelta
import json
import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from accounts.models import Profile, needs_profile_setup
from . import service
from .models import Conversation, Message
from .live import notify


def error(message, status=400):
    return JsonResponse({'error':message},status=status)


def endpoint(methods, *, starter=False):
    def decorate(view):
        @never_cache
        @wraps(view)
        def wrapped(request,*args,**kwargs):
            if not request.user.is_authenticated:return error('다시 로그인해 주세요.',401)
            if not service.enabled():return error('쪽지를 사용할 수 없습니다.',404)
            if not request.user.is_active:return error('사용할 수 없는 계정입니다.',403)
            if needs_profile_setup(request.user):return error('캐릭터 설정을 먼저 완료해 주세요.',403)
            if request.method not in methods:
                response=error('지원하지 않는 요청입니다.',405);response['Allow']=', '.join(methods);return response
            if starter and not service.can_start(request.user):return error('새 대화 시작 권한이 없습니다.',403)
            return view(request,*args,**kwargs)
        return wrapped
    return decorate


def payload(request):
    if request.content_type!='application/json':raise ValueError('JSON 형식으로 보내 주세요.')
    if len(request.body)>20000:raise ValueError('입력한 내용이 너무 깁니다.')
    try:data=json.loads(request.body)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('요청 내용을 확인해 주세요.')
    if not isinstance(data,dict):raise ValueError('요청 내용을 확인해 주세요.')
    return data


def message_data(message,user):
    return {'id':str(message.id),'body':message.body,'sentByMe':message.sender_id==user.pk,
            'createdAt':message.created_at.isoformat(),'readAt':message.read_at.isoformat() if message.read_at else None}


def own_conversation(request,conversation_id):
    return service.conversations(request.user).select_related('first_user__campus_profile','second_user__campus_profile').filter(pk=conversation_id).first()


@ensure_csrf_cookie
@endpoint(['GET'])
def status(request):
    return JsonResponse({**service.configuration(request.user),'unread':service.unread(request.user)})


@endpoint(['GET'],starter=True)
def recipients(request):
    query=request.GET.get('q','').strip()[:40]
    if not query:return JsonResponse({'recipients':[]})
    matches=Profile.objects.select_related('user').filter(user__is_active=True,setup_complete=True,nickname__icontains=query).exclude(user=request.user).order_by('nickname','user_uuid')[:20]
    return JsonResponse({'recipients':[service.identity(p.user) for p in matches]})


@endpoint(['GET'])
def inbox(request):
    items=[]
    for conversation in service.conversations(request.user).select_related('first_user__campus_profile','second_user__campus_profile').order_by('-updated_at')[:50]:
        other=conversation.second_user if conversation.first_user_id==request.user.pk else conversation.first_user
        latest=conversation.messages.order_by('-created_at','-id').first()
        if latest is None:continue
        items.append({'id':str(conversation.pk),'other':service.identity(other),'preview':latest.body[:80],
                      'updatedAt':latest.created_at.isoformat(),'unread':conversation.messages.filter(recipient=request.user,read_at__isnull=True).count()})
    return JsonResponse({'conversations':items})


@endpoint(['GET'])
def history(request,conversation_id):
    conversation=own_conversation(request,conversation_id)
    if conversation is None:return error('대화를 찾을 수 없습니다.',404)
    other=conversation.second_user if conversation.first_user_id==request.user.pk else conversation.first_user
    rows=list(conversation.messages.order_by('-created_at','-id')[:100]);rows.reverse()
    return JsonResponse({'id':str(conversation.pk),'other':service.identity(other),
                         'messages':[message_data(row,request.user) for row in rows]})


@endpoint(['POST'])
def send(request):
    try:
        data=payload(request);recipient_id=uuid.UUID(str(data.get('recipient','')));request_id=uuid.UUID(str(data.get('requestId','')))
        body=data.get('body')
        if not isinstance(body,str) or not body.strip() or len(body)>2000:raise ValueError('메시지를 1~2000자로 입력해 주세요.')
        body=body.strip()
        if any(ord(c)<32 and c not in '\n\t' for c in body):raise ValueError('메시지에 사용할 수 없는 문자가 있습니다.')
    except (ValueError,TypeError,AttributeError) as exc:return error(str(exc) or '요청 내용을 확인해 주세요.')
    profile=Profile.objects.select_related('user').filter(user_uuid=recipient_id,user__is_active=True,setup_complete=True).first()
    if profile is None:return error('받는 사람을 찾을 수 없습니다.',404)
    recipient=profile.user
    if recipient.pk==request.user.pk:return error('다른 사람을 선택해 주세요.')
    first,second=sorted([request.user.pk,recipient.pk])
    with transaction.atomic():
        # Lock the pair in one global order: opposite first sends share one conversation
        # without locking each other's foreign-key rows in reverse order on MySQL.
        list(get_user_model().objects.select_for_update().filter(pk__in=[first,second]).order_by('pk').values_list('pk',flat=True))
        previous=Message.objects.filter(sender=request.user,request_id=request_id).first()
        if previous:
            if previous.recipient_id!=recipient.pk or previous.body!=body:return error('이미 사용한 전송 번호입니다.',409)
            return JsonResponse({'conversationId':str(previous.conversation_id),'message':message_data(previous,request.user)})
        conversation=Conversation.objects.filter(first_user_id=first,second_user_id=second).first()
        if conversation is None and not service.can_start(request.user):return error('새 대화 시작 권한이 없습니다.',403)
        if Message.objects.filter(sender=request.user,created_at__gt=timezone.now()-timedelta(seconds=1)).exists():return error('잠시 후 다시 보내 주세요.',429)
        if conversation is None:conversation,_=Conversation.objects.get_or_create(first_user_id=first,second_user_id=second)
        message=Message.objects.create(conversation=conversation,sender=request.user,recipient=recipient,body=body,request_id=request_id)
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.created_at)
        transaction.on_commit(lambda:notify(recipient.pk,conversation.pk),robust=True)
        transaction.on_commit(lambda:notify(request.user.pk,conversation.pk),robust=True)
    return JsonResponse({'conversationId':str(conversation.pk),'message':message_data(message,request.user)},status=201)


@endpoint(['POST'])
def mark_read(request,conversation_id):
    conversation=own_conversation(request,conversation_id)
    if conversation is None:return error('대화를 찾을 수 없습니다.',404)
    try:through=uuid.UUID(str(payload(request).get('through','')))
    except (ValueError,TypeError,AttributeError):return error('읽은 메시지를 확인해 주세요.')
    cursor=conversation.messages.filter(pk=through).first()
    if cursor is None:return error('메시지를 찾을 수 없습니다.',404)
    with transaction.atomic():
        changed=conversation.messages.filter(recipient=request.user,read_at__isnull=True).filter(
            Q(created_at__lt=cursor.created_at)|Q(created_at=cursor.created_at,id__lte=cursor.pk)
        ).update(read_at=timezone.now())
        if changed:
            for user_id in (conversation.first_user_id,conversation.second_user_id):
                transaction.on_commit(lambda user_id=user_id:notify(user_id,conversation.pk),robust=True)
    return JsonResponse({'unread':service.unread(request.user)})
