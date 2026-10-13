from functools import wraps
import json
import uuid

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.models import get_avatar, get_nickname, needs_profile_setup
from .forms import CommentForm, PostForm
from .models import Comment, Post
from eventing.events import record_comment_event, record_post_event


CATEGORY_DESCRIPTIONS = {
    "notice": "캠퍼스 소식과 운영 안내를 확인해요.",
    "free": "일상 이야기부터 가벼운 고민까지 자유롭게 나눠요.",
    "it": "Codex 토큰 초기화 소식, AI 도구별 전망과 IT 소식을 나눠요.",
    "project": "만든 서비스 소개, 포트폴리오와 코드 리뷰 요청을 올려요.",
    "career": "채용 공고, 면접 후기, 이력서 피드백과 직무 고민을 나눠요.",
    "study": "강의·책 추천, 정리 노트와 유용한 개발 도구를 공유해요.",
    "question": "코드 오류, 환경 설정과 수업 중 궁금했던 내용을 질문해요.",
}


def error(message, status=400, fields=None):
    data = {"error": message}
    if fields:
        data["fields"] = fields
    return JsonResponse(data, status=status)


def community_api(methods):
    def decorate(view):
        @never_cache
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error("다시 로그인해 주세요.", 401)
            if needs_profile_setup(request.user):
                return error("닉네임과 캐릭터 설정을 먼저 완료해 주세요.", 403)
            if request.method not in methods:
                response = error("지원하지 않는 요청입니다.", 405)
                response["Allow"] = ", ".join(methods)
                return response
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def payload(request):
    if request.content_type != "application/json":
        return None, error("JSON 형식으로 요청해 주세요.", 415)
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > 100000:
            return None, error("입력한 내용이 너무 깁니다.", 413)
        raw = request.body
        if len(raw) > 100000:
            return None, error("입력한 내용이 너무 깁니다.", 413)
        data = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None, error("요청 내용을 확인해 주세요.")
    if not isinstance(data, dict):
        return None, error("요청 내용을 확인해 주세요.")
    for key in ("title", "body", "category", "version"):
        if key in data and not isinstance(data[key], str):
            return None, error("문자열 형식으로 입력해 주세요.")
    return data, None


def form_error(form):
    fields = {key: [str(message) for message in messages] for key, messages in form.errors.items()}
    return error(next(iter(fields.values()))[0], fields=fields)


def author_data(user):
    return {"id": user.pk, "nickname": get_nickname(user), "avatar": get_avatar(user)}


def can_manage(request, item):
    return request.user.is_staff or item.author_id == request.user.pk


def post_data(post, request, detail=False):
    data = {
        "id": post.pk, "category": post.category, "categoryLabel": post.get_category_display(),
        "postUuid": str(post.post_uuid), "revision": post.revision,
        "title": post.title, "author": author_data(post.author),
        "createdAt": post.created_at.isoformat(), "updatedAt": post.updated_at.isoformat(),
        "commentCount": getattr(post, "comment_count", 0),
        "canEdit": can_manage(request, post) and (post.category != Post.Category.NOTICE or request.user.is_staff),
        "canDelete": can_manage(request, post),
    }
    if detail:
        data["body"] = post.body
    return data


def comment_data(comment, request):
    deleted = comment.deleted_at is not None
    data = {
        "id": comment.pk, "commentUuid": str(comment.comment_uuid), "revision": comment.revision,
        "parentCommentUuid": str(comment.parent_id) if comment.parent_id else None,
        "postId": comment.post_id, "body": "삭제된 댓글입니다." if deleted else comment.body,
        "author": None if deleted else author_data(comment.author), "createdAt": comment.created_at.isoformat(),
        "updatedAt": comment.updated_at.isoformat(), "isDeleted": deleted,
        "canEdit": not deleted and can_manage(request, comment),
        "canDelete": not deleted and can_manage(request, comment),
        "canReply": not deleted and comment.parent_id is None,
    }
    if comment.parent_id is None:
        data["replies"] = [comment_data(reply, request) for reply in getattr(comment, "visible_replies", [])]
    return data


def posts_query():
    return Post.objects.filter(deleted_at__isnull=True).select_related(
        "author", "author__campus_profile"
    ).annotate(comment_count=Count("comments", filter=Q(comments__deleted_at__isnull=True))).order_by("-created_at", "-pk")


def page_for(request, query, size):
    try:
        number = int(request.GET.get("page", "1"))
        if not 1 <= number <= 100000:
            raise ValueError
    except ValueError:
        return None, error("페이지 번호를 확인해 주세요.")
    paginator = Paginator(query, size)
    page = paginator.get_page(number)
    return (page, {"page": page.number, "pages": paginator.num_pages, "total": paginator.count}), None


@community_api(["GET"])
def metadata(request):
    counts = dict(Post.objects.order_by().values_list("category").annotate(total=Count("pk")))
    return JsonResponse({
        "categories": [{"id": key, "name": label, "description": CATEGORY_DESCRIPTIONS[key],
                        "count": counts.get(key, 0), "canWrite": key != Post.Category.NOTICE or request.user.is_staff}
                       for key, label in Post.Category.choices],
        "total": sum(counts.values()), "user": {**author_data(request.user), "isAdmin": request.user.is_staff},
        "limits": {"title": 140, "body": 20000, "comment": 2000},
    })


@community_api(["GET", "POST"])
def posts(request):
    if request.method == "GET":
        category = request.GET.get("category", "all")
        if category != "all" and category not in Post.Category.values:
            return error("게시판을 확인해 주세요.")
        search = request.GET.get("q", "").strip()
        if len(search) > 100:
            return error("검색어는 100자까지 입력할 수 있어요.")
        query = posts_query()
        if category != "all":
            query = query.filter(category=category)
        if search:
            query = query.filter(Q(title__icontains=search) | Q(body__icontains=search))
        result, failure = page_for(request, query, 12)
        if failure:
            return failure
        page, pagination = result
        return JsonResponse({"posts": [post_data(item, request) for item in page], "pagination": pagination})
    data, failure = payload(request)
    if failure:
        return failure
    if data.get("category") == Post.Category.NOTICE and not request.user.is_staff:
        return error("공지사항은 관리자만 작성할 수 있어요.", 403)
    form = PostForm(data)
    if not form.is_valid():
        return form_error(form)
    item = form.save(commit=False)
    item.author = request.user
    with transaction.atomic():
        item.save()
        item.comment_count = 0
        record_post_event("post_created", request.user, request.session.get("platform_session_uuid"), item)
    return JsonResponse({"post": post_data(item, request, detail=True)}, status=201)


@community_api(["GET", "PATCH", "DELETE"])
def post_detail(request, post_id):
    item = posts_query().filter(pk=post_id).first()
    if item is None:
        return error("글이 삭제되었거나 존재하지 않아요.", 404)
    if request.method == "GET":
        with transaction.atomic():
            record_post_event("post_read", request.user, request.session.get("platform_session_uuid"), item)
        return JsonResponse({"post": post_data(item, request, detail=True)})
    if not can_manage(request, item):
        return error("본인이 쓴 글만 수정하거나 삭제할 수 있어요.", 403)
    if request.method == "DELETE":
        now = timezone.now()
        next_revision = item.revision + 1
        with transaction.atomic():
            updated = Post.objects.filter(
                pk=post_id, deleted_at__isnull=True, revision=item.revision
            ).update(deleted_at=now, updated_at=now, revision=next_revision)
            if not updated:
                return error("다른 화면에서 수정된 글이에요. 최신 글을 다시 확인해 주세요.", 409)
            item.revision = next_revision
            record_post_event("post_deleted", request.user, request.session.get("platform_session_uuid"), item)
        return JsonResponse({"deleted": True})
    data, failure = payload(request)
    if failure:
        return failure
    if (data.get("category", item.category) == Post.Category.NOTICE or item.category == Post.Category.NOTICE) and not request.user.is_staff:
        return error("공지사항은 관리자만 수정할 수 있어요.", 403)
    if data.get("version") != item.updated_at.isoformat():
        return error("다른 화면에서 수정된 글이에요. 최신 글을 다시 확인해 주세요.", 409)
    form = PostForm({key: data.get(key, getattr(item, key)) for key in ("category", "title", "body")}, instance=item)
    if not form.is_valid():
        return form_error(form)
    now = timezone.now()
    next_revision = item.revision + 1
    with transaction.atomic():
        updated = Post.objects.filter(
            pk=post_id, deleted_at__isnull=True, revision=item.revision, updated_at=item.updated_at
        ).update(**form.cleaned_data, updated_at=now, revision=next_revision)
        if not updated:
            return error("다른 화면에서 수정된 글이에요. 최신 글을 다시 확인해 주세요.", 409)
        item.revision = next_revision
        record_post_event("post_updated", request.user, request.session.get("platform_session_uuid"), item)
    return JsonResponse({"post": post_data(posts_query().get(pk=post_id), request, detail=True)})


@community_api(["GET", "POST"])
def comments(request, post_id):
    post = Post.objects.filter(pk=post_id, deleted_at__isnull=True).first()
    if post is None:
        return error("글이 삭제되었거나 존재하지 않아요.", 404)
    if request.method == "GET":
        # Paginate whole threads so a reply cannot appear without its parent.
        replies = Comment.objects.filter(deleted_at__isnull=True).select_related("author", "author__campus_profile")
        threads = Comment.objects.filter(post_id=post_id, parent__isnull=True).select_related(
            "author", "author__campus_profile"
        ).annotate(reply_count=Count("replies", filter=Q(replies__deleted_at__isnull=True))).filter(
            Q(deleted_at__isnull=True) | Q(reply_count__gt=0)
        ).prefetch_related(Prefetch("replies", queryset=replies, to_attr="visible_replies")).order_by("created_at", "pk")
        result, failure = page_for(request, threads, 30)
        if failure:
            return failure
        page, pagination = result
        return JsonResponse({
            "comments": [comment_data(item, request) for item in page], "pagination": pagination,
            "commentCount": Comment.objects.filter(post_id=post_id, deleted_at__isnull=True).count(),
        })
    data, failure = payload(request)
    if failure:
        return failure
    form = CommentForm(data)
    if not form.is_valid():
        return form_error(form)
    parent_uuid = data.get("parentCommentUuid")
    if parent_uuid is not None:
        try:
            if not isinstance(parent_uuid, str):
                raise ValueError
            parent_uuid = uuid.UUID(parent_uuid)
            if parent_uuid.version != 4:
                raise ValueError
        except ValueError:
            return error("답글을 달 댓글을 확인해 주세요.")
    item = form.save(commit=False)
    item.post_id = post_id
    item.author = request.user
    with transaction.atomic():
        if parent_uuid is not None:
            parent = Comment.objects.select_for_update().filter(
                comment_uuid=parent_uuid, post_id=post_id, deleted_at__isnull=True
            ).first()
            if parent is None:
                return error("답글을 달 댓글이 삭제되었거나 존재하지 않아요.", 404)
            if parent.parent_id is not None:
                return error("답글은 원래 댓글에 남겨 주세요.")
            item.parent = parent
        item.save()
        item.post = post
        record_comment_event("comment_created", request.user, request.session.get("platform_session_uuid"), item)
    return JsonResponse({"comment": comment_data(item, request)}, status=201)


@community_api(["PATCH", "DELETE"])
def comment_detail(request, comment_id):
    item = Comment.objects.select_related("author", "author__campus_profile", "post").filter(
        pk=comment_id, deleted_at__isnull=True, post__deleted_at__isnull=True
    ).first()
    if item is None:
        return error("댓글이 삭제되었거나 존재하지 않아요.", 404)
    if not can_manage(request, item):
        return error("본인이 쓴 댓글만 수정하거나 삭제할 수 있어요.", 403)
    if request.method == "DELETE":
        now = timezone.now()
        next_revision = item.revision + 1
        with transaction.atomic():
            updated = Comment.objects.filter(
                pk=comment_id, deleted_at__isnull=True, revision=item.revision
            ).update(deleted_at=now, updated_at=now, revision=next_revision)
            if not updated:
                return error("다른 화면에서 수정된 댓글이에요. 최신 댓글을 다시 확인해 주세요.", 409)
            item.revision = next_revision
            record_comment_event("comment_deleted", request.user, request.session.get("platform_session_uuid"), item)
        return JsonResponse({"deleted": True})
    data, failure = payload(request)
    if failure:
        return failure
    if "parentCommentUuid" in data:
        return error("댓글의 답글 대상은 변경할 수 없어요.")
    if data.get("version") != item.updated_at.isoformat():
        return error("다른 화면에서 수정된 댓글이에요. 최신 댓글을 다시 확인해 주세요.", 409)
    form = CommentForm(data, instance=item)
    if not form.is_valid():
        return form_error(form)
    now = timezone.now()
    next_revision = item.revision + 1
    with transaction.atomic():
        updated = Comment.objects.filter(
            pk=comment_id, deleted_at__isnull=True, revision=item.revision, updated_at=item.updated_at
        ).update(body=form.cleaned_data["body"], updated_at=now, revision=next_revision)
        if not updated:
            return error("다른 화면에서 수정된 댓글이에요. 최신 댓글을 다시 확인해 주세요.", 409)
        item.revision = next_revision
        record_comment_event("comment_updated", request.user, request.session.get("platform_session_uuid"), item)
    return JsonResponse({"comment": comment_data(Comment.objects.select_related("author", "author__campus_profile").get(pk=comment_id), request)})
